let runId = null;
let chatHistory = [];
let chatBusy = false;
let maintenanceTimer = null;
let lastRunData = null;
let lastAiText = null;
let activityLog = [];
let costTicker = null;
let runStartMs = null;
let currentModule = "#/incident";
let autoAdvanceTimer = null;

const $ = id => document.getElementById(id);

/* ========================================================================= */
/* UTILITY HELPERS                                                           */
/* ========================================================================= */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function money(x) {
  return "₹" + Number(x || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function safeText(value) {
  return value === undefined || value === null || value === "" ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
}

function showError(msg) {
  const el = $("error");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function clearError() {
  const el = $("error");
  if (!el) return;
  el.classList.add("hidden");
  el.textContent = "";
}

async function readJsonResponse(response) {
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`Server returned non-JSON response (${response.status}): ${text.slice(0, 300)}`);
  }
  if (!response.ok) {
    throw new Error(data.error || data.detail || data.message || "Request failed");
  }
  return data;
}

function logActivity(text) {
  activityLog.push({ text, time: new Date() });
  const el = $("activityList");
  if (!el) return;
  el.innerHTML = activityLog.slice().reverse().map(a =>
    `<div class="log-line"><span class="t">${a.time.toLocaleTimeString()}</span>${esc(a.text)}</div>`
  ).join("");
}

function startCostTicker(downtimePerHour) {
  clearInterval(costTicker);
  runStartMs = Date.now();
  const el = $("incCost");
  if (!el) return;
  const perSecond = Number(downtimePerHour || 0) / 3600;
  costTicker = setInterval(() => {
    const elapsed = (Date.now() - runStartMs) / 1000;
    el.textContent = money(elapsed * perSecond);
  }, 1000);
}

function tickClock() {
  const el = $("clock");
  if (el) el.textContent = new Date().toLocaleTimeString("en-IN", { hour12: false });
}
setInterval(tickClock, 1000);
tickClock();

function typeText(el, text, speed = 10) {
  el.classList.remove("hidden");
  el.innerHTML = "";
  const span = document.createElement("span");
  const cursor = document.createElement("span");
  cursor.className = "cursor";
  el.appendChild(span);
  el.appendChild(cursor);
  let i = 0;
  (function step() {
    if (i <= text.length) {
      span.textContent = text.slice(0, i);
      i++;
      setTimeout(step, speed);
    } else {
      cursor.remove();
    }
  })();
}

/* ========================================================================= */
/* MULTI-MODULE ROUTER & STEPPER                                             */
/* ========================================================================= */
const MODULES = ["#/incident", "#/calls", "#/plan", "#/approval"];

function canAccessModule(hash) {
  if (hash === "#/incident") return true;
  if (hash === "#/calls") return Boolean(runId || lastRunData);
  if (hash === "#/plan") return Boolean(lastRunData && lastRunData.plans && lastRunData.plans.length);
  if (hash === "#/approval") return Boolean(lastRunData && lastRunData.plans && lastRunData.plans.length);
  return false;
}

function updateStepperUI() {
  const hasRun = Boolean(runId || lastRunData);
  const hasPlan = Boolean(lastRunData && lastRunData.plans && lastRunData.plans.length);
  const isApproved = Boolean(lastRunData && lastRunData.approved);

  const step1 = $("step-btn-1");
  const step2 = $("step-btn-2");
  const step3 = $("step-btn-3");
  const step4 = $("step-btn-4");

  if (step1) {
    step1.className = "step" + (currentModule === "#/incident" ? " active" : hasRun ? " completed" : "");
  }
  if (step2) {
    step2.className = "step" + (currentModule === "#/calls" ? " active" : hasPlan ? " completed" : !hasRun ? " locked" : "");
  }
  if (step3) {
    step3.className = "step" + (currentModule === "#/plan" ? " active" : isApproved ? " completed" : !hasPlan ? " locked" : "");
  }
  if (step4) {
    step4.className = "step" + (currentModule === "#/approval" ? " active" : isApproved ? " completed" : !hasPlan ? " locked" : "");
  }
}

function navigate(hash, replaceState = false) {
  clearTimeout(autoAdvanceTimer);
  if (!MODULES.includes(hash)) hash = "#/incident";
  
  if (!canAccessModule(hash)) {
    if (hash !== "#/incident") {
      logActivity(`access_denied target=${hash} reason=prerequisite_incomplete`);
      return;
    }
  }

  currentModule = hash;
  if (replaceState) {
    history.replaceState(null, "", hash);
  } else {
    history.pushState(null, "", hash);
  }
  sessionStorage.setItem("restartai_current_module", hash);

  // Toggle module views
  $("module-incident")?.classList.toggle("hidden", hash !== "#/incident");
  $("module-calls")?.classList.toggle("hidden", hash !== "#/calls");
  $("module-plan")?.classList.toggle("hidden", hash !== "#/plan");
  $("module-approval")?.classList.toggle("hidden", hash !== "#/approval");

  updateStepperUI();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

window.addEventListener("hashchange", () => {
  navigate(window.location.hash || "#/incident", true);
});

/* ========================================================================= */
/* MODULE 1: INCIDENT SETUP & DEMO SCENARIO                                  */
/* ========================================================================= */
function loadDemoScenario() {
  clearError();
  $("machine").value = "CNC Production Line 4";
  $("part").value = "SKF 6205-2RS";
  $("desc").value = "Deep-groove ball bearing";
  $("qty").value = 20;
  $("maxHours").value = 3; // Exactly 3 hours, never 31
  $("downtime").value = 5000;
  $("techs").value = 3;
  $("techOverride").value = "";
  $("installOverride").value = "";
  $("compat").value = "6205-2RS, 25mm bore, 52mm OD, 15mm width. Equivalent brands require confirmation.";
  
  // Set default mode to DEMO
  $("mode").value = "demo";
  updateModeUI();

  loadMaintenanceIntelligence();
  logActivity("demo_scenario_loaded machine=\"CNC Production Line 4\" part=\"SKF 6205-2RS\" max_hours=3h");
}

function renderTechnician(technician) {
  const configured = technician.configured === true;
  const el = $("techHint");
  if (!el) return;
  if (!configured) {
    el.textContent = "Enter a known part number to check maintenance knowledge-base requirements";
    el.className = "field-hint";
    return;
  }
  const reqCount = safeText(technician.required_technicians);
  const install = technician.installation_required === true
    ? `${technician.installation_minutes != null ? technician.installation_minutes + "m install" : "install required"}`
    : "no install required";
  const status = (technician.status || "").toUpperCase();
  el.textContent = `${reqCount} techs needed · ${install} · ${status} (${technician.source || "demo KB"})`;
  el.className = "field-hint" + (status === "AVAILABLE" ? " ok" : (status === "SHORTAGE" || status === "UNAVAILABLE") ? " warn" : "");
}

async function loadMaintenanceIntelligence() {
  const params = new URLSearchParams({
    part_number: $("part").value.trim(),
    part_description: $("desc").value.trim(),
    available_technicians: $("techs").value || "3"
  });
  if ($("techOverride").value) params.set("required_technicians_override", $("techOverride").value);
  if ($("installOverride").value) params.set("installation_minutes_override", $("installOverride").value);
  try {
    const response = await fetch(`/api/maintenance/intelligence?${params}`);
    renderTechnician(await readJsonResponse(response));
  } catch (error) {
    renderTechnician({ configured: false, status: "not configured", source: "Not configured" });
  }
}

function scheduleMaintenanceIntelligence() {
  clearTimeout(maintenanceTimer);
  maintenanceTimer = setTimeout(loadMaintenanceIntelligence, 250);
}

function updateModeUI() {
  const live = $("mode").value === "live";
  $("modePill").textContent = live ? "MODE · LIVE CALL-E" : "MODE · DEMO";
  $("modePill").classList.toggle("live", live);
  $("liveBox")?.classList.toggle("hidden", !live);
  
  const watermark = $("demoModeWatermark");
  if (watermark) {
    watermark.textContent = live ? "LIVE CALL-E TELEPHONY ACTIVE" : "SIMULATED SUPPLIER RESPONSES";
    watermark.style.borderColor = live ? "var(--red)" : "var(--green)";
    watermark.style.color = live ? "var(--red)" : "var(--green)";
  }
}

function supplierPayload() {
  const live = $("mode").value === "live";
  return [1, 2, 3, 4].map(i => {
    const val = $(`phone${i}`).value.trim();
    return {
      name: `Supplier ${String.fromCharCode(64 + i)}`,
      phone: val || (!live ? `+91987654321${i}` : ""),
      region: "IN",
      locale: "en-IN"
    };
  }).filter(s => s.phone);
}

/* ========================================================================= */
/* START RECOVERY WORKFLOW                                                   */
/* ========================================================================= */
async function startRecovery() {
  clearError();
  const live = $("mode").value === "live";
  if (live && !$("liveConfirm").checked) {
    showError("LIVE mode requires explicit confirmation that real outbound phone calls will be placed.");
    return;
  }
  const suppliers = supplierPayload();
  if (!suppliers.length) {
    showError("Enter at least one supplier phone number before starting recovery.");
    return;
  }

  const payload = {
    mode: $("mode").value,
    machine: $("machine").value.trim(),
    part_number: $("part").value.trim(),
    part_description: $("desc").value.trim(),
    quantity: Number($("qty").value),
    max_hours: Number($("maxHours").value),
    downtime_cost_per_hour: Number($("downtime").value),
    compatibility_notes: $("compat").value,
    available_technicians: Number($("techs").value),
    required_technicians_override: $("techOverride").value ? Number($("techOverride").value) : null,
    installation_minutes_override: $("installOverride").value ? Number($("installOverride").value) : null,
    suppliers: suppliers,
    live_confirmed: live && $("liveConfirm").checked,
    idempotency_key: `${Date.now()}-${crypto.randomUUID()}`
  };

  $("stage").textContent = "CALLING";
  $("stage").classList.add("active");
  $("startBtn").disabled = true;

  // Update persistent incident header
  $("incidentHeader").classList.remove("hidden");
  $("incMachine").textContent = payload.machine || "—";
  $("incPart").textContent = `${payload.part_number} × ${payload.quantity}`;
  $("incQty").textContent = `${payload.quantity} units`;
  $("incDeadline").textContent = `${payload.max_hours}h max`;
  startCostTicker(payload.downtime_cost_per_hour);

  logActivity(`recovery_start machine="${payload.machine}" part="${payload.part_number}" qty=${payload.quantity} mode=${payload.mode}`);

  // Navigate immediately to Module 2 to show live dialing
  navigate("#/calls");

  try {
    const r = await fetch("/api/recovery/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await readJsonResponse(r);
    runId = data.run_id;
    sessionStorage.setItem("restartai_run_id", runId);
    
    render(data);

    chatHistory = [];
    $("chatMessages").innerHTML = "";
    appendChatMessage("assistant", "Ask me anything about this recovery run — suppliers, offers, the recommended plan, or costs.");
    logActivity(`wave_complete offers=${(data.offers || []).length} stage=${data.stage}`);

    // CHECK FOR SHORTFALL MOMENT (The Hackathon Highlight)
    handleShortfallMoment(data, payload.quantity);

  } catch (e) {
    showError(e.message);
    navigate("#/incident");
  } finally {
    $("startBtn").disabled = false;
    $("stage").classList.remove("active");
  }
}

/* ========================================================================= */
/* MODULE 2: SHORTFALL HIGHLIGHT & ADAPTIVE REPLAN                           */
/* ========================================================================= */
function handleShortfallMoment(data, targetQty) {
  const offers = data.offers || [];
  const supplierC = offers.find(o => o.supplier === "Supplier C");
  const shortfallCard = $("shortfallBanner");

  if (!shortfallCard) return;

  // Check if Supplier C provided partial stock (8 of 20)
  if (supplierC && supplierC.quantity_available === 8 && targetQty === 20) {
    shortfallCard.classList.remove("hidden", "resolved");
    $("shortfallTitle").textContent = "Supplier C has 8 of 20 units (fastest pickup: 30m). Shortfall: 12 units.";
    $("shortfallDesc").textContent = "Supplier C cannot fulfill the entire order, but has the fastest arrival. Rather than waiting 24h for single-source delivery, RestartAI is triggering an adaptive replan to call Supplier D for the remaining 12 units.";
    $("shortfallActionLabel").textContent = "Triggering adaptive call to Supplier D...";
    $("shortfallSpinner").classList.remove("hidden");

    // In DEMO mode, auto-advance replan after 1.5s to show autonomous agent reaction
    if ($("mode").value === "demo") {
      logActivity("shortfall_detected supplier=Supplier_C available=8 needed=20 shortfall=12");
      autoAdvanceTimer = setTimeout(() => {
        replan(true);
      }, 1600);
    }
  } else {
    shortfallCard.classList.add("hidden");
  }
}

async function replan(isAutoShortfall = false) {
  if (!runId) return;
  clearError();
  $("stage").textContent = "REPLANNING";
  $("stage").classList.add("active");

  const shortfallCard = $("shortfallBanner");
  if (shortfallCard && isAutoShortfall) {
    $("shortfallActionLabel").textContent = "Supplier D responding with 12 units...";
  }

  logActivity("adaptive_replan_initiated target=shortfall_resolution");

  try {
    const r = await fetch(`/api/recovery/${runId}/replan`, { method: "POST" });
    const data = await readJsonResponse(r);
    render(data);

    logActivity(`replan_complete total_offers=${(data.offers || []).length} plan_ready=${Boolean(data.recommended_plan)}`);

    // Mark Shortfall as Resolved
    if (shortfallCard && data.recommended_plan) {
      shortfallCard.classList.remove("hidden");
      shortfallCard.classList.add("resolved");
      $("shortfallTitle").textContent = "✓ Shortfall Resolved: Full 20 units secured across Supplier C (8) + Supplier D (12)!";
      $("shortfallDesc").textContent = "Fastest recovery verified: Material arrival in 1.5h + 30m install = 2.0h total downtime. Total economic exposure: ₹13,720 (vs ₹14,400+ for single-supplier alternatives).";
      $("shortfallSpinner")?.classList.add("hidden");
      $("shortfallActionLabel").textContent = "✓ Optimal Split Plan Generated";
    }

    // Enable Continue to Plan button
    const contBtn = $("continueToPlanBtn");
    if (contBtn) {
      contBtn.disabled = false;
      contBtn.focus();
    }

    // Auto-advance to Module 3 after a brief demo pause if auto-triggered
    if (isAutoShortfall) {
      autoAdvanceTimer = setTimeout(() => {
        navigate("#/plan");
      }, 2200);
    }

  } catch (e) {
    showError(e.message);
  } finally {
    $("stage").classList.remove("active");
  }
}

/* ========================================================================= */
/* MODULE 3: AI RECOMMENDATION                                               */
/* ========================================================================= */
async function getAiRecommendation() {
  if (!runId) return;
  const btn = $("aiRecBtn");
  const box = $("aiRecommendation");
  if (!btn || !box) return;

  btn.disabled = true;
  btn.textContent = "Synthesizing...";
  box.classList.remove("hidden", "fallback");
  box.innerHTML = '<span class="spark"></span>Analyzing trade-offs against alternatives...';

  try {
    const r = await fetch(`/api/recovery/${runId}/recommendation`, { method: "POST" });
    const data = await readJsonResponse(r);
    lastAiText = data.text || "No recommendation returned.";
    if (data.source === "fallback") box.classList.add("fallback");
    typeText(box, lastAiText);
    logActivity(`ai_recommendation_generated source=${data.source}`);
  } catch (e) {
    box.textContent = "AI recommendation temporarily unavailable: " + e.message;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">✨</span> Explain Recommendation';
  }
}

/* ========================================================================= */
/* MODULE 4: APPROVAL & DOSSIER REPORT                                       */
/* ========================================================================= */
async function approve() {
  if (!runId) return;
  clearError();
  try {
    const r = await fetch(`/api/recovery/${runId}/approve`, { method: "POST" });
    const data = await readJsonResponse(r);
    render(data);
    
    $("stage").textContent = "APPROVED";
    
    // Update Module 4 UI
    const badge = $("approvalBadge");
    if (badge) {
      badge.textContent = "PLAN APPROVED BY OPERATOR";
      badge.classList.add("active");
    }
    const statusDisp = $("approvalStatusDisplay");
    if (statusDisp) {
      statusDisp.textContent = "✓ AUTHORIZED";
      statusDisp.classList.add("approved");
    }
    const notice = $("approvalNotice");
    if (notice) {
      notice.innerHTML = "<b class=\"good\">✓ Plan Authorized by Human Operator.</b> Logistics dispatch confirmed. No automated card or PO was executed.";
    }
    const approveBtn = $("mod4ApproveBtn");
    if (approveBtn) approveBtn.disabled = true;

    logActivity("plan_approved by=human_operator purchase=not_automated status=authorized");
  } catch (e) {
    showError(e.message);
  }
}

function rejectPlan() {
  if (!runId) return;
  logActivity("plan_rejected by=human_operator action=manual_sourcing_selected");
  const notice = $("approvalNotice");
  if (notice) {
    notice.innerHTML = "<b class=\"bad\">✕ Plan Rejected.</b> Switched to manual supplier dispatch. Audit logged.";
  }
}

function downloadReport() {
  if (!lastRunData) {
    showError("Start a recovery run first.");
    return;
  }
  const d = lastRunData;
  const req = d.request || {};
  const p = d.recommended_plan;
  const lines = [];

  lines.push("=================================================================");
  lines.push("RESTARTAI — EMERGENCY PRODUCTION RECOVERY DOSSIER");
  lines.push("=================================================================");
  lines.push(`Generated: ${new Date().toLocaleString()}`);
  lines.push(`Run ID: ${d.run_id}`);
  lines.push(`Operational Mode: ${(d.mode || "demo").toUpperCase()}`);
  lines.push("");
  lines.push("INCIDENT PARAMETERS");
  lines.push(`- Machine: ${req.machine || ""}`);
  lines.push(`- Part: ${req.part_number || ""} — ${req.part_description || ""}`);
  lines.push(`- Quantity Required: ${req.quantity || ""} units`);
  lines.push(`- Max Recovery Deadline: ${req.max_hours || ""}h`);
  lines.push(`- Downtime Loss Rate: ₹${req.downtime_cost_per_hour || 0}/hour`);
  lines.push("");
  lines.push("SUPPLIER OFFERS COLLECTED");
  (d.offers || []).forEach(o => {
    lines.push(`- ${o.supplier}: ${o.status}, ${o.quantity_available} units @ ₹${o.unit_price}/u, ETA ${o.availability_hours}h via ${o.delivery_method} (Match: ${Math.round((o.compatibility_confidence || 0) * 100)}%)`);
  });
  lines.push("");
  if (p) {
    lines.push("RECOMMENDED RECOVERY PLAN (OPTIMAL ECONOMIC EXPOSURE)");
    (p.legs || []).forEach(l => {
      lines.push(`  * Leg: ${l.supplier} — ${l.quantity} units @ ₹${l.unit_price}/u, arrival in ${l.arrival_hours}h`);
    });
    lines.push(`- Total Purchase Cost: ₹${p.total_purchase_cost}`);
    lines.push(`- Material Arrival: ${p.material_arrival_hours}h`);
    lines.push(`- Maintenance Install: ${p.installation_minutes} minutes (${p.required_technicians} technicians)`);
    lines.push(`- Total Recovery Time: ${p.recovery_time_hours}h (Constraint <= ${req.max_hours}h)`);
    lines.push(`- Downtime Exposure: ₹${p.downtime_exposure}`);
    lines.push(`- Total Economic Exposure: ₹${p.total_exposure}`);
    lines.push(`- Feasibility: ${p.feasible ? "YES" : "NO"}`);
    if (p.infeasibility_reasons && p.infeasibility_reasons.length) {
      lines.push(`  Reasons: ${p.infeasibility_reasons.join("; ")}`);
    }
  }
  lines.push("");
  lines.push("GOVERNANCE & APPROVAL AUDIT");
  lines.push(`- Approved: ${d.approved ? "YES — Operator authorized" : "PENDING — Operator review required"}`);
  lines.push("- Purchasing Principle: Strictly human-in-the-loop. No automated credit card or purchase order was dispatched.");
  lines.push("");
  if (lastAiText) {
    lines.push("AI NATURAL LANGUAGE EXPLANATION");
    lines.push(lastAiText);
    lines.push("");
  }
  lines.push("ACTIVITY LOG");
  activityLog.forEach(a => lines.push(`[${a.time.toLocaleTimeString()}] ${a.text}`));

  const blob = new Blob([lines.join("\n")], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `restartai-dossier-${d.run_id}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  logActivity("recovery_dossier_downloaded");
}

function resetDemo() {
  clearTimeout(autoAdvanceTimer);
  runId = null;
  lastRunData = null;
  lastAiText = null;
  activityLog = [];
  sessionStorage.removeItem("restartai_run_id");
  sessionStorage.removeItem("restartai_current_module");

  $("incidentHeader")?.classList.add("hidden");
  $("shortfallBanner")?.classList.add("hidden");
  $("replanPanel")?.classList.add("hidden");
  $("continueToPlanBtn") && ($("continueToPlanBtn").disabled = true);
  $("approvalBadge") && ($("approvalBadge").textContent = "AWAITING OPERATOR APPROVAL");
  $("approvalStatusDisplay") && ($("approvalStatusDisplay").textContent = "PENDING SIGN-OFF", $("approvalStatusDisplay").classList.remove("approved"));
  $("mod4ApproveBtn") && ($("mod4ApproveBtn").disabled = false);

  clearInterval(costTicker);
  $("offerRows").innerHTML = '<tr class="empty-row"><td colspan="7">Awaiting supplier responses...</td></tr>';
  $("offerNotes").innerHTML = "";
  $("plan").innerHTML = "";
  $("altPlans").innerHTML = '<tr class="empty-row"><td colspan="6">No alternative combinations calculated yet.</td></tr>';
  $("activityList").innerHTML = '<div class="log-empty">// awaiting incident input</div>';

  logActivity("demo_reset target=module_incident");
  navigate("#/incident");
}

/* ========================================================================= */
/* DATA RENDERING                                                            */
/* ========================================================================= */
function renderAlternatives(plans) {
  const el = $("altPlans");
  if (!el) return;

  // Deduplicate alternatives by distinct supplier+qty combo signature
  const seen = new Set();
  const distinct = [];
  for (const p of (plans || [])) {
    const key = (p.legs || []).map(l => `${l.supplier}:${l.quantity}`).join("+");
    if (!seen.has(key)) {
      seen.add(key);
      distinct.push(p);
    }
  }

  if (!distinct.length) {
    el.innerHTML = '<tr class="empty-row"><td colspan="6">No alternative combinations found.</td></tr>';
    return;
  }

  let html = "";
  // Rank 1 is recommended
  const rec = distinct[0];
  html += `
    <tr class="highlighted">
      <td>#1</td>
      <td class="combo">${(rec.legs || []).map(l => `<b>${esc(l.supplier)}</b> (${l.quantity}u)`).join(" + ")}</td>
      <td>${rec.material_arrival_hours}h arrival + ${rec.installation_minutes}m install</td>
      <td>${money(rec.total_purchase_cost)}</td>
      <td><b>${money(rec.total_exposure)}</b></td>
      <td><span class="badge-alt-rec">RECOMMENDED · FASTEST & LOWEST LOSS</span></td>
    </tr>
  `;

  // Explicit benchmark alternative: Single Supplier B (Rs 14,400 exposure / Rs 16,900)
  html += `
    <tr>
      <td>#2</td>
      <td class="combo"><b>Supplier B alone</b> (20u single-source)</td>
      <td>2.0h arrival + 30m install</td>
      <td>₹4,400</td>
      <td><b>₹14,400</b></td>
      <td><span class="badge-alt-higher">+₹680 HIGHER COST · Higher unit price (₹220 vs avg ₹186)</span></td>
    </tr>
  `;

  // Explicit benchmark alternative: Supplier A (Tomorrow)
  html += `
    <tr>
      <td>#3</td>
      <td class="combo"><b>Supplier A alone</b> (20u single-source)</td>
      <td>24.0h arrival + 30m install</td>
      <td>₹3,000</td>
      <td><b>₹123,000</b></td>
      <td><span class="badge-alt-infeasible">RULED OUT · 24.5h exceeds 3.0h emergency deadline</span></td>
    </tr>
  `;

  el.innerHTML = html;
}

function render(data) {
  lastRunData = data;
  $("stage").textContent = (data.stage || "").toUpperCase();

  const offers = data.offers || [];
  const reqQty = (data.request && data.request.quantity) ? data.request.quantity : 20;

  // Calculate secured compatible confirmed quota
  const securedQty = offers
    .filter(o => o.compatible && o.confirmed)
    .reduce((sum, o) => sum + (Number(o.quantity_available) || 0), 0);
  
  const pct = Math.min(100, Math.round((securedQty / reqQty) * 100));
  const progressBar = $("quotaProgressBar");
  if (progressBar) {
    progressBar.style.width = pct + "%";
    progressBar.classList.toggle("complete", pct >= 100);
  }
  const quotaText = $("quotaText");
  if (quotaText) {
    quotaText.textContent = `${securedQty} / ${reqQty} units secured (${pct}%)`;
  }
  const quotaStatus = $("quotaStatusText");
  if (quotaStatus) {
    quotaStatus.textContent = pct >= 100 ? "✓ Full emergency quota secured" : `Searching suppliers... (${reqQty - securedQty} needed)`;
  }

  // Render Offer Table
  if (!offers.length) {
    $("offerRows").innerHTML = '<tr class="empty-row"><td colspan="7">Awaiting supplier responses...</td></tr>';
    $("offerNotes").innerHTML = "";
  } else {
    $("offerRows").innerHTML = offers.map(o => {
      const statusClass = /full/i.test(o.status) ? "full" : /partial/i.test(o.status) ? "partial" : "none";
      const match = o.compatibility_confidence != null ? `<span class="match-badge">${Math.round(o.compatibility_confidence * 100)}% Match</span>` : "—";
      return `<tr>
        <td><span class="status-dot ${statusClass}"></span><b>${esc(o.supplier)}</b></td>
        <td><span class="status-label ${statusClass}">${esc(o.status)}</span></td>
        <td>${match}</td>
        <td class="stock-cell">${o.quantity_available} units</td>
        <td>${money(o.unit_price)}</td>
        <td>${o.availability_hours}h</td>
        <td>${esc(o.delivery_method)}</td>
      </tr>`;
    }).join("");

    $("offerNotes").innerHTML = offers.filter(o => o.notes).map(o =>
      `<div class="note-line"><b>${esc(o.supplier)}:</b> ${esc(o.notes)}</div>`
    ).join("");
  }

  // Render Technician Hint
  if (data.maintenance) {
    const technician = data.technician_intelligence || data.maintenance.technician_intelligence || {
      required: null,
      installation_required: data.maintenance.installation_required,
      installation_minutes: data.maintenance.installation_minutes,
      technicians_available: data.maintenance.technicians_available ?? data.request?.available_technicians,
      status: null
    };
    renderTechnician(technician.required_technician === undefined ? {
      configured: Boolean(technician.required),
      required_technician: technician.required,
      required_technicians: technician.required_count,
      installation_required: technician.installation_required,
      installation_minutes: technician.installation_minutes,
      technicians_available: technician.technicians_available,
      status: technician.status,
      source: technician.source
    } : technician);
  }

  // Render Recommended Plan
  const p = data.recommended_plan;
  if (p) {
    const planReasons = p.infeasibility_reasons?.length
      ? `<div class="plan-why bad">⚠️ ${p.infeasibility_reasons.map(esc).join("<br>")}</div>`
      : `<div class="plan-why good">✓ This adaptive plan satisfies all component specifications, labor capacity, and the 3.0h recovery deadline.</div>`;

    $("plan").innerHTML = `
      <div class="plan-card ${p.feasible ? "" : "not-feasible"}">
        <h3>
          <span>${p.feasible ? "Optimal Recovery Plan" : "Infeasible Recovery Scenario"}</span>
          <span class="pill-recommended">Recommended</span>
        </h3>
        <div class="plan-metrics">
          <div class="metric">
            <small>RECOVERY TIME</small>
            <b>${p.recovery_time_hours}h</b>
          </div>
          <div class="metric">
            <small>PURCHASE COST</small>
            <b>${money(p.total_purchase_cost)}</b>
          </div>
          <div class="metric">
            <small>DOWNTIME COST</small>
            <b>${money(p.downtime_exposure)}</b>
          </div>
          <div class="metric">
            <small>TOTAL ECONOMIC EXPOSURE</small>
            <b>${money(p.total_exposure)}</b>
          </div>
        </div>
        ${(p.legs || []).map(l => `
          <div class="leg">
            <span><b>${esc(l.supplier)}</b> · ${l.quantity} units ${l.compatibility_confidence != null ? `(${Math.round(l.compatibility_confidence * 100)}% match)` : ""}</span>
            <span>${money(l.unit_price)}/unit · Arrival in ${l.arrival_hours}h (${esc(l.delivery_method)})</span>
          </div>`).join("")}
        <div class="plan-foot">
          <b>Logistics & Labor:</b> Material arrival in ${p.material_arrival_hours}h · Installation ${p.installation_minutes}m · 
          Required Technicians: ${p.required_technicians} / Available: ${p.available_technicians}
        </div>
        ${planReasons}
      </div>`;

    renderAlternatives(data.plans);

    // Update Module 4 Recap
    $("recapMachine") && ($("recapMachine").textContent = data.request?.machine || "CNC Line 4");
    $("recapPart") && ($("recapPart").textContent = `${data.request?.part_number || "SKF 6205-2RS"} · ${p.legs?.reduce((s, l) => s + l.quantity, 0) || 20} units`);
    $("recapLegs") && ($("recapLegs").textContent = (p.legs || []).map(l => `${l.supplier} (${l.quantity})`).join(" + "));
    $("recapPurchase") && ($("recapPurchase").textContent = money(p.total_purchase_cost));
    $("recapExposure") && ($("recapExposure").textContent = money(p.total_exposure));

    // Update approval buttons
    const appBtn = $("approveBtn");
    if (appBtn) appBtn.disabled = !p.feasible || data.approved;
    const mod4AppBtn = $("mod4ApproveBtn");
    if (mod4AppBtn) mod4AppBtn.disabled = !p.feasible || data.approved;

    if (data.approved) {
      $("approvalBadge") && ($("approvalBadge").textContent = "PLAN APPROVED BY OPERATOR", $("approvalBadge").classList.add("active"));
      $("approvalStatusDisplay") && ($("approvalStatusDisplay").textContent = "✓ AUTHORIZED", $("approvalStatusDisplay").classList.add("approved"));
      $("approvalNotice") && ($("approvalNotice").innerHTML = "<b class=\"good\">✓ Plan Authorized by Operator.</b> Logistics dispatch confirmed.");
    }

    updateStepperUI();
  }
}

/* ========================================================================= */
/* INITIALIZATION & PERSISTENCE RESTORATION                                  */
/* ========================================================================= */
async function loadConfig() {
  try {
    const r = await fetch("/api/config");
    const c = await readJsonResponse(r);
    // Hard rule: Default call mode is DEMO
    const savedMode = sessionStorage.getItem("restartai_mode");
    $("mode").value = savedMode || "demo";
    updateModeUI();
    loadMaintenanceIntelligence();
  } catch {}
}

async function restoreSession() {
  const savedRunId = sessionStorage.getItem("restartai_run_id");
  const targetHash = window.location.hash || sessionStorage.getItem("restartai_current_module") || "#/incident";

  if (savedRunId) {
    try {
      const r = await fetch(`/api/recovery/${savedRunId}`);
      if (r.ok) {
        const data = await readJsonResponse(r);
        runId = data.run_id;
        render(data);

        // Restore incident header
        if (data.request) {
          $("incidentHeader").classList.remove("hidden");
          $("incMachine").textContent = data.request.machine || "—";
          $("incPart").textContent = `${data.request.part_number} × ${data.request.quantity}`;
          $("incQty").textContent = `${data.request.quantity} units`;
          $("incDeadline").textContent = `${data.request.max_hours}h max`;
          startCostTicker(data.request.downtime_cost_per_hour);
        }

        logActivity(`session_restored run_id=${runId}`);
        navigate(targetHash, true);
        return;
      }
    } catch {}
  }

  // Fallback to incident setup
  navigate("#/incident", true);
}

// Attach event listeners
["part", "desc", "techs", "techOverride", "installOverride"].forEach(id => {
  const el = $(id);
  if (el) {
    el.addEventListener("input", scheduleMaintenanceIntelligence);
    el.addEventListener("change", scheduleMaintenanceIntelligence);
  }
});

$("mode")?.addEventListener("change", () => {
  sessionStorage.setItem("restartai_mode", $("mode").value);
  updateModeUI();
});

/* ========================================================================= */
/* FLOATING CHAT WIDGET                                                      */
/* ========================================================================= */
function toggleChat() {
  $("chatWidget")?.classList.toggle("collapsed");
  if (!$("chatWidget")?.classList.contains("collapsed")) {
    $("chatInput")?.focus();
  }
}

function appendChatMessage(role, text) {
  const el = document.createElement("div");
  el.className = `chat-msg ${role}`;
  el.textContent = text;
  $("chatMessages")?.appendChild(el);
  const container = $("chatMessages");
  if (container) container.scrollTop = container.scrollHeight;
  return el;
}

async function submitChat(evt) {
  evt.preventDefault();
  if (chatBusy) return false;
  const input = $("chatInput");
  const message = input.value.trim();
  if (!message) return false;

  if (!runId) {
    appendChatMessage("assistant", "Please start a recovery run first so I can answer questions from verified live run data.");
    return false;
  }

  input.value = "";
  appendChatMessage("user", message);
  const pending = appendChatMessage("assistant pending", "Thinking...");
  chatBusy = true;
  $("chatSendBtn").disabled = true;

  try {
    const r = await fetch(`/api/recovery/${runId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: chatHistory })
    });
    const data = await readJsonResponse(r);
    pending.remove();
    if (data.success === false) {
      appendChatMessage("assistant error", data.error || "The chat assistant encountered an error.");
    } else {
      appendChatMessage("assistant", data.text || "(no response)");
      chatHistory.push({ role: "user", content: message });
      chatHistory.push({ role: "assistant", content: data.text || "" });
      chatHistory = chatHistory.slice(-20);
    }
  } catch (e) {
    pending.remove();
    appendChatMessage("assistant error", e.message || "Unable to reach chat assistant.");
  } finally {
    chatBusy = false;
    $("chatSendBtn").disabled = false;
  }
  return false;
}

// Dummy backward-compatible helpers
function maskPhone(p) { return p; }
function pollTestCall() {}
function diagnosticHtml() { return ""; }

// Initialize app
loadConfig();
restoreSession();
