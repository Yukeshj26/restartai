import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import RecoveryRequest, Supplier

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
logger = logging.getLogger(__name__)


class CallEError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        call_id: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.call_id = call_id
        self.diagnostics = diagnostics or {}


class CallETimeoutError(CallEError):
    pass


class CalleService:
    def __init__(self):
        self.mode = os.getenv("CALL_E_MODE", "demo").lower()
        self.api_key = os.getenv("CALLE_API_KEY", "").strip()
        self.base_url = os.getenv("CALLE_BASE_URL", "https://api.heycall-e.com").rstrip(
            "/"
        )
        self.calls: dict[str, dict[str, Any]] = {}
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=60.0,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def validate_phone(phone: str) -> str:
        normalized = phone.strip()
        if not E164_RE.fullmatch(normalized):
            raise ValueError(
                "Phone must be a valid E.164 number, for example +919876543210."
            )
        return normalized

    @staticmethod
    def mask_phone(phone: str) -> str:
        return f"{phone[:3]}******{phone[-4:]}" if len(phone) > 7 else "***"

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        if not self.api_key:
            raise CallEError(
                "CALL-E API key is missing. Add CALLE_API_KEY to .env.",
                code="missing_api_key",
            )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    def _result_schema() -> dict[str, Any]:
        fields = {
            "supplier_name": {
                "type": "string",
                "description": "Supplier name or business name given during the call.",
            },
            "available_quantity": {
                "type": "integer",
                "description": "Units physically available. Use 0 if unknown.",
            },
            "unit_price": {
                "type": "number",
                "description": "Exact unit price. Use 0 if unknown.",
            },
            "currency": {"type": "string", "description": "Currency such as INR."},
            "delivery_hours": {
                "type": "number",
                "description": "Hours until delivery. Use 999 if unknown.",
            },
            "delivery_method": {
                "type": "string",
                "description": "Delivery, pickup, courier, or unknown.",
            },
            "compatible": {
                "type": "string",
                "enum": ["yes", "no", "unknown"],
                "description": "Exact requested part/spec compatibility. Never assume an equivalent is compatible.",
            },
            "compatibility_confidence": {
                "type": "number",
                "description": "0 to 1 confidence of exact compatibility. Use 0 if unknown.",
            },
            "can_fulfill": {
                "type": "string",
                "enum": ["yes", "partial", "no", "unknown"],
            },
        }
        return {
            "type": "object",
            "required": list(fields),
            "properties": fields,
            "additionalProperties": False,
        }

    @staticmethod
    def _infer_region_and_locale(
        phone: str, default_region: str = "IN", default_locale: str = "en-IN"
    ) -> tuple[str, str]:
        normalized = phone.strip()
        if normalized.startswith("+91"):
            return "IN", "en-IN"
        if normalized.startswith("+1"):
            return "US", "en-US"
        if normalized.startswith("+44"):
            return "GB", "en-GB"
        if normalized.startswith("+49"):
            return "DE", "de-DE"
        return default_region or "IN", default_locale or "en-IN"

    def _build_payload(
        self,
        supplier: Supplier,
        request: RecoveryRequest,
        known_offers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        inferred_region, inferred_locale = self._infer_region_and_locale(
            supplier.phone, supplier.region, supplier.locale
        )
        return {
            "task": self._build_task(supplier, request, known_offers),
            "recipients": [
                {
                    "phones": [supplier.phone],
                    "region": supplier.region or inferred_region,
                    "locale": supplier.locale or inferred_locale,
                }
            ],
            "result_schema": {
                "type": "object",
                "required": ["supplier_call_completed"],
                "properties": {"supplier_call_completed": {"type": "boolean"}},
                "additionalProperties": False,
            },
            "recipient_result_schema": self._result_schema(),
            "metadata": {
                "app": "restartai",
                "workflow_run_id": request.idempotency_key or "",
                "supplier_name": supplier.name,
                "part_number": request.part_number,
            },
        }

    @staticmethod
    def _error_from_response(response: httpx.Response, action: str) -> CallEError:
        try:
            body = response.json()
        except ValueError:
            body = {}
        detail = (
            body.get("message")
            or body.get("error")
            or body.get("detail")
            or response.text[:300]
        )
        messages = {
            401: "CALL-E authentication failed. Check CALLE_API_KEY.",
            403: "CALL-E authorization was denied.",
            422: "CALL-E rejected the call request. Check recipient phone format and request schema.",
            429: "CALL-E rate limit reached. Try again later.",
        }
        return CallEError(
            messages.get(
                response.status_code,
                f"CALL-E {action} failed ({response.status_code}): {detail}",
            ),
            code=str(response.status_code),
            status_code=response.status_code,
        )

    async def create_call(
        self,
        supplier: Supplier,
        request: RecoveryRequest,
        known_offers=None,
        *,
        idempotency_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        phone = self.validate_phone(supplier.phone)
        key = (
            idempotency_key
            or f"restartai-{request.idempotency_key or request.part_number}-{supplier.name}"
        )
        logger.info(
            "CALL-E create request supplier=%s phone=%s",
            supplier.name,
            self.mask_phone(phone),
        )
        try:
            if client is not None:
                response = await client.post(
                    f"{self.base_url}/v1/calls",
                    headers=self._headers(key),
                    json=self._build_payload(supplier, request, known_offers or []),
                )
            else:
                async with httpx.AsyncClient(timeout=60.0) as http_client:
                    response = await http_client.post(
                        f"{self.base_url}/v1/calls",
                        headers=self._headers(key),
                        json=self._build_payload(supplier, request, known_offers or []),
                    )
        except httpx.TimeoutException as exc:
            raise CallEError(
                "CALL-E request timed out.", code="network_timeout"
            ) from exc
        except httpx.HTTPError as exc:
            raise CallEError(
                f"CALL-E connection failed: {exc}", code="connection_error"
            ) from exc
        if response.is_error:
            raise self._error_from_response(response, "create")
        try:
            data = response.json()
        except ValueError as exc:
            raise CallEError(
                "CALL-E returned a non-JSON create response.",
                code="invalid_response",
                status_code=response.status_code,
            ) from exc
        call_id = data.get("id") or data.get("call_id")
        if not call_id:
            raise CallEError("CALL-E returned no call ID.", code="invalid_response")
        self.calls[call_id] = {
            "supplier": supplier.name,
            "phone": phone,
            "phone_masked": self.mask_phone(phone),
            "call_id": call_id,
            "status": data.get("status", "queued"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "failure_code": None,
            "failure_message": None,
            "result": None,
            "summary": None,
            "confidence": None,
        }
        logger.info(
            "CALL-E response call_id=%s status=%s",
            call_id,
            data.get("status", "queued"),
        )
        return data

    async def get_call(
        self, call_id: str, *, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        try:
            if client is not None:
                response = await client.get(
                    f"{self.base_url}/v1/calls/{call_id}", headers=self._headers()
                )
            else:
                async with httpx.AsyncClient(timeout=60.0) as http_client:
                    response = await http_client.get(
                        f"{self.base_url}/v1/calls/{call_id}", headers=self._headers()
                    )
        except httpx.TimeoutException as exc:
            raise CallEError(
                "CALL-E status request timed out.", code="network_timeout"
            ) from exc
        except httpx.HTTPError as exc:
            raise CallEError(
                f"CALL-E connection failed: {exc}", code="connection_error"
            ) from exc
        if response.is_error:
            raise self._error_from_response(response, "status")
        try:
            return response.json()
        except ValueError as exc:
            raise CallEError(
                "CALL-E returned a non-JSON status response.",
                code="invalid_response",
                status_code=response.status_code,
            ) from exc

    @staticmethod
    def _status(data: dict[str, Any]) -> str:
        recipients = data.get("recipients") or [{}]
        return str(
            data.get("status")
            or data.get("state")
            or recipients[0].get("status")
            or "unknown"
        ).lower()

    @staticmethod
    def _first_nested(data: Any, keys: tuple[str, ...]) -> Any:
        if isinstance(data, dict):
            for key in keys:
                if data.get(key) is not None:
                    return data[key]
            for value in data.values():
                found = CalleService._first_nested(value, keys)
                if found is not None:
                    return found
        elif isinstance(data, list):
            for value in data:
                found = CalleService._first_nested(value, keys)
                if found is not None:
                    return found
        return None

    @classmethod
    def _diagnostics(cls, call_id: str, data: dict[str, Any]) -> dict[str, Any]:
        recipients = (
            data.get("recipients") if isinstance(data.get("recipients"), list) else []
        )
        recipient = (
            recipients[0] if recipients and isinstance(recipients[0], dict) else {}
        )
        attempts = (
            recipient.get("attempts")
            if isinstance(recipient.get("attempts"), list)
            else data.get("attempts")
        )
        attempt = (
            attempts[0]
            if isinstance(attempts, list) and attempts and isinstance(attempts[0], dict)
            else {}
        )
        diagnostics = {
            "call_id": call_id,
            "status": cls._status(data),
            "failure_code": data.get("failure_code") or data.get("error_code"),
            "failure_message": data.get("failure_message")
            or data.get("error")
            or data.get("failure"),
            "recipient_status": recipient.get("status")
            or cls._first_nested(data, ("recipient_status",)),
            "attempt_status": attempt.get("status")
            or cls._first_nested(data, ("attempt_status",)),
            "attempt_failure_code": attempt.get("failure_code")
            or attempt.get("error_code"),
            "attempt_failure_message": attempt.get("failure_message")
            or attempt.get("error")
            or attempt.get("failure"),
            "structured_result": cls._extract_result(data),
            "transcript_available": bool(cls._first_nested(data, ("transcript",))),
        }
        cleaned = {
            key: value
            for key, value in diagnostics.items()
            if value not in (None, "", {})
        }
        attempt_code = str(cleaned.get("attempt_failure_code", "")).lower()
        attempt_message = str(cleaned.get("attempt_failure_message", "")).lower()
        failure_message = str(cleaned.get("failure_message", "")).lower()
        no_answer_evidence = (
            attempt_code == "480"
            or "no answer" in attempt_message
            or "no answer" in failure_message
            or "unavailable" in attempt_message
            or "unavailable" in failure_message
        )
        if no_answer_evidence and cleaned.get("status") == "failed":
            cleaned["category"] = "supplier_unavailable"
            cleaned["human_message"] = "Supplier did not answer or was unavailable."
        return cleaned

    @classmethod
    def _safe_response(cls, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {
                name: cls._safe_response(item, name)
                for name, item in value.items()
                if name.lower()
                not in {"api_key", "authorization", "access_token", "secret"}
            }
        if isinstance(value, list):
            return [cls._safe_response(item, key) for item in value]
        if key.lower() in {"phone", "phones", "phone_number", "phone_numbers"}:
            if isinstance(value, str):
                return cls.mask_phone(value)
            if isinstance(value, list):
                return [cls.mask_phone(str(item)) for item in value]
        if key.lower() == "transcript":
            return "[redacted; transcript available]"
        return value

    def _log_result(self, call_id: str, data: dict[str, Any]) -> None:
        diagnostics = self._diagnostics(call_id, data)
        logger.info(
            "LIVE CALL-E RESULT call_id=%s status=%s diagnostics=%s",
            call_id,
            diagnostics.get("status"),
            diagnostics,
        )

    def _update_record(self, call_id: str, data: dict[str, Any]) -> dict[str, Any]:
        record = self.calls.setdefault(call_id, {"call_id": call_id})
        status = self._status(data)
        record.update(
            {
                "status": status,
                "failure_code": data.get("failure_code") or data.get("error_code"),
                "failure_message": data.get("failure_message")
                or data.get("error")
                or data.get("failure"),
            }
        )
        if status in {"completed", "failed", "canceled"}:
            record["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("CALL-E status call_id=%s status=%s", call_id, status)
        record["provider_response"] = data
        record["diagnostics"] = self._diagnostics(call_id, data)
        record["category"] = record["diagnostics"].get("category")
        record["human_message"] = record["diagnostics"].get("human_message")
        if status in {"failed", "canceled"}:
            self._log_result(call_id, data)
        return record

    async def wait_for_call(
        self,
        call_id: str,
        *,
        max_wait_seconds: int = 300,
        poll_interval: float = 2.0,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        elapsed = 0.0
        attempt = 0
        while elapsed < max_wait_seconds:
            data = await self.get_call(call_id, client=client)
            record = self._update_record(call_id, data)
            if record["status"] in {"completed", "failed", "canceled"}:
                return data
            # Use responsive 1.0s interval for first 5 checks, then standard poll_interval
            sleep_duration = 1.0 if attempt < 5 else poll_interval
            elapsed += sleep_duration
            attempt += 1
            if elapsed < max_wait_seconds:
                await asyncio.sleep(sleep_duration)
        raise CallETimeoutError(
            "CALL-E call did not reach a terminal state within 5 minutes.",
            code="timeout",
        )

    @staticmethod
    def _extract_result(data: dict[str, Any]) -> dict[str, Any]:
        recipients = data.get("recipients") or []
        recipient = recipients[0] if recipients else {}
        # Recipient-level structured_result holds the detailed recipient_result_schema
        # data (quantity, price, delivery, etc.). The top-level structured_result only
        # reflects the batch-level result_schema (e.g. supplier_call_completed), so it
        # must be checked last, not first.
        return (
            recipient.get("structured_result")
            or recipient.get("result")
            or data.get("structured_result")
            or data.get("result")
            or {}
        )

    async def call_supplier_async(
        self,
        supplier: Supplier,
        request: RecoveryRequest,
        known_offers=None,
        *,
        idempotency_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        if client is not None:
            created = await self.create_call(
                supplier, request, known_offers, idempotency_key=idempotency_key, client=client
            )
            call_id = created.get("id") or created.get("call_id")
            completed = await self.wait_for_call(call_id, client=client)
        else:
            async with httpx.AsyncClient(
                timeout=60.0,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            ) as session_client:
                created = await self.create_call(
                    supplier,
                    request,
                    known_offers,
                    idempotency_key=idempotency_key,
                    client=session_client,
                )
                call_id = created.get("id") or created.get("call_id")
                completed = await self.wait_for_call(call_id, client=session_client)
        status = self._status(completed)
        record = self._update_record(call_id, completed)
        if status != "completed":
            diagnostics = record.get("diagnostics", {})
            raise CallEError(
                record.get("failure_message") or f"CALL-E call {status}.",
                code=record.get("failure_code") or status,
                call_id=call_id,
                diagnostics=diagnostics,
            )
        result = self._extract_result(completed)
        if not result:
            raise CallEError(
                "CALL-E completed without a usable structured supplier result.",
                code="missing_result",
                call_id=call_id,
            )

        def num(value, default=0.0):
            try:
                return float(value)
            except (TypeError, ValueError):
                return float(default)

        quantity = max(0, int(num(result.get("available_quantity"), 0)))
        unit_price = max(0.0, num(result.get("unit_price"), 0))
        delivery_hours = max(0.0, num(result.get("delivery_hours"), 999))
        compatible_value = str(result.get("compatible") or "unknown").lower()
        fulfill_value = str(result.get("can_fulfill") or "unknown").lower()
        compatible = compatible_value == "yes"
        confirmed = compatible and fulfill_value in {"yes", "partial"}
        confidence = min(
            1.0,
            max(
                0.0,
                num(result.get("compatibility_confidence"), 0 if not compatible else 1),
            ),
        )
        normalized = {
            "supplier": result.get("supplier_name") or supplier.name,
            "phone": supplier.phone,
            "quantity_available": quantity,
            "unit_price": unit_price,
            "currency": result.get("currency") or "INR",
            "availability_hours": delivery_hours,
            "delivery_method": result.get("delivery_method") or "unknown",
            "compatible": compatible,
            "confirmed": confirmed,
            "compatibility_confidence": confidence,
            "status": (
                "FULL STOCK"
                if fulfill_value == "yes" and confirmed
                else (
                    "PARTIAL STOCK"
                    if fulfill_value == "partial" and confirmed
                    else "NO STOCK"
                )
            ),
            "source": "CALL-E LIVE CALL",
            "call_id": call_id,
            "notes": (
                f"Supplier: {result.get('supplier_name') or supplier.name}. "
                f"Availability: {quantity} units. "
                f"Compatibility: {compatible_value}. "
                f"Fulfillment: {fulfill_value}. "
                f"Price: {unit_price:g} {result.get('currency') or 'INR'} per unit. "
                f"Delivery: {delivery_hours:g} hours via {result.get('delivery_method') or 'unknown'}."
            ),
        }

        record.update(
            {"result": result, "summary": normalized["notes"], "confidence": confidence}
        )
        return normalized

    async def start_test_call(self, phone: str, supplier_name: str) -> dict[str, Any]:
        phone = self.validate_phone(phone)
        supplier = Supplier(name=supplier_name, phone=phone)
        request = RecoveryRequest(
            machine="test",
            part_number="test",
            part_description="test",
            quantity=1,
            max_hours=1,
            downtime_cost_per_hour=0,
            suppliers=[supplier],
            live_confirmed=True,
        )
        created = await self.create_call(
            supplier,
            request,
            idempotency_key=f"restartai-test-{phone}-{uuid.uuid4()}",
            client=self._get_client(),
        )
        call_id = created.get("id") or created.get("call_id")
        record = self.calls[call_id]
        return {
            "call_id": call_id,
            "status": record["status"],
            "supplier": supplier_name,
            "phone_masked": record["phone_masked"],
        }

    async def test_call_status(self, call_id: str) -> dict[str, Any]:
        data = await self.get_call(call_id, client=self._get_client())
        record = self._update_record(call_id, data)
        return {
            "success": True,
            "call_id": call_id,
            "status": record["status"],
            "failure_code": record.get("failure_code"),
            "failure_message": record.get("failure_message"),
            "category": record.get("category"),
            "human_message": record.get("human_message"),
            "diagnostics": record.get("diagnostics", {}),
            "structured_result": record.get("diagnostics", {}).get("structured_result"),
            "transcript_available": record.get("diagnostics", {}).get(
                "transcript_available", False
            ),
            "provider_response": self._safe_response(data),
        }

    async def get_call_status(self, call_id: str) -> dict[str, Any]:
        return await self.test_call_status(call_id)

    def call_supplier(
        self, supplier: Supplier, request: RecoveryRequest, known_offers=None
    ) -> dict[str, Any]:
        if getattr(request, "mode", None) == "demo" or (
            getattr(request, "mode", None) is None and self.mode == "demo"
        ):
            return self._demo_call(supplier, request, known_offers or [])
        raise CallEError(
            "Live calls must use the asynchronous CALL-E REST flow.",
            code="async_required",
        )

    def _build_task(self, supplier, request, known_offers):
        prior = ""
        if known_offers:
            prior = " Confirmed context: " + ", ".join(
                f"{x['supplier']} ({x.get('quantity_available', 0)} units, {x.get('unit_price', 0)} {x.get('currency', 'INR')}, {x.get('availability_hours', 999)}h)"
                for x in known_offers
            ) + "."
        remaining = max(
            0,
            request.quantity
            - sum(
                x.get("quantity_available", 0)
                for x in known_offers
                if x.get("compatible") and x.get("confirmed")
            ),
        )
        return (
            f"Emergency procurement call to {supplier.name} for machine {request.machine}. "
            f"Part required: {request.part_number} ({request.part_description or 'bearing/component'}). "
            f"Target quantity: {request.quantity} units (remaining needed: {remaining}), max allowable delivery: {request.max_hours} hours. "
            f"Ask the supplier: "
            f"1. Is exact part {request.part_number} in stock now? "
            f"2. How many physical units are available immediately? "
            f"3. What is the unit price and currency? "
            f"4. What is the delivery ETA in hours and dispatch method? "
            f"5. Can you fulfill full quantity ({request.quantity}) or partial? "
            f"Only record factual answers. Unknown quantity=0, unknown price=0, unknown delivery=999. "
            f"Return a concise factual summary.{prior}"
        ).strip()

    def _demo_call(
        self,
        supplier: Supplier,
        request: RecoveryRequest,
        known_offers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        scenario = getattr(request, "chaos_scenario", "standard") or "standard"
        name = supplier.name.strip()
        call_id = f"demo-{name.lower().replace(' ', '-')}"

        req_qty = getattr(request, "quantity", 20) or 20
        part_name = getattr(request, "part_number", "SKF 6205-2RS") or "SKF 6205-2RS"
        machine_name = (
            getattr(request, "machine", "CNC Production Line 4")
            or "CNC Production Line 4"
        )

        is_golden = (
            req_qty == 20 and part_name == "SKF 6205-2RS" and "CNC" in machine_name
        )
        qty_full = 20 if is_golden else req_qty
        qty_c = 8 if is_golden else max(1, int(round(req_qty * 0.4)))
        qty_d = 12 if is_golden else max(1, req_qty - qty_c)

        # Standard Golden Scenario Baseline
        standard_offers = {
            "Supplier A": {
                "quantity_available": qty_full,
                "unit_price": 150.0,
                "availability_hours": 24.0,
                "delivery_method": "delivery",
                "compatible": True,
                "compatibility_confidence": 0.98,
                "confirmed": True,
                "status": "CONFIRMED",
                "notes": (
                    f"Full stock of {qty_full} units; 24-hour next-day truck delivery."
                    if not is_golden
                    else "Full stock of 20 units; 24-hour next-day truck delivery."
                ),
                "transcript": (
                    (
                        f'[00:02] Agent: "Hello, RestartAI emergency recovery for {machine_name}. We require {qty_full} units of {part_name}. Do you have physical stock?"\n'
                        f'[00:07] Supplier A: "Yes, we have {qty_full} units in our regional warehouse. Rubber contact seal, exact match."\n'
                        '[00:12] Agent: "What is your unit price and earliest arrival time?"\n'
                        '[00:16] Supplier A: "Price is 150 rupees per unit. Next dispatch truck departs tomorrow at 8 AM, reaching you in 24 hours."\n'
                        f'[00:22] Agent: "Confirmed: {qty_full} units at Rs 150, arriving in 24 hours."'
                    )
                    if not is_golden
                    else (
                        '[00:02] Agent: "Hello, RestartAI emergency recovery for CNC Production Line 4. We require 20 units of SKF 6205-2RS. Do you have physical stock?"\n'
                        '[00:07] Supplier A: "Yes, we have 20 units in our regional warehouse. Rubber contact seal, exact match."\n'
                        '[00:12] Agent: "What is your unit price and earliest arrival time?"\n'
                        '[00:16] Supplier A: "Price is 150 rupees per unit. Next dispatch truck departs tomorrow at 8 AM, reaching you in 24 hours."\n'
                        '[00:22] Agent: "Confirmed: 20 units at Rs 150, arriving in 24 hours."'
                    )
                ),
                "extracted_fields": {
                    "quantity": {
                        "value": qty_full,
                        "source_quote": f"Yes, we have {qty_full} units in our regional warehouse.",
                        "confidence": 0.98,
                    },
                    "unit_price": {
                        "value": 150.0,
                        "source_quote": "Price is 150 rupees per unit.",
                        "confidence": 0.99,
                    },
                    "availability_hours": {
                        "value": 24.0,
                        "source_quote": "reaching you in 24 hours.",
                        "confidence": 0.97,
                    },
                    "delivery_method": {
                        "value": "delivery",
                        "source_quote": "Next dispatch truck departs tomorrow",
                        "confidence": 0.96,
                    },
                    "compatible": {
                        "value": True,
                        "source_quote": "Rubber contact seal, exact match.",
                        "confidence": 0.98,
                    },
                },
                "retry_count": 0,
            },
            "Supplier B": {
                "quantity_available": qty_full,
                "unit_price": 220.0,
                "availability_hours": 2.0,
                "delivery_method": "delivery",
                "compatible": True,
                "compatibility_confidence": 0.98,
                "confirmed": True,
                "status": "CONFIRMED",
                "notes": (
                    f"Full stock of {qty_full} units; 2-hour express courier delivery."
                    if not is_golden
                    else "Full stock of 20 units; 2-hour express courier delivery."
                ),
                "transcript": (
                    (
                        f'[00:02] Agent: "Emergency procurement for {machine_name}: we need {qty_full} units of {part_name} immediately. Can you deliver today?"\n'
                        f'[00:08] Supplier B: "Yes, we have {qty_full} units in stock at our local city depot. We can dispatch a hotshot courier immediately."\n'
                        '[00:14] Agent: "What is the unit cost and delivery timeline?"\n'
                        '[00:19] Supplier B: "220 rupees per unit including emergency courier fee. Arrival guaranteed within 2 hours of confirmation."\n'
                        f'[00:26] Agent: "Confirmed: {qty_full} units at Rs 220, 2-hour arrival."'
                    )
                    if not is_golden
                    else (
                        '[00:02] Agent: "Emergency procurement for CNC Line 4: we need 20 units of SKF 6205-2RS immediately. Can you deliver today?"\n'
                        '[00:08] Supplier B: "Yes, we have 20 units in stock at our local city depot. We can dispatch a hotshot courier immediately."\n'
                        '[00:14] Agent: "What is the unit cost and delivery timeline?"\n'
                        '[00:19] Supplier B: "220 rupees per unit including emergency courier fee. Arrival guaranteed within 2 hours of confirmation."\n'
                        '[00:26] Agent: "Confirmed: 20 units at Rs 220, 2-hour arrival."'
                    )
                ),
                "extracted_fields": {
                    "quantity": {
                        "value": qty_full,
                        "source_quote": f"we have {qty_full} units in stock at our local city depot",
                        "confidence": 0.99,
                    },
                    "unit_price": {
                        "value": 220.0,
                        "source_quote": "220 rupees per unit including emergency courier fee",
                        "confidence": 0.98,
                    },
                    "availability_hours": {
                        "value": 2.0,
                        "source_quote": "Arrival guaranteed within 2 hours",
                        "confidence": 0.98,
                    },
                    "delivery_method": {
                        "value": "delivery",
                        "source_quote": "dispatch a hotshot courier immediately",
                        "confidence": 0.98,
                    },
                    "compatible": {
                        "value": True,
                        "source_quote": f"{part_name} immediately",
                        "confidence": 0.98,
                    },
                },
                "retry_count": 0,
            },
            "Supplier C": {
                "quantity_available": qty_c,
                "unit_price": 180.0,
                "availability_hours": 0.5,
                "delivery_method": "pickup",
                "compatible": True,
                "compatibility_confidence": 0.95,
                "confirmed": True,
                "status": "CONFIRMED",
                "notes": (
                    f"Only {qty_c} available for immediate pickup in 30 minutes."
                    if not is_golden
                    else "Only 8 available for immediate pickup in 30 minutes."
                ),
                "transcript": (
                    (
                        f'[00:02] Agent: "Calling Supplier C: breakdown on {machine_name} needing {req_qty} units {part_name}. What is your available stock?"\n'
                        f'[00:08] Supplier C: "Let me check the front shelf... I only have {qty_c} units on hand right now. The rest was sold this morning."\n'
                        f'[00:15] Agent: "We can take partial stock. Are they exact {part_name}?"\n'
                        f'[00:20] Supplier C: "Yes, genuine {part_name} specification. Price is 180 rupees each."\n'
                        '[00:26] Agent: "How fast can we collect them?"\n'
                        '[00:30] Supplier C: "Ready at our trade counter immediately. You can pick them up in 30 minutes."\n'
                        f'[00:36] Agent: "Confirmed: {qty_c} units at Rs 180, 0.5h pickup."'
                    )
                    if not is_golden
                    else (
                        '[00:02] Agent: "Calling Supplier C: breakdown on CNC Line 4 needing 20 units SKF 6205-2RS. What is your available stock?"\n'
                        '[00:08] Supplier C: "Let me check the front shelf... I only have 8 units on hand right now. The rest was sold this morning."\n'
                        '[00:15] Agent: "We can take partial stock. Are they exact SKF 6205-2RS rubber seal?"\n'
                        '[00:20] Supplier C: "Yes, genuine SKF 6205-2RS rubber contact seal. Price is 180 rupees each."\n'
                        '[00:26] Agent: "How fast can we collect them?"\n'
                        '[00:30] Supplier C: "Ready at our trade counter immediately. You can pick them up in 30 minutes."\n'
                        '[00:36] Agent: "Confirmed: 8 units at Rs 180, 0.5h pickup."'
                    )
                ),
                "extracted_fields": {
                    "quantity": {
                        "value": qty_c,
                        "source_quote": f"I only have {qty_c} units on hand right now.",
                        "confidence": 0.99,
                    },
                    "unit_price": {
                        "value": 180.0,
                        "source_quote": "Price is 180 rupees each.",
                        "confidence": 0.98,
                    },
                    "availability_hours": {
                        "value": 0.5,
                        "source_quote": "pick them up in 30 minutes.",
                        "confidence": 0.97,
                    },
                    "delivery_method": {
                        "value": "pickup",
                        "source_quote": "Ready at our trade counter immediately",
                        "confidence": 0.96,
                    },
                    "compatible": {
                        "value": True,
                        "source_quote": f"Yes, genuine {part_name}",
                        "confidence": 0.99,
                    },
                },
                "retry_count": 0,
            },
            "Supplier D": {
                "quantity_available": qty_d,
                "unit_price": 190.0,
                "availability_hours": 1.5,
                "delivery_method": "delivery",
                "compatible": True,
                "compatibility_confidence": 0.96,
                "confirmed": True,
                "status": "CONFIRMED",
                "notes": (
                    f"{qty_d} available; 90-minute express delivery."
                    if not is_golden
                    else "12 available; 90-minute express delivery."
                ),
                "transcript": (
                    (
                        f'[00:02] Agent: "Calling Supplier D: {machine_name} stopped. Supplier C gave us {qty_c} units; we have a remaining shortfall of {qty_d} units. Can you supply {qty_d} units of {part_name}?"\n'
                        f'[00:09] Supplier D: "Yes, we have {qty_d} units on shelf. Perfect timing, that is exactly what we have left in this batch."\n'
                        '[00:16] Agent: "What is your unit price and transit time?"\n'
                        '[00:20] Supplier D: "190 rupees per unit. Express bike delivery right now will reach your plant in 90 minutes (1.5h)."\n'
                        f'[00:27] Agent: "Confirmed: {qty_d} units at Rs 190, 1.5-hour delivery."'
                    )
                    if not is_golden
                    else (
                        '[00:02] Agent: "Calling Supplier D: CNC Line 4 stopped. Supplier C gave us 8 units; we have a remaining shortfall of 12 units. Can you supply 12 units of SKF 6205-2RS?"\n'
                        '[00:09] Supplier D: "Yes, we have 12 units on shelf. Perfect timing, that is exactly what we have left in this batch."\n'
                        '[00:16] Agent: "What is your unit price and transit time?"\n'
                        '[00:20] Supplier D: "190 rupees per unit. Express bike delivery right now will reach your plant in 90 minutes (1.5h)."\n'
                        '[00:27] Agent: "Confirmed: 12 units at Rs 190, 1.5-hour delivery."'
                    )
                ),
                "extracted_fields": {
                    "quantity": {
                        "value": qty_d,
                        "source_quote": f"Yes, we have {qty_d} units on shelf.",
                        "confidence": 0.99,
                    },
                    "unit_price": {
                        "value": 190.0,
                        "source_quote": "190 rupees per unit.",
                        "confidence": 0.98,
                    },
                    "availability_hours": {
                        "value": 1.5,
                        "source_quote": "reach your plant in 90 minutes (1.5h)",
                        "confidence": 0.97,
                    },
                    "delivery_method": {
                        "value": "delivery",
                        "source_quote": "Express bike delivery right now",
                        "confidence": 0.96,
                    },
                    "compatible": {
                        "value": True,
                        "source_quote": f"{part_name}... exactly what we have left in this batch",
                        "confidence": 0.99,
                    },
                },
                "retry_count": 0,
            },
        }

        offer_data = dict(
            standard_offers.get(
                name,
                {
                    "quantity_available": 0,
                    "unit_price": 0.0,
                    "availability_hours": 999.0,
                    "delivery_method": "unknown",
                    "compatible": False,
                    "compatibility_confidence": 0.0,
                    "confirmed": False,
                    "status": "UNAVAILABLE",
                    "notes": "No data for this supplier.",
                    "transcript": "[No transcript recorded]",
                    "extracted_fields": {},
                    "retry_count": 0,
                },
            )
        )

        # Dynamic Chaos Scenario Mutations
        if scenario == "supplier_unsure" and name == "Supplier A":
            offer_data.update(
                {
                    "status": "TENTATIVE",
                    "confirmed": False,
                    "quantity_available": 0,
                    "notes": "Tentative response: warehouse manager away, unconfirmed stock.",
                    "transcript": (
                        '[00:02] Agent: "Do you have 20 units of SKF 6205-2RS in physical stock right now?"\n'
                        '[00:08] Supplier A: "Uh, maybe tomorrow afternoon, let me check with the warehouse supervisor. Call back later."\n'
                        '[00:16] Agent: "Can you confirm if any units are reserved?"\n'
                        '[00:20] Supplier A: "I cannot confirm anything until tomorrow morning. Bye."'
                    ),
                    "extracted_fields": {
                        "quantity": {
                            "value": 0,
                            "source_quote": "Uh, maybe tomorrow afternoon, let me check with the warehouse supervisor. Call back later.",
                            "confidence": 0.45,
                        },
                        "status": {
                            "value": "TENTATIVE",
                            "source_quote": "I cannot confirm anything until tomorrow morning.",
                            "confidence": 0.95,
                        },
                    },
                }
            )
        elif scenario == "midcall_quantity_shift" and name == "Supplier C":
            offer_data.update(
                {
                    "status": "CONFIRMED",
                    "confirmed": True,
                    "quantity_available": 8,
                    "notes": "Mid-call stock retraction: initially claimed 16, but 8 were already allocated.",
                    "transcript": (
                        '[00:02] Agent: "We need 20 units of SKF 6205-2RS. What do you have on the shelf?"\n'
                        '[00:07] Supplier C: "Looks like we have 16 units here... wait, hold on, let me look at the job card. Ah, 8 are on hold for line 2 repair. I can only release 8 units to you."\n'
                        '[00:17] Agent: "Confirmed 8 units available at Rs 180 for immediate pickup."'
                    ),
                    "extracted_fields": {
                        "quantity": {
                            "value": 8,
                            "source_quote": "wait, hold on, let me look at the job card. Ah, 8 are on hold... I can only release 8 units to you.",
                            "confidence": 0.94,
                        },
                        "unit_price": {
                            "value": 180.0,
                            "source_quote": "release 8 units to you at 180",
                            "confidence": 0.98,
                        },
                        "availability_hours": {
                            "value": 0.5,
                            "source_quote": "immediate pickup",
                            "confidence": 0.95,
                        },
                        "compatible": {
                            "value": True,
                            "source_quote": "SKF 6205-2RS",
                            "confidence": 0.98,
                        },
                    },
                }
            )
        elif scenario == "no_answer" and name == "Supplier A":
            offer_data.update(
                {
                    "status": "NO_ANSWER",
                    "confirmed": False,
                    "quantity_available": 0,
                    "unit_price": 0.0,
                    "availability_hours": 999.0,
                    "retry_count": 1,
                    "notes": "Call rang out for 45 seconds without answer. Auto-retried once in Python, then escalated.",
                    "transcript": (
                        "[00:00] [Outbound Dialing Supplier A at +919876543211...]\n"
                        "[00:45] [Call Timeout: No answer after 45 seconds. Python auto-retry initiated.]\n"
                        "[00:47] [Outbound Dialing Retry 1/1...]\n"
                        "[01:32] [Call Timeout: Unresponsive. Python engine escalating to next supplier.]"
                    ),
                    "extracted_fields": {
                        "status": {
                            "value": "NO_ANSWER",
                            "source_quote": "[Call Timeout: Unresponsive after retry]",
                            "confidence": 1.0,
                        }
                    },
                }
            )
        elif scenario == "price_revised_upward" and name == "Supplier B":
            offer_data.update(
                {
                    "unit_price": 340.0,
                    "notes": "Emergency surcharge: unit price revised upward from 220 to 340 mid-call.",
                    "transcript": (
                        '[00:02] Agent: "Do you have 20 units of SKF 6205-2RS for urgent 2-hour dispatch?"\n'
                        '[00:08] Supplier B: "Yes, 20 in stock, but emergency breakdown dispatch has a surcharge. Our price is 340 rupees per unit today, not catalog 220."\n'
                        '[00:18] Agent: "Understood: 20 units at Rs 340, 2-hour delivery."'
                    ),
                    "extracted_fields": {
                        "quantity": {
                            "value": 20,
                            "source_quote": "Yes, 20 in stock",
                            "confidence": 0.99,
                        },
                        "unit_price": {
                            "value": 340.0,
                            "source_quote": "price is 340 rupees per unit today, not catalog 220",
                            "confidence": 0.98,
                        },
                        "availability_hours": {
                            "value": 2.0,
                            "source_quote": "urgent 2-hour dispatch",
                            "confidence": 0.97,
                        },
                    },
                }
            )
        elif scenario == "callback_promised" and name == "Supplier A":
            offer_data.update(
                {
                    "status": "CALLBACK_PROMISED",
                    "confirmed": False,
                    "quantity_available": 0,
                    "notes": "Counter staff at lunch; promised callback in 45 minutes.",
                    "transcript": (
                        '[00:02] Agent: "Calling Supplier A for emergency SKF 6205-2RS quote."\n'
                        '[00:06] Supplier A: "The warehouse terminal is locked while staff is on lunch break. Please call back in 45 minutes."\n'
                        '[00:12] Agent: "Understood. Escalating to alternative suppliers immediately."'
                    ),
                    "extracted_fields": {
                        "status": {
                            "value": "CALLBACK_PROMISED",
                            "source_quote": "locked while staff is on lunch break. Please call back in 45 minutes.",
                            "confidence": 0.92,
                        }
                    },
                }
            )

        return {
            "supplier": supplier.name,
            "phone": supplier.phone,
            "currency": "INR",
            "source": "demo",
            "call_id": call_id,
            **offer_data,
        }
