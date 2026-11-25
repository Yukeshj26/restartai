import os
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
GROK_CHAT_URL = "https://api.x.ai/v1/chat/completions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are the explanation layer for RestartAI, an emergency factory parts-recovery agent.

A deterministic Python engine has already:
- called suppliers, collected offers
- computed every plan's cost, arrival time, recovery time, downtime exposure and feasibility
- ranked the plans and selected a recommended plan

Your ONLY job is to explain that existing recommendation to a factory manager in clear, confident,
plain-English business language. You are NOT allowed to:
- change the recommended plan
- invent or alter any number (cost, hours, quantities, exposure)
- recommend a different plan than the one marked as recommended

Use only the numbers given to you. If information is missing, say so rather than guessing.
Keep it to 3-5 short sentences plus, if useful, one short bullet list of trade-offs versus the
next-best alternative. Write for a manager deciding under time pressure at 2am, not an executive report.
"""

CHAT_SYSTEM_PROMPT = """You are the assistant chatbot embedded in RestartAI's operator dashboard, sitting
beside a live emergency parts-recovery run.

You will be given the current run's data: the incident (machine, part, quantity, deadline,
downtime cost), every supplier offer collected so far (status, quantity, price, ETA), the
technician/maintenance intelligence, and the ranked recovery plans (if any exist yet).

Answer the operator's questions about THIS run using ONLY the data you are given. You may:
- explain why a plan was or wasn't recommended
- summarize supplier offers or compare them
- explain technician/installation constraints
- do simple arithmetic on the numbers provided

You must NOT:
- invent numbers, suppliers, or offers that are not in the data
- change or second-guess the recommended plan yourself — you can explain it, not overrule it
- speculate about suppliers who haven't responded yet

