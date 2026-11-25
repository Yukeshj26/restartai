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

let errorToastTimer = null;

function showError(msg, tip = "") {
  const el = $("error");
  if (!el) return;
  clearTimeout(errorToastTimer);
  const msgEl = $("errorMessage");
  if (msgEl) {
    msgEl.textContent = msg;
  } else {
    el.textContent = msg;
  }
  const tipEl = $("errorTip");
  if (tipEl) {
    tipEl.textContent = tip || (msg.includes("LIVE") ? "Tip: Use DEMO mode for offline presentation without live phone keys." : "");
  }
  el.classList.remove("hidden");
  errorToastTimer = setTimeout(clearError, 8000);
}

function clearError() {
  clearTimeout(errorToastTimer);
  const el = $("error");
  if (!el) return;
  el.classList.add("hidden");
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
const MODULES = ["#/incident", "#/calls", "#/plan", "#/approval", "#/logs"];

function canAccessModule(hash) {
  if (hash === "#/incident") return true;
  if (hash === "#/logs") return true;
  if (hash === "#/calls") return Boolean(runId || lastRunData);
  if (hash === "#/plan") return Boolean(runId || (lastRunData && lastRunData.plans && lastRunData.plans.length));
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
  const stepLogs = $("step-btn-logs");

  if (step1) {
    step1.className = "rail-btn step" + (currentModule === "#/incident" ? " active" : hasRun ? " completed" : "");
  }
  if (step2) {
    step2.className = "rail-btn step" + (currentModule === "#/calls" ? " active" : hasPlan ? " completed" : !hasRun ? " locked" : "");
  }
  if (step3) {
    step3.className = "rail-btn step" + (currentModule === "#/plan" ? " active" : isApproved ? " completed" : !hasRun ? " locked" : "");
  }
  if (step4) {
    step4.className = "rail-btn step" + (currentModule === "#/approval" ? " active" : isApproved ? " completed" : !hasPlan ? " locked" : "");
  }
  if (stepLogs) {
    stepLogs.className = "rail-btn" + (currentModule === "#/logs" ? " active" : "");
  }
}

async function proceedToRecoveryPlan() {
  clearTimeout(autoAdvanceTimer);
  if (lastRunData && lastRunData.plans && lastRunData.plans.length) {
    navigate("#/plan");
    return;
  }
  
  if (!runId && lastRunData?.run_id) {
    runId = lastRunData.run_id;
  }

  if (!runId) {
    navigate("#/plan");
    return;
  }

  const btn = $("continueToPlanBtn");
  const origText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Synthesizing Plan...";
  }

  try {
    const r = await fetch(`/api/recovery/${runId}/replan`, { method: "POST" });
    const data = await readJsonResponse(r);
    render(data);
    currentModule = "#/plan";
    history.pushState(null, "", "#/plan");
    sessionStorage.setItem("restartai_current_module", "#/plan");
    $("module-incident")?.classList.add("hidden");
    $("module-calls")?.classList.add("hidden");
    $("module-plan")?.classList.remove("hidden");
    $("module-approval")?.classList.add("hidden");
    $("module-logs")?.classList.add("hidden");
    updateStepperUI();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (err) {
    showError(`Failed to generate recovery plan: ${err.message}`);
    navigate("#/plan");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = origText || "Continue to Recovery Plan →";
    }
  }
}

async function navigate(hash, replaceState = false) {
  clearTimeout(autoAdvanceTimer);
  if (!MODULES.includes(hash)) hash = "#/incident";

  // If navigating to Plan, but plans haven't been computed yet, automatically synthesize them
  if (hash === "#/plan" && runId && (!lastRunData || !lastRunData.plans || !lastRunData.plans.length)) {
    await proceedToRecoveryPlan();
    return;
  }
  
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
  $("module-logs")?.classList.toggle("hidden", hash !== "#/logs");

  if (hash === "#/logs") {
    onLogsModuleActive();
  } else {
    onLogsModuleInactive();
  }

  updateStepperUI();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

window.addEventListener("hashchange", () => {
  navigate(window.location.hash || "#/incident", true);
});

/* ========================================================================= */
/* MODULE 1: INCIDENT SETUP & DEMO SCENARIO                                  */
/* ========================================================================= */
async function onAssetSelected(machineId) {
  clearError();
  try {
    const res = await fetch(`/api/assets/${encodeURIComponent(machineId)}`);
    const machine = await readJsonResponse(res);
    const part = (machine.parts && machine.parts[0]) || {};
    
    $("machine").value = machine.name || "";
    $("part").value = part.part_number || "";
    $("desc").value = part.part_description || "";
    $("qty").value = part.default_quantity || 1;
    $("maxHours").value = machine.default_max_recovery_hours || 3.0;
    $("downtime").value = machine.downtime_cost_per_hour || 5000;
    $("techs").value = machine.default_technicians || 2;
    $("techOverride").value = "";
    $("installOverride").value = "";
    $("compat").value = part.compatibility_notes || "";

    scheduleMaintenanceIntelligence();
    logActivity(`asset_selected machine="${machine.name}" part="${part.part_number}"`);

    // Dynamically update masthead headline
    $("executiveHeadline") && ($("executiveHeadline").textContent = `${machine.name} is down.`);
  } catch (err) {
    showError(`Failed to load asset specs: ${err.message}`);
  }
}

async function simulateMachineFault(autoStart = false) {
  clearError();
  const machineId = $("assetSelector") ? $("assetSelector").value : "cnc-line-4";
  const btn = autoStart ? $("btnSimulateAndRecover") : $("btnSimulateFault");
  const origText = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="btn-icon">⏳</span> Ingesting Telemetry...`;
  }

  try {
    const res = await fetch("/api/events/fault", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        machine_id: machineId,
        auto_start: autoStart,
        mode: $("mode").value
      })
    });
    const data = await readJsonResponse(res);

    // 1. Populate form fields
    const inc = data.incident;
    if (inc) {
      $("machine").value = inc.machine || "";
      $("part").value = inc.part_number || "";
      $("desc").value = inc.part_description || "";
      $("qty").value = inc.quantity || 1;
      $("maxHours").value = inc.max_hours || 3.0;
      $("downtime").value = inc.downtime_cost_per_hour || 5000;
      $("techs").value = inc.available_technicians || 3;
      $("compat").value = inc.compatibility_notes || "";
      scheduleMaintenanceIntelligence();
    }

    // 2. Render Incoming Telemetry Banner
    const banner = $("incomingFaultBanner");
    if (banner && data.event) {
      banner.classList.remove("hidden");
      $("faultEventTime").textContent = new Date(data.event.created_at).toLocaleTimeString();
      $("faultMachineName").textContent = data.event.machine_name;
      $("faultSensorId").textContent = data.event.sensor_id;
      $("faultTelemetry").textContent = `${data.event.telemetry_value} mm/s (${data.event.telemetry_metric})`;
      $("faultCode").textContent = data.event.fault_code;
      $("faultDescription").textContent = data.event.message;
      $("faultPartResolved").textContent = `${inc.part_number} (${inc.part_description}) · ${inc.quantity} units`;
      $("faultCriticality").textContent = `CRITICAL (₹${Number(inc.downtime_cost_per_hour).toLocaleString()}/hr)`;
    }

    logActivity(`telemetry_fault_ingested machine="${data.event.machine_name}" sensor="${data.event.sensor_id}" code="${data.event.fault_code}"`);

    // 3. Flow directly into recovery if autoStart is true
    if (autoStart && data.run_id && data.recovery) {
      runId = data.run_id;
      sessionStorage.setItem("restartai_run_id", runId);

      $("stage").textContent = "CALLING";
      $("stage").classList.add("active");
      if ($("startBtn")) $("startBtn").disabled = true;

      $("incidentHeader").classList.remove("hidden");
      $("incMachine").textContent = inc.machine || "—";
      $("incPart").textContent = `${inc.part_number} × ${inc.quantity}`;
      $("incQty").textContent = `${inc.quantity} units`;
      $("incDeadline").textContent = `${inc.max_hours}h max`;
      startCostTicker(inc.downtime_cost_per_hour);

      render(data.recovery);
      navigate("#/calls");
    } else {
      // Smooth scroll to fields to let user verify
      $("machine").scrollIntoView({ behavior: "smooth", block: "center" });
    }
  } catch (err) {
    showError(`Sensor trigger error: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origText;
    }
  }
}

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
  if ($("chaosScenario")) $("chaosScenario").value = "standard";
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
    chaos_scenario: $("chaosScenario") ? $("chaosScenario").value : "standard",
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

  $("executiveHeadline") && ($("executiveHeadline").textContent = `${payload.machine} is down.`);

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

  targetQty = Number(targetQty || data.request?.quantity || 20);
  const availC = supplierC ? Number(supplierC.quantity_available || 0) : 0;
  const isPartial = supplierC && availC > 0 && availC < targetQty;

  if (isPartial) {
    const shortfallQty = targetQty - availC;
    const pctShortfall = Math.round((shortfallQty / targetQty) * 100);
    shortfallCard.classList.remove("hidden", "resolved");
    $("shortfallTitle").textContent = `Supplier C has ${availC} of ${targetQty} units (fastest pickup: 30m). Shortfall: ${shortfallQty} units.`;
    $("shortfallDesc").textContent = `Supplier C cannot fulfill the entire order, but has the fastest arrival. Rather than waiting 24h for single-source delivery, RestartAI is triggering an adaptive replan to call Supplier D for the remaining ${shortfallQty} units.`;
    $("shortfallActionLabel").textContent = "Triggering adaptive call to Supplier D...";
    $("shortfallSpinner")?.classList.remove("hidden");
    if ($("shortfallLegDLabel")) $("shortfallLegDLabel").textContent = `🚨 SHORTFALL: ${shortfallQty} Units (${pctShortfall}%)`;
    if ($("shortfallLegDEta")) $("shortfallLegDEta").textContent = "Calling Supplier D...";

    const currentMode = $("mode")?.value || $("regMode")?.value || "demo";
    // In DEMO mode, auto-advance replan after 1.5s to show autonomous agent reaction
    if (currentMode === "demo") {
      logActivity(`shortfall_detected supplier=Supplier_C available=${availC} needed=${targetQty} shortfall=${shortfallQty}`);
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
    $("shortfallActionLabel").textContent = "Supplier D responding with remaining stock...";
    if ($("shortfallLegDLabel")) $("shortfallLegDLabel").textContent = "Supplier D: Connecting...";
    if ($("shortfallLegDEta")) $("shortfallLegDEta").textContent = "Connecting to depot...";
  }

  logActivity("adaptive_replan_initiated target=shortfall_resolution");

  try {
    const r = await fetch(`/api/recovery/${runId}/replan`, { method: "POST" });
    const data = await readJsonResponse(r);
    render(data);

    logActivity(`replan_complete total_offers=${(data.offers || []).length} plan_ready=${Boolean(data.recommended_plan)}`);

    // Mark Shortfall as Resolved
    if (shortfallCard && data.recommended_plan) {
      const targetQty = Number(data.request?.quantity || 20);
      const legC = (data.recommended_plan.legs || []).find(l => l.supplier === "Supplier C");
      const legD = (data.recommended_plan.legs || []).find(l => l.supplier === "Supplier D");
      const qtyC = legC ? legC.quantity : (targetQty === 20 ? 8 : Math.floor(targetQty * 0.4));
      const qtyD = legD ? legD.quantity : (targetQty - qtyC);
      const pctD = Math.round((qtyD / targetQty) * 100);
      shortfallCard.classList.remove("hidden");
      shortfallCard.classList.add("resolved");
      $("shortfallTitle").textContent = `✓ Shortfall Resolved: Full ${targetQty} units secured across Supplier C (${qtyC}) + Supplier D (${qtyD})!`;
      $("shortfallDesc").textContent = `Fastest recovery verified: Material arrival in ${data.recommended_plan.recovery_time_hours}h. Total economic exposure: ${money(data.recommended_plan.total_exposure)}.`;
      $("shortfallSpinner")?.classList.add("hidden");
      $("shortfallActionLabel").textContent = "✓ Optimal Split Plan Generated";
      if ($("shortfallLegDLabel")) $("shortfallLegDLabel").textContent = `✓ Supplier D: ${qtyD} Units (${pctD}%)`;
      if ($("shortfallLegDEta")) $("shortfallLegDEta").textContent = `ETA: ${legD?.arrival_hours || 1.5}h · Confirmed`;
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
/* RECOVERY CONFIDENCE ENGINE LOGIC                                         */
/* ========================================================================= */
let recoveryConfidenceState = {
  score: 86,
  targetTimeStr: "14:30",
  targetHours: 2.0,
  isDrifted: false,
  isApproved: false,
  isResolved: false,
  timeline: [
    { time: "T+01m", text: "Supplier C stock confirmed (8 units) → confidence set to 82%" },
    { time: "T+02m", text: "Supplier D stock confirmed (12 units) → confidence increased to 86%" },
    { time: "T+03m", text: "Technician Shift A crew confirmed on-site (2/2 ready)" },
    { time: "T+05m", text: "Machine sensors calibrated & baseline readiness verified" }
  ]
};

function formatTargetRestartTime(recoveryHours = 2.0) {
  const now = new Date();
  const target = new Date(now.getTime() + Math.round((recoveryHours || 2.0) * 3600 * 1000));
  const hh = String(target.getHours()).padStart(2, "0");
  const mm = String(target.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function initRecoveryConfidence(data) {
  const p = data?.recommended_plan || data?.best_expected_plan || (data?.plans && data.plans[0]);
  const recoveryHours = p?.recovery_time_hours || data?.request?.max_hours || 2.0;
  recoveryConfidenceState.targetHours = recoveryHours;
  recoveryConfidenceState.targetTimeStr = formatTargetRestartTime(recoveryHours);
  recoveryConfidenceState.isApproved = !!data?.approved;

  if (data?.approved) {
    if (!recoveryConfidenceState.timeline.some(t => t.text.includes("authorized by human operator"))) {
      recoveryConfidenceState.timeline.push({
        time: "T+08m",
        text: "Recovery plan authorized by human operator → logistics dispatch confirmed"
      });
    }
  }

  updateRecoveryConfidenceUI();
}

function simulateConfidenceDrift(drift) {
  recoveryConfidenceState.isDrifted = !!drift;
  if (drift) {
    recoveryConfidenceState.score = 68;
    if (!recoveryConfidenceState.timeline.some(t => t.text.includes("ETA delayed by 25 min"))) {
      recoveryConfidenceState.timeline.push({
        time: "T+14m",
        text: "Supplier D ETA delayed by 25 min → confidence reduced to 68%",
        isAlert: true
      });
      recoveryConfidenceState.timeline.push({
        time: "T+14m",
        text: "Fallback supplier reservation prepared (Prepared for operator approval)",
        isAlert: true
      });
    }
    logActivity("confidence_drift delay_min=25 new_score=68 band=at_risk fallback=prepared");
  } else {
    recoveryConfidenceState.score = 86;
    recoveryConfidenceState.timeline.push({
      time: "T+18m",
      text: "Transit delay mitigated · Nominal delivery restored → confidence increased to 86%"
    });
    logActivity("confidence_restored nominal_schedule=true score=86 band=on_track");
  }

  updateRecoveryConfidenceUI();
}

function reviewFallbackContingency() {
  logActivity("fallback_review_initiated by=operator mode=manual_gate_preserved");
  const triadFallback = $("triadFallbackCard");
  if (triadFallback) {
    triadFallback.scrollIntoView({ behavior: "smooth", block: "center" });
    triadFallback.classList.add("highlight-triad");
    setTimeout(() => triadFallback.classList.remove("highlight-triad"), 2500);
  }
}

function validateRestartAndCloseIncident() {
  if (recoveryConfidenceState.isResolved) return;
  recoveryConfidenceState.isResolved = true;

  recoveryConfidenceState.timeline.push({
    time: "T+22m",
    text: "Restart validation complete · Machine telemetry within normal limits · Incident resolved"
  });

  logActivity("incident_resolved operator_signoff=verified telemetry=normal line=resumed");

  document.querySelectorAll("[data-btn-validate-restart]").forEach(btn => {
    btn.disabled = true;
    btn.textContent = "✓ Incident Resolved · Production Restored";
    btn.style.background = "#15803d";
  });

  document.querySelectorAll("[data-restart-closure-notice]").forEach(el => {
    el.innerHTML = "<b class=\"good\">✓ Line Restart Confirmed & Validated:</b> Physical vibration (0.02 mm/s), bearing temperature (52.4°C), and spindle load (1,450 RPM) confirmed within normal limits. Incident formally closed.";
  });

  document.querySelectorAll("[data-telemetry-overall-badge]").forEach(el => {
    el.textContent = "✓ RESOLVED & OPERATIONAL";
    el.style.background = "#bbf7d0";
    el.style.color = "#166534";
  });

  const incHdr = $("incidentHeader");
  if (incHdr) {
    const statusPill = incHdr.querySelector(".incident-status-pill");
    if (statusPill) {
      statusPill.textContent = "RESOLVED";
      statusPill.style.background = "#dcfce7";
      statusPill.style.color = "#166534";
      statusPill.style.borderColor = "#86efac";
    }
  }

  updateRecoveryConfidenceUI();
}

function resetRecoveryConfidence() {
  recoveryConfidenceState = {
    score: 86,
    targetTimeStr: "14:30",
    targetHours: 2.0,
    isDrifted: false,
    isApproved: false,
    isResolved: false,
    timeline: [
      { time: "T+01m", text: "Supplier C stock confirmed (8 units) → confidence set to 82%" },
      { time: "T+02m", text: "Supplier D stock confirmed (12 units) → confidence increased to 86%" },
      { time: "T+03m", text: "Technician Shift A crew confirmed on-site (2/2 ready)" },
      { time: "T+05m", text: "Machine sensors calibrated & baseline readiness verified" }
    ]
  };
  updateRecoveryConfidenceUI();
}

function updateRecoveryConfidenceUI() {
  const score = recoveryConfidenceState.score;
  const isDrifted = recoveryConfidenceState.isDrifted;
  const targetTime = recoveryConfidenceState.targetTimeStr;

  let bandClass = "band-on-track";
  let bandLabel = "● On track (80–100%)";
  if (score < 60) {
    bandClass = "band-critical";
    bandLabel = "✕ Intervention required (<60%)";
  } else if (score < 80) {
    bandClass = "band-at-risk";
    bandLabel = "▲ At risk (60–79%)";
  }

  document.querySelectorAll("[data-confidence-score]").forEach(el => {
    el.textContent = `${score}%`;
  });

  document.querySelectorAll("[data-confidence-band]").forEach(el => {
    el.className = `confidence-band-badge ${bandClass}`;
    el.textContent = bandLabel;
  });

  document.querySelectorAll("[data-confidence-target]").forEach(el => {
    if (isDrifted) {
      el.textContent = `${score}% likely to restart before target deadline (${targetTime}) · ETA transit slip detected`;
    } else {
      el.textContent = `${score}% likely to restart before target deadline (${targetTime})`;
    }
  });

  document.querySelectorAll("[data-factor-status='eta']").forEach(el => {
    if (isDrifted) {
      el.textContent = "Transit Slip (+25m)";
      el.className = "factor-card-status status-warning";
    } else {
      el.textContent = "On Schedule";
      el.className = "factor-card-status status-good";
    }
  });

  document.querySelectorAll("[data-factor-val='eta']").forEach(el => {
    if (isDrifted) {
      el.textContent = "+25 min drift (Delayed)";
    } else {
      el.textContent = "0 min drift (Express transit)";
    }
  });

  document.querySelectorAll("[data-factor-meta='eta']").forEach(el => {
    if (isDrifted) {
      el.textContent = "Transit variance on primary courier leg";
    } else {
      el.textContent = "Dispatched via direct courier";
    }
  });

  document.querySelectorAll("[data-fallback-card]").forEach(el => {
    if (score < 70) {
      el.classList.remove("hidden");
    } else {
      el.classList.add("hidden");
    }
  });

  document.querySelectorAll("[data-restart-validation]").forEach(el => {
    if (recoveryConfidenceState.isApproved) {
      el.classList.remove("hidden");
    } else {
      el.classList.add("hidden");
    }
  });

  document.querySelectorAll("[data-confidence-timeline]").forEach(container => {
    container.innerHTML = recoveryConfidenceState.timeline.map(item => `
      <div class="timeline-item ${item.isAlert ? 'drift-alert' : ''}">
        <span class="timeline-time">${esc(item.time)}</span>
        <span class="timeline-text">${item.isAlert ? '⚠️ ' : '• '}${esc(item.text)}</span>
      </div>
    `).join("");
  });
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
    recoveryConfidenceState.isApproved = true;
    updateRecoveryConfidenceUI();
    loadActionPackage(runId);
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

let currentActionPackage = null;

async function loadActionPackage(targetRunId) {
  if (!targetRunId) return;
  try {
    const r = await fetch(`/api/recovery/${targetRunId}/actions`);
    if (!r.ok) return;
    const pkg = await readJsonResponse(r);
    currentActionPackage = pkg;
    renderActionPackageUI(pkg, targetRunId);
  } catch (e) {
    console.warn("Failed to load action package:", e);
  }
}

function renderActionPackageUI(pkg, targetRunId) {
  if (!pkg) return;
  const mobLink = $("mobileApproverLink");
  if (mobLink) mobLink.href = `/approver/${targetRunId}`;
  const printLink = $("printDossierLink");
  if (printLink) printLink.href = `/api/recovery/${targetRunId}/report.html`;

  // Render POs
  const poContainer = $("poDraftsContainer");
  if (poContainer) {
    const pos = pkg.purchase_orders || [];
    if (!pos.length) {
      poContainer.innerHTML = '<div class="loading-placeholder">No purchase orders required.</div>';
    } else {
      poContainer.innerHTML = pos.map(po => `
        <div class="po-card">
          <b>${esc(po.po_number)}</b> · <span style="color:#fff;">${esc(po.supplier_name)}</span><br>
          <span>${po.quantity} units @ ${money(po.unit_price)} = <b>${money(po.subtotal)}</b></span><br>
          <span class="sub">${esc(po.delivery_method)} · Status: ${esc(po.status)}</span>
        </div>
      `).join("");
    }
  }

  // Render Tech Dispatch
  if ($("techDispatchText")) {
    $("techDispatchText").textContent = pkg.technician_dispatch_message || "Awaiting plan authorization...";
  }

  // Render Stakeholder Note
  if ($("stakeholderNoteText")) {
    $("stakeholderNoteText").textContent = pkg.stakeholder_status_note || "Awaiting plan authorization...";
  }

  // Render CMMS Ticket
  if ($("cmmsTicketText")) {
    $("cmmsTicketText").textContent = JSON.stringify(pkg.cmms_ticket || {}, null, 2);
  }
}

function copyActionArtifact(type) {
  let textToCopy = "";
  if (!currentActionPackage) return;
  if (type === "poDrafts") {
    textToCopy = (currentActionPackage.purchase_orders || []).map(po =>
      `[${po.po_number}] VENDOR: ${po.supplier_name} | ITEM: ${po.part_number} | QTY: ${po.quantity} | UNIT: ₹${po.unit_price} | TOTAL: ₹${po.subtotal} | STATUS: ${po.status}`
    ).join("\n");
  } else if (type === "techDispatch") {
    textToCopy = currentActionPackage.technician_dispatch_message || "";
  } else if (type === "stakeholderNote") {
    textToCopy = currentActionPackage.stakeholder_status_note || "";
  }
  if (!textToCopy) return;
  navigator.clipboard.writeText(textToCopy).then(() => {
    logActivity(`action_artifact_copied type=${type}`);
    showError("✓ Copied to clipboard!");
  }).catch(() => {
    showError("Could not copy automatically. Select text to copy.");
  });
}

function downloadCmmsJson() {
  if (!currentActionPackage || !currentActionPackage.cmms_ticket) {
    showError("Action package not ready yet.");
    return;
  }
  const blob = new Blob([JSON.stringify(currentActionPackage.cmms_ticket, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `cmms-ticket-${currentActionPackage.run_id}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  logActivity("cmms_ticket_json_downloaded");
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
  if (d.fallback_plan && d.fallback_plan.plan) {
    const fb = d.fallback_plan;
    lines.push("PRECOMPUTED PLAN B (CONTINGENCY)");
    lines.push(`- Trigger Condition: ${fb.trigger_condition}`);
    lines.push(`- Action: ${fb.contingency_action}`);
    lines.push(`- Contingency Exposure: ₹${fb.plan.total_exposure} (+₹${fb.delta_exposure})`);
    lines.push(`- Recovery Time: ${fb.plan.recovery_time_hours}h (+${fb.delta_recovery_hours}h)`);
    lines.push("");
  }
  if (d.sensitivity && d.sensitivity.breakeven_explanation) {
    lines.push("ECONOMIC SENSITIVITY & BREAKEVEN");
    lines.push(`- Breakeven Delay: ${d.sensitivity.breakeven_delay_minutes} minutes`);
    lines.push(`- Analysis: ${d.sensitivity.breakeven_explanation}`);
    lines.push("");
  }
  if (d.cross_reference && d.cross_reference.length) {
    lines.push("PART INTERCHANGE MATRIX (ENGINEERING DIRECTORY)");
    d.cross_reference.forEach(cr => {
      lines.push(`- ${cr.brand} ${cr.part_number}: ${Math.round((cr.compatibility_confidence || 0.95) * 100)}% match (${cr.notes || ''}) [REQUIRES CONFIRMATION]`);
    });
    lines.push("");
  }
  if (d.technician_schedule && d.technician_schedule.shift) {
    const s = d.technician_schedule.shift;
    lines.push("MAINTENANCE LABOR & SHIFT ASSIGNMENT");
    lines.push(`- Active Shift: ${s.name} (${s.hours})`);
    lines.push(`- Required Competency: ${s.required_capability}`);
    lines.push(`- Crew: ${(s.assigned_crew || []).map(c => `${c.name} (${c.role})`).join(", ")}`);
    lines.push("");
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
  stopDemoWalkthrough();
  clearTimeout(autoAdvanceTimer);
  clearError();
  runId = null;
  lastRunData = null;
  lastAiText = null;
  activityLog = [];
  sessionStorage.removeItem("restartai_run_id");
  sessionStorage.removeItem("restartai_current_module");

  $("incidentHeader")?.classList.add("hidden");
  $("incomingFaultBanner")?.classList.add("hidden");
  $("shortfallBanner")?.classList.add("hidden");
  $("shortfallBanner")?.classList.remove("resolved");
  $("replanPanel")?.classList.add("hidden");
  $("continueToPlanBtn") && ($("continueToPlanBtn").disabled = true);
  $("approvalBadge") && ($("approvalBadge").textContent = "AWAITING OPERATOR APPROVAL", $("approvalBadge").classList.remove("active"));
  $("approvalStatusDisplay") && ($("approvalStatusDisplay").textContent = "PENDING SIGN-OFF", $("approvalStatusDisplay").classList.remove("approved"));
  $("approvalNotice") && ($("approvalNotice").innerHTML = "⚠️ <b>No purchase has been initiated.</b> Approval is strictly required to proceed with logistics.");
  $("mod4ApproveBtn") && ($("mod4ApproveBtn").disabled = false);
  $("executiveHeadline") && ($("executiveHeadline").textContent = "CNC Production Line 4 is down.");

  clearInterval(costTicker);
  $("incCost") && ($("incCost").textContent = "₹0");
  $("offerRows").innerHTML = '<tr class="empty-row"><td colspan="7">Awaiting supplier responses...</td></tr>';
  $("offerNotes").innerHTML = "";
  $("plan").innerHTML = "";
  $("altPlans").innerHTML = '<tr class="empty-row"><td colspan="6">No alternative combinations calculated yet.</td></tr>';
  $("activityList").innerHTML = '<div class="log-empty">// awaiting incident input</div>';

  // Reset fleet highlight
  document.querySelectorAll(".fleet-node").forEach(n => n.classList.remove("selected-asset"));

  resetRecoveryConfidence();
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

function renderDecisionTriad(data) {
  const best = data.best_expected_plan || data.recommended_plan;
  const safe = data.safe_plan;
  const fb = data.fallback_plan;

  if (best) {
    const legsText = (best.legs || []).map(l => `${esc(l.supplier)} (${l.quantity}u)`).join(" + ");
    if ($("triadBestTitle")) $("triadBestTitle").textContent = legsText;
    if ($("triadBestTime")) $("triadBestTime").textContent = `${best.recovery_time_hours}h`;
    if ($("triadBestExposure")) $("triadBestExposure").textContent = money(best.total_exposure);
  }

  if (safe && $("triadSafeTitle")) {
    if (safe.feasible && (safe.legs || []).length) {
      $("triadSafeTitle").textContent = (safe.legs || []).map(l => `${esc(l.supplier)} (${l.quantity}u)`).join(" + ");
      $("triadSafeTime").textContent = `${safe.recovery_time_hours}h`;
      $("triadSafeExposure").textContent = money(safe.total_exposure);
      if ($("triadSafeStatus")) {
        $("triadSafeStatus").textContent = "Fully Confirmed · Feasible";
        $("triadSafeStatus").className = "triad-status-pill success";
      }
    } else {
      $("triadSafeTitle").textContent = "Insufficient Confirmed Audited Stock";
      $("triadSafeTime").textContent = "—";
      $("triadSafeExposure").textContent = "—";
      if ($("triadSafeStatus")) {
        $("triadSafeStatus").textContent = "Safe Plan Infeasible · Missing Tier-1 Stock";
        $("triadSafeStatus").className = "triad-status-pill warning";
      }
    }
  }

  if (fb && fb.plan && $("triadFallbackTitle")) {
    const p = fb.plan;
    const legsText = (p.legs || []).map(l => `${esc(l.supplier)} (${l.quantity}u)`).join(" + ");
    $("triadFallbackTitle").textContent = legsText;
    const deltaH = fb.delta_recovery_hours >= 0 ? `+${fb.delta_recovery_hours}h` : `${fb.delta_recovery_hours}h`;
    const deltaE = fb.delta_exposure >= 0 ? `+${money(fb.delta_exposure)}` : money(fb.delta_exposure);
    if ($("triadFallbackTime")) $("triadFallbackTime").textContent = `${p.recovery_time_hours}h (${deltaH})`;
    if ($("triadFallbackExposure")) $("triadFallbackExposure").textContent = `${money(p.total_exposure)} (${deltaE})`;
    if ($("triadFallbackTrigger")) $("triadFallbackTrigger").textContent = `Contingency trigger: ${fb.trigger_condition}. Action: ${fb.contingency_action}.`;
  }
}

function renderSensitivity(sensitivity) {
  if (!sensitivity) return;
  const txtEl = $("sensitivityBreakevenText");
  if (txtEl && sensitivity.breakeven_explanation) {
    txtEl.textContent = sensitivity.breakeven_explanation;
  }
  const rowsEl = $("sensitivityRows");
  if (!rowsEl) return;
  const points = sensitivity.points || [];
  if (!points.length) {
    rowsEl.innerHTML = '<tr><td colspan="5" class="empty-row">No sensitivity data available.</td></tr>';
    return;
  }
  const curRate = sensitivity.current_downtime_rate;
  rowsEl.innerHTML = points.map(pt => {
    const isCur = pt.downtime_rate === curRate;
    return `
      <tr class="${isCur ? 'current-rate-row' : ''}">
        <td><b>₹${pt.downtime_rate.toLocaleString()}/hr</b> ${isCur ? '<span class="match-badge">CURRENT LOSS RATE</span>' : ''}</td>
        <td>${money(pt.recommended_plan_exposure)}</td>
        <td>${money(pt.single_source_b_exposure)}</td>
        <td style="color:${pt.net_savings >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:700;">
          ${pt.net_savings >= 0 ? '+' : ''}${money(pt.net_savings)}
        </td>
        <td>${pt.savings_percent}% lower loss</td>
      </tr>
    `;
  }).join("");
}

function renderCrossRef(equivalents) {
  const el = $("crossRefRows");
  if (!el) return;
  if (!equivalents || !equivalents.length) {
    el.innerHTML = '<tr><td colspan="5" class="empty-row">No interchangeable equivalents in registry.</td></tr>';
    return;
  }
  el.innerHTML = equivalents.map(eq => `
    <tr>
      <td><b>${esc(eq.brand || '')}</b></td>
      <td class="mono"><b>${esc(eq.part_number || '')}</b></td>
      <td><span class="match-badge">${Math.round((eq.compatibility_confidence || 0.95) * 100)}% Match</span></td>
      <td>${esc(eq.notes || 'Direct form-fit-function match')}</td>
      <td><span class="badge-requires-conf">REQUIRES CONFIRMATION</span></td>
    </tr>
  `).join("");
}

function renderTechnicianSchedule(sched) {
  if (!sched) return;
  const shift = sched.shift || {};
  if ($("shiftName") && shift.name) $("shiftName").textContent = `${shift.name} (${shift.hours || '06:00 - 14:00 IST'})`;
  if ($("shiftSkill") && shift.required_capability) $("shiftSkill").textContent = shift.required_capability;
  if ($("shiftCrew") && shift.assigned_crew) {
    $("shiftCrew").textContent = shift.assigned_crew.map(c => `${c.name} (${c.role})`).join(" · ");
  }
  if ($("shiftStatusPill") && shift.name) {
    $("shiftStatusPill").textContent = `${shift.shift_id || 'SHIFT A'} ACTIVE (${shift.available_count || 3} CREW)`;
  }
  const mList = $("technicianMilestones");
  if (!mList) return;
  const milestones = sched.milestones || [];
  if (!milestones.length) {
    mList.innerHTML = '<div class="empty-row">No milestone schedule generated.</div>';
    return;
  }
  mList.innerHTML = milestones.map(m => `
    <div class="tech-milestone-item">
      <div class="milestone-time">${esc(m.time)}</div>
      <div class="milestone-title-group">
        <h4>${esc(m.title)}</h4>
        <p>${esc(m.description)}</p>
      </div>
      <div class="milestone-crew">${esc(m.technicians || 'Assigned Crew')}</div>
    </div>
  `).join("");
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
    $("offerRows").innerHTML = offers.map((o, idx) => {
      const statusClass = (o.status || "").toLowerCase().replace(/[^a-z0-9]/g, "_");
      const match = o.compatibility_confidence != null ? `<span class="match-badge">${Math.round(o.compatibility_confidence * 100)}% Match</span>` : "—";
      return `<tr>
        <td>
          <span class="status-dot ${statusClass}"></span><b>${esc(o.supplier)}</b>
          <br><button type="button" class="btn-view-transcript" onclick="openTranscriptModal(${idx})">📄 View Transcript</button>
        </td>
        <td><span class="status-badge ${statusClass}">${esc(o.status)}</span></td>
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

  // Enable Continue to Plan button once supplier offers have been received
  const contBtn = $("continueToPlanBtn");
  if (contBtn && offers.length) {
    contBtn.disabled = false;
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
    renderDecisionTriad(data);
    renderSensitivity(data.sensitivity);
    renderCrossRef(data.cross_reference);
    renderTechnicianSchedule(data.technician_schedule);
    if (runId || data.run_id) {
      renderCounterfactual(runId || data.run_id);
    }

    // Update Module 4 Recap
    $("recapMachine") && ($("recapMachine").textContent = data.request?.machine || "CNC Line 4");
    $("recapPart") && ($("recapPart").textContent = `${data.request?.part_number || "SKF 6205-2RS"} · ${p.legs?.reduce((s, l) => s + l.quantity, 0) || 20} units`);
    $("recapLegs") && ($("recapLegs").textContent = (p.legs || []).map(l => `${l.supplier} (${l.quantity})`).join(" + "));
    $("recapPurchase") && ($("recapPurchase").textContent = money(p.total_purchase_cost));
    $("recapExposure") && ($("recapExposure").textContent = money(p.total_exposure));
    if (runId) loadActionPackage(runId);
    initRecoveryConfidence(data);

    $("executiveHeadline") && ($("executiveHeadline").textContent = `${data.request?.machine || 'Machinery'} is down.`);

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
/* TRANSCRIPT & EXTRACTION MODAL HANDLERS                                    */
/* ========================================================================= */
function openTranscriptModal(offerIndex) {
  if (!lastRunData || !lastRunData.offers || !lastRunData.offers[offerIndex]) return;
  const o = lastRunData.offers[offerIndex];

  $("modalSupplierTitle").textContent = `Call Transcript · ${o.supplier}`;
  $("modalCallStatus").textContent = o.status || "—";
  $("modalCallPhone").textContent = o.phone || "—";
  $("modalCallId").textContent = o.call_id || "demo-call";
  $("modalCallRetries").textContent = String(o.retry_count || 0);

  const transcriptEl = $("modalTranscriptText");
  if (transcriptEl) {
    transcriptEl.textContent = o.transcript || "[No transcript recorded for this supplier call]";
  }

  const grid = $("modalExtractedGrid");
  if (grid) {
    const fields = o.extracted_fields || {};
    const fieldKeys = Object.keys(fields);
    if (!fieldKeys.length) {
      grid.innerHTML = '<div class="evidence-empty" style="color:var(--text-faint); font-style:italic;">No structured source quotes extracted for this call.</div>';
    } else {
      grid.innerHTML = fieldKeys.map(k => {
        const item = fields[k] || {};
        const confPct = Math.round((item.confidence || 1.0) * 100);
        return `
          <div class="evidence-card">
            <div class="evidence-head">
              <span class="evidence-field-name">${esc(k.replace(/_/g, ' '))}</span>
              <span class="evidence-conf">${confPct}% Conf</span>
            </div>
            <div class="evidence-val mono">${esc(safeText(item.value))}</div>
            <div class="evidence-quote">“${esc(item.source_quote || 'Verbatim quote from call')}”</div>
          </div>
        `;
      }).join("");
    }
  }

  $("transcriptModal")?.classList.remove("hidden");
}

function closeTranscriptModal(event) {
  $("transcriptModal")?.classList.add("hidden");
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

/* ========================================================================= */
/* PHASE 6: COUNTERFACTUAL & BENCHMARK FUNCTIONS                            */
/* ========================================================================= */
async function renderCounterfactual(targetRunId) {
  if (!targetRunId) return;
  try {
    const r = await fetch(`/api/recovery/${targetRunId}/counterfactual`);
    if (!r.ok) return;
    const cf = await readJsonResponse(r);
    
    // 1. RestartAI
    const rPlan = cf.restartai_plan || {};
    if ($("cfRestartPurchase")) $("cfRestartPurchase").textContent = money(rPlan.purchase_cost);
    if ($("cfRestartRecovery")) $("cfRestartRecovery").textContent = `${rPlan.recovery_time_hours} hours`;
    if ($("cfRestartDowntime")) $("cfRestartDowntime").textContent = money(rPlan.total_exposure - rPlan.purchase_cost);
    if ($("cfRestartExposure")) $("cfRestartExposure").textContent = money(rPlan.total_exposure);

    // 2. Fastest Single
    const fPlan = cf.counterfactual_fastest_single || {};
    if ($("cfFastestPurchase")) $("cfFastestPurchase").textContent = money(fPlan.purchase_cost);
    if ($("cfFastestRecovery")) $("cfFastestRecovery").textContent = `${fPlan.recovery_time_hours} hours`;
    if ($("cfFastestDowntime")) $("cfFastestDowntime").textContent = money(fPlan.total_exposure - fPlan.purchase_cost);
    if ($("cfFastestExposure")) $("cfFastestExposure").textContent = money(fPlan.total_exposure);
    if ($("cfFastestVerdict") && fPlan.verdict) {
      $("cfFastestVerdict").innerHTML = `<b>SUBOPTIMAL SINGLE-SOURCE:</b> ${esc(fPlan.verdict)}`;
    }

    // 3. Cheapest First
    const cPlan = cf.counterfactual_cheapest_first || {};
    if ($("cfCheapestPurchase")) $("cfCheapestPurchase").textContent = `${money(cPlan.purchase_cost)} (Saves ${money(rPlan.purchase_cost - cPlan.purchase_cost)})`;
    if ($("cfCheapestRecovery")) $("cfCheapestRecovery").textContent = `${cPlan.recovery_time_hours} hours`;
    if ($("cfCheapestDowntime")) $("cfCheapestDowntime").textContent = money(cPlan.total_exposure - cPlan.purchase_cost);
    if ($("cfCheapestExposure")) $("cfCheapestExposure").textContent = money(cPlan.total_exposure);
    if ($("cfCheapestVerdict") && cPlan.verdict) {
      $("cfCheapestVerdict").innerHTML = `<b>DISASTROUS SOURCING DEFAULT:</b> ${esc(cPlan.verdict)}`;
    }
  } catch (e) {
    console.warn("Failed to load counterfactual analysis:", e);
  }
}

async function loadBenchmarkSummary() {
  try {
    const r = await fetch('/api/benchmark/summary');
    if (!r.ok) return;
    const data = await readJsonResponse(r);
    const kpis = data.kpis || {};
    const rKpi = kpis.restartai || {};
    const fKpi = kpis.fastest_single || {};
    const cKpi = kpis.cheapest_first || {};

    if ($("bmRestartOnTime")) $("bmRestartOnTime").textContent = `${rKpi.on_time_recovery_rate}%`;
    if ($("bmFastestOnTime")) $("bmFastestOnTime").textContent = `${fKpi.on_time_recovery_rate}%`;
    if ($("bmCheapestOnTime")) $("bmCheapestOnTime").textContent = `${cKpi.on_time_recovery_rate}%`;

    if ($("bmRestartExp")) $("bmRestartExp").textContent = money(rKpi.avg_total_exposure);
    if ($("bmFastestExp")) $("bmFastestExp").textContent = `${money(fKpi.avg_total_exposure)} (+${Math.round(((fKpi.avg_total_exposure - rKpi.avg_total_exposure)/rKpi.avg_total_exposure)*100)}%)`;
    if ($("bmCheapestExp")) $("bmCheapestExp").textContent = `${money(cKpi.avg_total_exposure)} (+${Math.round(((cKpi.avg_total_exposure - rKpi.avg_total_exposure)/rKpi.avg_total_exposure)*100)}%)`;

    if ($("bmRestartTime")) $("bmRestartTime").textContent = `${rKpi.avg_recovery_time_hours} hrs`;
    if ($("bmFastestTime")) $("bmFastestTime").textContent = `${fKpi.avg_recovery_time_hours} hrs`;
    if ($("bmCheapestTime")) $("bmCheapestTime").textContent = `${cKpi.avg_recovery_time_hours} hrs`;
  } catch (e) {
    console.warn("Failed to load benchmark summary:", e);
  }
}


/* ========================================================================= */
/* PHASE 7: FLEET BOARD & DEMO STORY WALKTHROUGH                            */
/* ========================================================================= */
function selectFleetAsset(assetId) {
  const sel = $("assetSelector");
  if (sel) {
    sel.value = assetId;
    onAssetSelected(assetId);
  }
  document.querySelectorAll(".fleet-node").forEach(node => node.classList.remove("selected-asset"));
  const cardMap = {
    "cnc-line-4": "fleetCardCnc",
    "press-p-12": "fleetCardPress",
    "inj-mold-02": "fleetCardInj",
    "smt-place-1": "fleetCardSmt",
    "pack-conv-1": "fleetCardPack"
  };
  const cardId = cardMap[assetId];
  if (cardId && $(cardId)) {
    $(cardId).classList.add("selected-asset");
  }
}

let walkthroughActive = false;
let walkthroughPaused = false;
let walkthroughStep = 0;
let walkthroughTimerInterval = null;
let walkthroughElapsedSec = 0;
let walkthroughTimeout = null;

function runFullDemoStory() {
  stopDemoWalkthrough();
  resetDemo();

  walkthroughActive = true;
  walkthroughPaused = false;
  walkthroughStep = 1;
  walkthroughElapsedSec = 0;

  const banner = $("walkthroughBanner");
  if (banner) banner.classList.remove("hidden");
  updateWalkthroughBannerUI();

  walkthroughTimerInterval = setInterval(() => {
    if (!walkthroughPaused) {
      walkthroughElapsedSec++;
      const mm = String(Math.floor(walkthroughElapsedSec / 60)).padStart(2, "0");
      const ss = String(walkthroughElapsedSec % 60).padStart(2, "0");
      if ($("walkthroughTimer")) $("walkthroughTimer").textContent = `${mm}:${ss}`;
    }
  }, 1000);

  executeWalkthroughStep(1);
}

function updateWalkthroughBannerUI() {
  const stepTitles = [
    "",
    "Stage 1/4: SENSE · Sensor Telemetry Ingestion (CNC Line 4 Spindle Anomaly Detected)",
    "Stage 2/4: SENSE TO ACT · Supplier Dialing & Autonomous Shortfall Resolution",
    "Stage 3/4: DECIDE · Exposure Optimization & Counterfactual Explainer",
    "Stage 4/4: ACT & GOVERNANCE · Dispatch Package Prepared · Awaiting Operator Sign-Off"
  ];
  if ($("walkthroughStageText")) {
    $("walkthroughStageText").textContent = stepTitles[walkthroughStep] || "Hackathon Demo Walkthrough Active";
  }
  if ($("btnPauseDemo")) {
    $("btnPauseDemo").textContent = walkthroughPaused ? "▶ Resume" : "⏸ Pause";
  }
}

function togglePauseDemoWalkthrough() {
  walkthroughPaused = !walkthroughPaused;
  updateWalkthroughBannerUI();
  if (!walkthroughPaused) {
    executeWalkthroughStep(walkthroughStep);
  } else {
    clearTimeout(walkthroughTimeout);
  }
}

function advanceDemoWalkthroughStage() {
  clearTimeout(walkthroughTimeout);
  executeWalkthroughStep(walkthroughStep + 1);
}

function stopDemoWalkthrough() {
  walkthroughActive = false;
  walkthroughPaused = false;
  walkthroughStep = 0;
  clearTimeout(walkthroughTimeout);
  clearInterval(walkthroughTimerInterval);
  $("walkthroughBanner")?.classList.add("hidden");
}

function executeWalkthroughStep(step) {
  if (!walkthroughActive || step > 4) {
    if (step > 4) {
      if ($("walkthroughStageText")) {
        $("walkthroughStageText").textContent = "✓ 3-Minute Demo Walkthrough Complete! Authorize plan below.";
      }
    }
    return;
  }
  walkthroughStep = step;
  updateWalkthroughBannerUI();

  if (step === 1) {
    navigate("#/incident");
    selectFleetAsset("cnc-line-4");
    setTimeout(() => {
      simulateMachineFault(false);
      logActivity("walkthrough_stage_1_sense_complete");
      walkthroughTimeout = setTimeout(() => {
        if (!walkthroughPaused) executeWalkthroughStep(2);
      }, 3000);
    }, 400);
  } else if (step === 2) {
    startRecovery();
    logActivity("walkthrough_stage_2_calls_started");
    walkthroughTimeout = setTimeout(() => {
      if (!walkthroughPaused) executeWalkthroughStep(3);
    }, 5500);
  } else if (step === 3) {
    navigate("#/plan");
    logActivity("walkthrough_stage_3_plan_displayed");
    setTimeout(() => {
      getAiRecommendation();
    }, 1000);
    walkthroughTimeout = setTimeout(() => {
      if (!walkthroughPaused) executeWalkthroughStep(4);
    }, 6000);
  } else if (step === 4) {
    navigate("#/approval");
    logActivity("walkthrough_stage_4_approval_ready");
    $("mod4ApproveBtn")?.focus();
  }
}

/* ========================================================================= */
/* KEYBOARD SHORTCUTS & MODAL                                                */
/* ========================================================================= */
function openKeyboardModal() {
  $("keyboardModal")?.classList.remove("hidden");
}

function closeKeyboardModal(e) {
  if (e && e.target && e.target.classList.contains("modal-card")) return;
  $("keyboardModal")?.classList.add("hidden");
}

window.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : "";
  if (tag === "input" || tag === "textarea" || tag === "select") {
    if (e.key === "Escape") e.target.blur();
    return;
  }

  if (e.key === "1") {
    navigate("#/incident");
  } else if (e.key === "2") {
    if (canAccessModule("#/calls")) navigate("#/calls");
  } else if (e.key === "3") {
    if (canAccessModule("#/plan")) navigate("#/plan");
  } else if (e.key === "4") {
    if (canAccessModule("#/approval")) navigate("#/approval");
  } else if (e.key === "5" || e.key === "l" || e.key === "L") {
    navigate("#/logs");
  } else if (e.key === "n" || e.key === "N") {
    openRegisterIncidentModal();
  } else if (e.key === "d" || e.key === "D") {
    runFullDemoStory();
  } else if (e.key === "r" || e.key === "R") {
    resetDemo();
  } else if (e.key === "?") {
    openKeyboardModal();
  } else if (e.key === "Escape") {
    closeKeyboardModal();
    closeTranscriptModal();
    $("chatWidget")?.classList.add("collapsed");
  } else if (e.key === " " || e.key === "Spacebar") {
    if (currentModule === "#/calls") {
      e.preventDefault();
      proceedToRecoveryPlan();
    } else if (currentModule === "#/plan") {
      const btn = $("continueToApprovalBtn");
      if (btn) {
        e.preventDefault();
        navigate("#/approval");
      }
    }
  }
});

/* ========================================================================= */
/* MODULE 5: SYSTEM & AUDIT LOGS CONTROLLER                                  */
/* ========================================================================= */
let logsTab = "all";
let logsAutoRefreshTimer = null;
let cachedAuditLogs = [];
let cachedSystemLogs = [];
let logsLoading = false;

function onLogsModuleActive() {
  fetchLogs();
  const autoCheckbox = $("logsAutoRefresh");
  if (autoCheckbox && autoCheckbox.checked) {
    startLogsAutoRefresh();
  }
}

function onLogsModuleInactive() {
  stopLogsAutoRefresh();
}

function startLogsAutoRefresh() {
  stopLogsAutoRefresh();
  logsAutoRefreshTimer = setInterval(() => {
    if (currentModule === "#/logs" && !logsLoading) {
      fetchLogs(false);
    }
  }, 3000);
}

function stopLogsAutoRefresh() {
  if (logsAutoRefreshTimer) {
    clearInterval(logsAutoRefreshTimer);
    logsAutoRefreshTimer = null;
  }
}

function toggleLogsAutoRefresh() {
  const checkbox = $("logsAutoRefresh");
  if (checkbox && checkbox.checked) {
    startLogsAutoRefresh();
  } else {
    stopLogsAutoRefresh();
  }
}

async function fetchLogs(manual = false) {
  if (logsLoading) return;
  logsLoading = true;
  
  const statusText = $("logsLiveStatusText");
  if (manual && statusText) {
    statusText.textContent = "REFRESHING LOGS...";
  }

  try {
    const res = await fetch("/api/logs?limit=300");
    const data = await readJsonResponse(res);

    cachedAuditLogs = Array.isArray(data.audit_logs) ? data.audit_logs : [];
    cachedSystemLogs = Array.isArray(data.system_logs) ? data.system_logs : [];

    updateLogsCounters();
    updateRunIdFilterOptions();
    renderLogsList();

    const updatedEl = $("logsLastUpdated");
    if (updatedEl) {
      updatedEl.textContent = `Updated: ${new Date().toLocaleTimeString("en-IN", { hour12: false })}`;
    }
    if (statusText) {
      statusText.textContent = "LIVE BUFFER ACTIVE";
    }
  } catch (err) {
    console.error("Failed to load logs:", err);
    if (statusText) {
      statusText.textContent = "CONNECTION ERROR";
    }
  } finally {
    logsLoading = false;
  }
}

function updateLogsCounters() {
  const countAll = cachedAuditLogs.length + cachedSystemLogs.length;
  const countAudit = cachedAuditLogs.length;
  const countSystem = cachedSystemLogs.length;
  const countErrors = cachedSystemLogs.filter(l => l.level === "ERROR" || l.level === "CRITICAL").length +
    cachedAuditLogs.filter(l => (l.event_type || "").includes("error") || (l.event_type || "").includes("fail")).length;

  if ($("countLogsAll")) $("countLogsAll").textContent = countAll;
  if ($("countLogsAudit")) $("countLogsAudit").textContent = countAudit;
  if ($("countLogsSystem")) $("countLogsSystem").textContent = countSystem;
  if ($("countLogsErrors")) $("countLogsErrors").textContent = countErrors;
}

function updateRunIdFilterOptions() {
  const select = $("logsRunIdFilter");
  if (!select) return;

  const currentVal = select.value;
  const runIds = new Set();
  if (runId) runIds.add(runId);
  cachedAuditLogs.forEach(l => {
    if (l.run_id) runIds.add(l.run_id);
  });

  const existingOptions = Array.from(select.options).map(o => o.value);
  const distinctIds = Array.from(runIds);

  distinctIds.forEach(id => {
    if (!existingOptions.includes(id)) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = `Run ${id}${id === runId ? " (Active)" : ""}`;
      select.appendChild(opt);
    }
  });

  if (currentVal && existingOptions.includes(currentVal)) {
    select.value = currentVal;
  }
}

function switchLogsTab(tab) {
  logsTab = tab;
  ["all", "audit", "system", "errors"].forEach(t => {
    const btn = $(`tabLogs${t.charAt(0).toUpperCase() + t.slice(1)}`);
    if (btn) btn.classList.toggle("active", t === tab);
  });
  renderLogsList();
}

function clearLogsSearch() {
  const input = $("logsSearchInput");
  if (input) input.value = "";
  $("logsSearchClearBtn")?.classList.add("hidden");
  filterLogsDisplay();
}

function filterLogsDisplay() {
  const searchVal = ($("logsSearchInput")?.value || "").trim();
  $("logsSearchClearBtn")?.classList.toggle("hidden", !searchVal);
  renderLogsList();
}

function getUnifiedLogsList() {
  // Normalize audit logs
  const auditEntries = cachedAuditLogs.map(l => ({
    id: `audit-${l.id}`,
    source: "audit",
    timestamp: l.created_at,
    time_str: l.created_at ? new Date(l.created_at).toLocaleTimeString("en-IN", { hour12: false }) : "—",
    level: (l.event_type || "").includes("error") || (l.event_type || "").includes("fail") ? "ERROR" : "AUDIT",
    logger: "sqlite.audit_logs",
    eventType: l.event_type || "audit_event",
    run_id: l.run_id || null,
    message: l.message || "Audit event",
    payload: l.payload || null,
    rawTime: l.created_at ? new Date(l.created_at).getTime() : 0,
  }));

  // Normalize system logs
  const systemEntries = cachedSystemLogs.map((l, idx) => ({
    id: `sys-${idx}`,
    source: "system",
    timestamp: l.timestamp,
    time_str: l.time_str || (l.timestamp ? new Date(l.timestamp).toLocaleTimeString("en-IN", { hour12: false }) : "—"),
    level: l.level || "INFO",
    logger: l.logger || "restartai",
    eventType: null,
    run_id: null,
    message: l.message || "",
    payload: null,
    rawTime: l.timestamp ? new Date(l.timestamp).getTime() : 0,
  }));

  let combined = [];
  if (logsTab === "all") {
    combined = [...auditEntries, ...systemEntries];
  } else if (logsTab === "audit") {
    combined = auditEntries;
  } else if (logsTab === "system") {
    combined = systemEntries;
  } else if (logsTab === "errors") {
    combined = [...auditEntries, ...systemEntries].filter(l => l.level === "ERROR" || l.level === "WARNING" || l.level === "CRITICAL");
  }

  // Sort descending by time (most recent on top)
  combined.sort((a, b) => b.rawTime - a.rawTime);

  // Apply filters
  const keyword = ($("logsSearchInput")?.value || "").toLowerCase().trim();
  const levelFilter = ($("logsLevelFilter")?.value || "").toUpperCase().trim();
  const runFilter = ($("logsRunIdFilter")?.value || "").trim();

  return combined.filter(item => {
    if (keyword) {
      const matchText = `${item.message} ${item.logger} ${item.level} ${item.eventType || ""} ${item.run_id || ""}`.toLowerCase();
      if (!matchText.includes(keyword)) return false;
    }
    if (levelFilter) {
      if (levelFilter === "ERROR" && item.level !== "ERROR" && item.level !== "CRITICAL") return false;
      if (levelFilter === "WARNING" && !["WARNING", "ERROR", "CRITICAL"].includes(item.level)) return false;
      if (levelFilter === "INFO" && !["INFO", "WARNING", "ERROR", "CRITICAL"].includes(item.level)) return false;
    }
    if (runFilter) {
      if (item.run_id !== runFilter) return false;
    }
    return true;
  });
}

function renderLogsList() {
  const container = $("logsContainer");
  if (!container) return;

  const records = getUnifiedLogsList();
  const metaEl = $("logsStreamMeta");
  if (metaEl) {
    metaEl.textContent = `Showing ${records.length} log event${records.length === 1 ? "" : "s"}`;
  }

  if (records.length === 0) {
    container.innerHTML = `
      <div class="logs-empty-state">
        <span class="empty-icon">🔍</span>
        <p>No log records match your current filter criteria.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = records.map(r => {
    const isError = r.level === "ERROR" || r.level === "CRITICAL";
    const isWarn = r.level === "WARNING";
    const isAudit = r.source === "audit";
    const badgeClass = isAudit ? "badge-audit" : isError ? "badge-error" : isWarn ? "badge-warn" : r.level === "DEBUG" ? "badge-debug" : "badge-info";
    const rowLevelClass = isAudit ? "source-audit" : isError ? "level-error" : isWarn ? "level-warning" : r.level === "DEBUG" ? "level-debug" : "level-info";
    const hasPayload = r.payload && Object.keys(r.payload).length > 0;
    const payloadId = `payload-${r.id}`;

    return `
      <div class="log-entry-row ${rowLevelClass}">
        <div class="log-entry-meta">
          <div class="log-meta-left">
            <span class="log-badge ${badgeClass}">${esc(r.level)}</span>
            <span class="log-timestamp mono">${esc(r.time_str)}</span>
            <span class="log-component mono">${esc(r.logger)}</span>
            ${r.eventType ? `<span class="log-run-pill mono">${esc(r.eventType)}</span>` : ""}
          </div>
          <div class="log-meta-right">
            ${r.run_id ? `<span class="log-run-pill mono" title="Associated Recovery Run ID">run: ${esc(r.run_id)}</span>` : ""}
          </div>
        </div>

        <div class="log-entry-msg ${r.source === "system" ? "mono" : ""}">${esc(r.message)}</div>

        ${hasPayload ? `
          <button type="button" class="log-payload-toggle" onclick="toggleLogPayload('${payloadId}')">
            ▸ Expand Event Payload JSON
          </button>
          <pre id="${payloadId}" class="log-payload-box hidden">${esc(JSON.stringify(r.payload, null, 2))}</pre>
        ` : ""}
      </div>
    `;
  }).join("");
}

function toggleLogPayload(id) {
  const el = $(id);
  if (!el) return;
  const isHidden = el.classList.contains("hidden");
  el.classList.toggle("hidden");
  const btn = el.previousElementSibling;
  if (btn && btn.classList.contains("log-payload-toggle")) {
    btn.textContent = isHidden ? "▾ Collapse Event Payload JSON" : "▸ Expand Event Payload JSON";
  }
}

function copyLogsToClipboard() {
  const records = getUnifiedLogsList();
  if (!records.length) {
    showError("No logs to copy.");
    return;
  }
  const lines = records.map(r => `[${r.time_str}] [${r.level}] [${r.logger}] ${r.message}${r.payload ? "\n  Payload: " + JSON.stringify(r.payload) : ""}`);
  navigator.clipboard.writeText(lines.join("\n")).then(() => {
    logActivity("logs_copied_to_clipboard count=" + records.length);
    showError("Logs copied to clipboard!", "Copied " + records.length + " lines of log output.");
  }).catch(() => {
    showError("Failed to copy logs to clipboard.");
  });
}

function downloadLogsExport() {
  const records = getUnifiedLogsList();
  const blob = new Blob([JSON.stringify(records, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `restartai-logs-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

async function clearServerLogs() {
  if (!confirm("Clear in-memory server console logs? (SQLite audit records will remain preserved)")) return;
  try {
    const res = await fetch("/api/logs/system", { method: "DELETE" });
    if (res.ok) {
      cachedSystemLogs = [];
      updateLogsCounters();
      renderLogsList();
      logActivity("system_logs_cleared");
    }
  } catch (err) {
    showError("Failed to clear server logs: " + err.message);
  }
}

/* ========================================================================= */
/* NEW INCIDENT REGISTRATION CONTROLLER                                      */
/* ========================================================================= */
function openRegisterIncidentModal() {
  $("registerIncidentModal")?.classList.remove("hidden");
  if (!$("regMachine")?.value) {
    loadIncidentPreset("press-p-12");
  }
}

function closeRegisterIncidentModal(e) {
  if (e && e.target && e.target.classList.contains("modal-card")) return;
  $("registerIncidentModal")?.classList.add("hidden");
}

function loadIncidentPreset(presetId) {
  if (presetId === "press-p-12") {
    if ($("regMachine")) $("regMachine").value = "Stamping Press P-12";
    if ($("regPart")) $("regPart").value = "SEAL-KIT-HYD-80";
    if ($("regDesc")) $("regDesc").value = "High-pressure hydraulic cylinder seal kit";
    if ($("regQty")) $("regQty").value = 15;
    if ($("regMaxHours")) $("regMaxHours").value = 3.5;
    if ($("regDowntime")) $("regDowntime").value = 8000;
    if ($("regTechs")) $("regTechs").value = 2;
    if ($("regCompat")) $("regCompat").value = "80mm piston, nitrile rubber or viton";
    if ($("regPhone1")) $("regPhone1").value = "+919876543211";
    if ($("regPhone2")) $("regPhone2").value = "+919876543212";
    if ($("regPhone3")) $("regPhone3").value = "+919876543213";
    if ($("regPhone4")) $("regPhone4").value = "+919876543214";
    syncPresetToMainForm("Stamping Press P-12", "SEAL-KIT-HYD-80", "High-pressure hydraulic cylinder seal kit", 15, 3.5, 8000, 2, "80mm piston, nitrile rubber or viton");
  } else if (presetId === "cnc-line-4") {
    if ($("regMachine")) $("regMachine").value = "CNC Production Line 4";
    if ($("regPart")) $("regPart").value = "SKF 6205-2RS";
    if ($("regDesc")) $("regDesc").value = "Deep-groove ball bearing";
    if ($("regQty")) $("regQty").value = 20;
    if ($("regMaxHours")) $("regMaxHours").value = 3;
    if ($("regDowntime")) $("regDowntime").value = 5000;
    if ($("regTechs")) $("regTechs").value = 3;
    if ($("regCompat")) $("regCompat").value = "6205-2RS, 25mm bore, 52mm OD, 15mm width. Equivalent brands require confirmation.";
    if ($("regPhone1")) $("regPhone1").value = "+919876543211";
    if ($("regPhone2")) $("regPhone2").value = "+919876543212";
    if ($("regPhone3")) $("regPhone3").value = "+919876543213";
    if ($("regPhone4")) $("regPhone4").value = "+919876543214";
    syncPresetToMainForm("CNC Production Line 4", "SKF 6205-2RS", "Deep-groove ball bearing", 20, 3, 5000, 3, "6205-2RS, 25mm bore, 52mm OD, 15mm width.");
  } else if (presetId === "inj-mold-02") {
    if ($("regMachine")) $("regMachine").value = "Injection Molding Machine 02";
    if ($("regPart")) $("regPart").value = "HEATER-BAND-400W";
    if ($("regDesc")) $("regDesc").value = "Ceramic band heater 60x50mm 230V 400W";
    if ($("regQty")) $("regQty").value = 4;
    if ($("regMaxHours")) $("regMaxHours").value = 4.0;
    if ($("regDowntime")) $("regDowntime").value = 3500;
    if ($("regTechs")) $("regTechs").value = 2;
    if ($("regCompat")) $("regCompat").value = "60mm ID band heater with thermocouple clearance";
    syncPresetToMainForm("Injection Molding Machine 02", "HEATER-BAND-400W", "Ceramic band heater 60x50mm 230V 400W", 4, 4.0, 3500, 2, "60mm ID band heater with thermocouple clearance");
  } else if (presetId === "blank") {
    if ($("regMachine")) $("regMachine").value = "";
    if ($("regPart")) $("regPart").value = "";
    if ($("regDesc")) $("regDesc").value = "";
    if ($("regQty")) $("regQty").value = 1;
    if ($("regMaxHours")) $("regMaxHours").value = 3.0;
    if ($("regDowntime")) $("regDowntime").value = 5000;
    if ($("regTechs")) $("regTechs").value = 2;
    if ($("regCompat")) $("regCompat").value = "";
  }
}

function syncPresetToMainForm(m, p, d, q, h, c, t, comp) {
  if ($("machine")) $("machine").value = m;
  if ($("part")) $("part").value = p;
  if ($("desc")) $("desc").value = d;
  if ($("qty")) $("qty").value = q;
  if ($("maxHours")) $("maxHours").value = h;
  if ($("downtime")) $("downtime").value = c;
  if ($("techs")) $("techs").value = t;
  if ($("compat")) $("compat").value = comp;
  scheduleMaintenanceIntelligence();

  // Dynamically update masthead headline
  $("executiveHeadline") && ($("executiveHeadline").textContent = `${m || 'Machinery'} is down.`);
}

async function handleNewIncidentSubmit(e) {
  if (e) e.preventDefault();
  clearError();

  const machine = $("regMachine").value.trim();
  const partNumber = $("regPart").value.trim();
  const partDesc = $("regDesc").value.trim();
  const qty = Number($("regQty").value);
  const maxHours = Number($("regMaxHours").value);
  const downtime = Number($("regDowntime").value);
  const techs = Number($("regTechs").value);
  const compat = $("regCompat").value.trim();
  const mode = $("regMode").value;

  if (!machine || !partNumber || !partDesc || !qty || !maxHours) {
    showError("Please fill out all required incident fields.");
    return;
  }

  // Sync to inline form fields
  syncPresetToMainForm(machine, partNumber, partDesc, qty, maxHours, downtime, techs, compat);
  if ($("mode")) {
    $("mode").value = mode;
    updateModeUI();
  }

  const suppliers = [
    { name: "Supplier A", phone: $("regPhone1")?.value.trim() || "+919876543211", region: "IN", locale: "en-IN" },
    { name: "Supplier B", phone: $("regPhone2")?.value.trim() || "+919876543212", region: "IN", locale: "en-IN" },
    { name: "Supplier C", phone: $("regPhone3")?.value.trim() || "+919876543213", region: "IN", locale: "en-IN" },
    { name: "Supplier D", phone: $("regPhone4")?.value.trim() || "+919876543214", region: "IN", locale: "en-IN" }
  ].filter(s => s.phone);

  const payload = {
    mode: mode,
    machine: machine,
    part_number: partNumber,
    part_description: partDesc,
    quantity: qty,
    max_hours: maxHours,
    downtime_cost_per_hour: downtime,
    compatibility_notes: compat,
    available_technicians: techs,
    suppliers: suppliers,
    chaos_scenario: $("chaosScenario") ? $("chaosScenario").value : "standard",
    live_confirmed: mode === "live",
    idempotency_key: `${Date.now()}-${crypto.randomUUID()}`
  };

  closeRegisterIncidentModal();

  // Set visual status and start cost ticker
  $("stage").textContent = "CALLING";
  $("stage").classList.add("active");
  $("startBtn") && ($("startBtn").disabled = true);
  $("incidentHeader")?.classList.remove("hidden");
  $("incMachine") && ($("incMachine").textContent = payload.machine);
  $("incPart") && ($("incPart").textContent = `${payload.part_number} × ${payload.quantity}`);
  $("incQty") && ($("incQty").textContent = `${payload.quantity} units`);
  $("incDeadline") && ($("incDeadline").textContent = `${payload.max_hours}h max`);
  startCostTicker(payload.downtime_cost_per_hour);

  logActivity(`incident_registered machine="${payload.machine}" part="${payload.part_number}" qty=${payload.quantity} loss=₹${payload.downtime_cost_per_hour}/h`);

  // Navigate immediately to Module 2 to show live dialing and progress
  navigate("#/calls");

  try {
    const res = await fetch("/api/recovery/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await readJsonResponse(res);
    runId = data.run_id;
    sessionStorage.setItem("restartai_run_id", runId);

    render(data);

    chatHistory = [];
    if ($("chatMessages")) {
      $("chatMessages").innerHTML = "";
      appendChatMessage("assistant", `Recovery initialized for ${payload.machine}. Ask me anything about suppliers, offers, or recovery plans.`);
    }
    logActivity(`recovery_active run_id=${runId} offers=${(data.offers || []).length}`);

    // Trigger shortfall detection and adaptive replanning for the registered incident
    handleShortfallMoment(data, payload.quantity);
  } catch (err) {
    showError(`Recovery dispatch failed: ${err.message}`);
  }
}

// Initialize app
loadConfig();
restoreSession();
loadBenchmarkSummary();
updateRecoveryConfidenceUI();