If the operator asks something the data doesn't cover, say plainly that you don't have that
information rather than guessing. Keep answers short and conversational — 2-4 sentences unless
the operator explicitly asks for more detail.
"""

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-2.5-flash",
    "grok": "grok-4.1-fast",
    "groq": "openai/gpt-oss-120b",
}


class LlmError(RuntimeError):
    pass


class LlmService:
    def __init__(self):
        provider = os.getenv("LLM_PROVIDER", "").strip().lower()
        if not provider:
            if os.getenv("GEMINI_API_KEY"):
                provider = "gemini"
            elif os.getenv("GROQ_API_KEY"):
                provider = "groq"
            elif os.getenv("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.getenv("GROK_API_KEY"):
                provider = "grok"
            else:
                provider = "gemini"
        elif provider not in DEFAULT_MODELS:
            logger.warning("Unknown LLM_PROVIDER=%s, falling back to gemini", provider)
            provider = "gemini"
        self.provider = provider

        key_env = {
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "grok": "GROK_API_KEY",
            "groq": "GROQ_API_KEY",
        }.get(self.provider, "GEMINI_API_KEY")
        self.api_key = os.getenv(key_env, "").strip()

        model_env = {
            "anthropic": "ANTHROPIC_MODEL",
            "gemini": "GEMINI_MODEL",
            "grok": "GROK_MODEL",
            "groq": "GROQ_MODEL",
        }.get(self.provider, "GEMINI_MODEL")
        self.model = os.getenv(
            model_env, DEFAULT_MODELS.get(self.provider, "gemini-2.5-flash")
        ).strip()
        self.enabled = bool(self.api_key)

        # In-memory query cache to avoid re-querying and consuming duplicate tokens
        self._cache: dict[str, str] = {}

    @staticmethod
    def _plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
        if not plan:
            return {}
        return {
            "legs": [
                {
                    "supplier": leg["supplier"],
                    "quantity": leg["quantity"],
                    "unit_price": leg["unit_price"],
                    "arrival_hours": leg["arrival_hours"],
                    "delivery_method": leg["delivery_method"],
                }
                for leg in plan.get("legs", [])
            ],
            "total_purchase_cost": plan.get("total_purchase_cost"),
            "material_arrival_hours": plan.get("material_arrival_hours"),
            "installation_minutes": plan.get("installation_minutes"),
            "recovery_time_hours": plan.get("recovery_time_hours"),
            "downtime_exposure": plan.get("downtime_exposure"),
            "total_exposure": plan.get("total_exposure"),
            "feasible": plan.get("feasible"),
            "infeasibility_reasons": plan.get("infeasibility_reasons", []),
        }

    def _fallback_summary(
        self, recommended: dict[str, Any], alternatives: list[dict[str, Any]]
    ) -> str:
        """Deterministic, template-based summary used when API quotas or tokens are exhausted."""
        if not recommended:
            return "No feasible recovery plan is available yet. Waiting on supplier offers."
        legs = ", ".join(
            f"{leg['quantity']} units from {leg['supplier']} (₹{leg['unit_price']}/unit)"
            for leg in recommended.get("legs", [])
        )
        lines = [
            f"Recommended plan: {legs}.",
            f"Total purchase cost is ₹{recommended.get('total_purchase_cost')}, "
            f"material arrival in {recommended.get('material_arrival_hours')}h, "
            f"and total recovery time {recommended.get('recovery_time_hours')}h.",
            f"Total economic exposure is ₹{recommended.get('total_exposure')} "
            f"(including ₹{recommended.get('downtime_exposure')} in downtime loss).",
        ]
        if alternatives:
            alt = alternatives[0]
            lines.append(
                f"Next-best alternative totals ₹{alt.get('total_exposure')} exposure "
                f"with {alt.get('recovery_time_hours')}h recovery time."
            )
        return " ".join(lines)

    def _deterministic_chat_answer(
        self, run_snapshot: dict[str, Any], message: str
    ) -> str:
        """Ground-truth analytical engine that answers operator questions directly
        from verified run data with zero token usage and 100% offline reliability."""
        msg_lower = message.strip().lower()
        req = run_snapshot.get("request", {}) or {}
        machine = req.get("machine", "Machinery")
        part = req.get("part_number", "part")
        qty = req.get("quantity", 0)
        max_h = req.get("max_hours", 3.0)
        loss_rate = req.get("downtime_cost_per_hour", 0)
        offers = run_snapshot.get("offers", []) or []
        plans = run_snapshot.get("plans", []) or []
        rec_plan = plans[0] if plans else None

        # 1. Supplier queries
        for char in ["a", "b", "c", "d"]:
            s_name = f"supplier {char}"
            if s_name in msg_lower:
                matching = next(
                    (o for o in offers if o.get("supplier", "").lower() == s_name), None
                )
                if not matching:
                    return f"{s_name.title()} was not contacted or has no recorded response."

                avail = matching.get("quantity_available", 0)
                price = matching.get("unit_price", 0)
                eta = matching.get("availability_hours", 0)
                status = matching.get("status", "RESPONDED")

                # Check if in recommended plan
                if rec_plan:
                    for leg in rec_plan.get("legs", []):
                        if leg.get("supplier", "").lower() == s_name:
                            leg_qty = leg.get("quantity", avail)
                            return (
                                f"{s_name.title()} is **selected** in the recommended plan: providing {leg_qty} units "
                                f"@ ₹{price}/unit with arrival in {eta}h ({matching.get('delivery_method', 'delivery')})."
                            )

                # Ruled out or contingency
                if eta > max_h:
                    return (
                        f"{s_name.title()} quoted {avail} units @ ₹{price}/unit, but arrival is {eta}h, "
                        f"which breaches the {max_h}h recovery deadline. It was ruled out to avoid extended downtime losses."
                    )
                elif rec_plan and rec_plan.get("total_exposure", 0) > 0:
                    return (
                        f"{s_name.title()} confirmed {avail} units @ ₹{price}/unit with {eta}h arrival. "
                        f"It is held as a viable contingency option, but the recommended plan yields lower total economic exposure."
                    )
                return f"{s_name.title()} offered {avail} units @ ₹{price}/unit with {eta}h ETA (Status: {status})."

        # 2. Cost / Financial exposure / Downtime loss
        if any(
            w in msg_lower
            for w in [
                "cost",
                "price",
                "loss",
                "exposure",
                "money",
                "save",
                "expense",
                "budget",
            ]
        ):
            if rec_plan:
                return (
                    f"For {machine}, the downtime loss rate is ₹{loss_rate:,.0f}/hr. "
                    f"The recommended plan requires ₹{rec_plan.get('total_purchase_cost', 0):,.0f} for components "
                    f"and incurs ₹{rec_plan.get('downtime_exposure', 0):,.0f} in downtime loss, "
                    f"bringing total economic exposure to ₹{rec_plan.get('total_exposure', 0):,.0f}."
                )
            return (
                f"The downtime loss rate is ₹{loss_rate:,.0f} per hour for {machine}."
            )

        # 3. Time / Recovery / Deadline / ETA
        if any(
            w in msg_lower
            for w in [
                "time",
                "hours",
                "delay",
                "deadline",
                "eta",
                "when",
                "arrival",
                "install",
            ]
        ):
            if rec_plan:
                return (
                    f"Production is projected to resume at T+{rec_plan.get('recovery_time_hours', 0)}h "
                    f"(target deadline is < {max_h}h). Material arrives in {rec_plan.get('material_arrival_hours', 0)}h "
                    f"followed by {rec_plan.get('installation_minutes', 0)}m installation."
                )
            return f"The maximum recovery deadline for this incident is {max_h} hours."

        # 4. Machine / Part details
        if any(
            w in msg_lower
            for w in [
                "machine",
                "part",
                "component",
                "spec",
                "bearing",
                "seal",
                "qty",
                "quantity",
            ]
        ):
            return (
                f"Incident target: **{machine}** has a critical failure requiring {qty} units of "
                f"part **{part}** ({req.get('part_description', 'critical component')})."
            )

        # 5. Recommendation / Decision summary
        if rec_plan and any(
            w in msg_lower
            for w in [
                "why",
                "recommend",
                "plan",
                "decision",
                "choice",
                "picked",
                "best",
            ]
        ):
            legs_desc = " + ".join(
                f"{l.get('supplier')} ({l.get('quantity')}u)"
                for l in rec_plan.get("legs", [])
            )
            return (
                f"RestartAI recommends {legs_desc} because it minimizes total factory shutdown time "
                f"(recovering at T+{rec_plan.get('recovery_time_hours')}h) with the lowest total economic exposure "
                f"(₹{rec_plan.get('total_exposure', 0):,.0f}) within the {max_h}h emergency deadline."
            )

        # 6. General status fallback
        if rec_plan:
            legs_desc = " + ".join(
                f"{l.get('supplier')} ({l.get('quantity')}u)"
                for l in rec_plan.get("legs", [])
            )
            return (
                f"{machine} recovery status: {len(offers)} supplier offers evaluated. "
                f"Recommended strategy: {legs_desc} restarting production in {rec_plan.get('recovery_time_hours')}h "
                f"at total exposure of ₹{rec_plan.get('total_exposure', 0):,.0f}."
            )

        return f"Recovery run for {machine} is active with {len(offers)} supplier quotes gathered."

    def _key_env_name(self) -> str:
        return {
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "grok": "GROK_API_KEY",
            "groq": "GROQ_API_KEY",
        }.get(self.provider, "GEMINI_API_KEY")

    async def recommend(self, run_snapshot: dict[str, Any]) -> dict[str, Any]:
        plans = run_snapshot.get("plans") or []
        recommended = plans[0] if plans else None
        alternatives = plans[1:4]

        if not self.enabled:
            return {
                "success": True,
                "source": "fallback",
                "text": self._fallback_summary(
                    self._plan_summary(recommended) if recommended else {},
                    [self._plan_summary(p) for p in alternatives],
                ),
            }

        payload_context = {
            "machine": run_snapshot.get("request", {}).get("machine"),
            "part_number": run_snapshot.get("request", {}).get("part_number"),
            "quantity_needed": run_snapshot.get("request", {}).get("quantity"),
            "max_hours_allowed": run_snapshot.get("request", {}).get("max_hours"),
            "downtime_cost_per_hour": run_snapshot.get("request", {}).get(
                "downtime_cost_per_hour"
            ),
            "recommended_plan": (
                self._plan_summary(recommended) if recommended else None
            ),
            "alternative_plans": [self._plan_summary(p) for p in alternatives],
        }

        user_message = (
            "Explain and justify this already-selected recovery plan for the factory manager. "
            "Do not change the recommendation or the numbers.\n\n"
            f"{payload_context}"
        )

        providers_to_try = [self.provider]
        if self.provider == "gemini" and os.getenv("GROQ_API_KEY"):
            providers_to_try.append("groq")
        elif self.provider == "groq" and os.getenv("GEMINI_API_KEY"):
            providers_to_try.append("gemini")

        for prov in providers_to_try:
            try:
                if prov == "anthropic":
                    text = await self._call_anthropic(user_message)
                elif prov == "gemini":
                    text = await self._call_gemini(user_message)
                elif prov == "groq":
                    text = await self._call_groq(user_message)
                else:
                    text = await self._call_grok(user_message)

                if text:
                    return {"success": True, "source": prov, "text": text}
            except Exception as exc:
                logger.warning(
                    "Provider %s failed (%s) in recommend, trying fallback", prov, exc
                )

        fallback = self._fallback_summary(
            self._plan_summary(recommended) if recommended else {},
            [self._plan_summary(p) for p in alternatives],
        )
        return {"success": True, "source": "fallback", "text": fallback}

    def _run_context(self, run_snapshot: dict[str, Any]) -> dict[str, Any]:
        plans = run_snapshot.get("plans") or []
        request = run_snapshot.get("request", {})
        return {
            "stage": run_snapshot.get("stage"),
            "machine": request.get("machine"),
            "part_number": request.get("part_number"),
            "part_description": request.get("part_description"),
            "quantity_needed": request.get("quantity"),
            "max_hours_allowed": request.get("max_hours"),
            "downtime_cost_per_hour": request.get("downtime_cost_per_hour"),
            "supplier_offers": [
                {
                    "supplier": o.get("supplier"),
                    "status": o.get("status"),
                    "quantity_available": o.get("quantity_available"),
                    "unit_price": o.get("unit_price"),
                    "availability_hours": o.get("availability_hours"),
                    "compatible": o.get("compatible"),
                    "confirmed": o.get("confirmed"),
                }
                for o in run_snapshot.get("offers", [])
            ],
            "recommended_plan": self._plan_summary(plans[0]) if plans else None,
            "alternative_plans": [self._plan_summary(p) for p in plans[1:4]],
        }

    async def chat(
        self,
        run_snapshot: dict[str, Any],
        message: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        # 1. Query Cache Check (0 tokens consumed on repeated questions)
        cache_key = f"{run_snapshot.get('run_id') or run_snapshot.get('request', {}).get('machine', '')}:{message.strip().lower()}"
        if cache_key in self._cache:
            return {"success": True, "source": "cache", "text": self._cache[cache_key]}

        # If LLM APIs are not enabled, immediately use the deterministic engine
        if not self.enabled:
            ans = self._deterministic_chat_answer(run_snapshot, message)
            self._cache[cache_key] = ans
            return {"success": True, "source": "ground_truth_engine", "text": ans}

        context = self._run_context(run_snapshot)
        history = history or []
        # Keep only the last 4 messages to save tokens and prevent context window exhaustion
        convo = "\n".join(f"{h['role']}: {h['content']}" for h in history[-4:])
        user_message = (
            "Here is the current recovery run's data:\n"
            f"{context}\n\n"
            + (f"Conversation so far:\n{convo}\n\n" if convo else "")
            + f"Operator question: {message}"
        )

        providers_to_try = [self.provider]
        if self.provider == "gemini" and os.getenv("GROQ_API_KEY"):
            providers_to_try.append("groq")
        elif self.provider == "groq" and os.getenv("GEMINI_API_KEY"):
            providers_to_try.append("gemini")

        for prov in providers_to_try:
            try:
                if prov == "anthropic":
                    text = await self._call_anthropic(
                        user_message, system=CHAT_SYSTEM_PROMPT
                    )
                elif prov == "gemini":
                    text = await self._call_gemini(
                        user_message, system=CHAT_SYSTEM_PROMPT
                    )
                elif prov == "groq":
                    text = await self._call_groq(
                        user_message, system=CHAT_SYSTEM_PROMPT
                    )
                else:
                    text = await self._call_grok(
                        user_message, system=CHAT_SYSTEM_PROMPT
                    )

                if text:
                    self._cache[cache_key] = text
                    return {"success": True, "source": prov, "text": text}
            except Exception as exc:
                logger.warning(
                    "Provider %s failed (%s) in chat, trying fallback", prov, exc
                )

        # Seamless Ground-Truth Analytical Engine Fallback (prevents token exhaustion failures)
        ans = self._deterministic_chat_answer(run_snapshot, message)
        self._cache[cache_key] = ans
        return {"success": True, "source": "ground_truth_engine", "text": ans}

    async def _call_anthropic(
        self, user_message: str, system: str = SYSTEM_PROMPT
    ) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": 250,
            "system": system,
            "messages": [{"role": "user", "content": user_message}],
        }
        data = await self._post(ANTHROPIC_MESSAGES_URL, headers, body)
        parts = [
            b.get("text", "")
            for b in data.get("content", [])
            if b.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p).strip()

    async def _call_gemini(self, user_message: str, system: str = SYSTEM_PROMPT) -> str:
        url = GEMINI_URL_TEMPLATE.format(model=self.model)
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
            "generationConfig": {"maxOutputTokens": 250},
        }
        data = await self._post(url, headers, body)
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()

    async def _call_grok(self, user_message: str, system: str = SYSTEM_PROMPT) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": 250,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        }
        data = await self._post(GROK_CHAT_URL, headers, body)
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message", {}).get("content") or "").strip()

    async def _call_groq(self, user_message: str, system: str = SYSTEM_PROMPT) -> str:
        headers = {
            "Authorization": f"Bearer {os.getenv('GROQ_API_KEY', self.api_key)}",
            "Content-Type": "application/json",
        }
        groq_model = os.getenv(
            "GROQ_MODEL", DEFAULT_MODELS.get("groq", "openai/gpt-oss-120b")
        )
        body = {
            "model": groq_model,
            "max_tokens": 250,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        }
        data = await self._post(GROQ_CHAT_URL, headers, body)
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message", {}).get("content") or "").strip()

    async def _post(
        self, url: str, headers: dict[str, str], body: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise LlmError(
                f"AI recommendation request to {self.provider} timed out."
            ) from exc
        except httpx.HTTPError as exc:
            raise LlmError(
                f"AI recommendation request to {self.provider} failed: {exc}"
            ) from exc

        if response.is_error:
            logger.warning(
                "%s API error status=%s body=%s",
                self.provider,
                response.status_code,
                response.text[:300],
            )
            raise LlmError(
                f"AI recommendation failed ({self.provider}, {response.status_code})."
            )
        return response.json()
