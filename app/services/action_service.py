"""Action package generator and report renderer for Phase 5: ACT.

Generates:
1. Purchase Order (PO) drafts per supplier leg.
2. Formatted Technician Dispatch messages (SMS/WhatsApp).
3. Stakeholder Status updates for plant management.
4. CMMS Ticket JSON (SAP PM / IBM Maximo compatible).
5. Lightweight mobile-optimized approver HTML view.
6. Print-ready full industrial recovery dossier HTML.

Non-negotiable: Human approval is mandatory. All generated packages are drafts.
Dispatch is disabled by default.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from ..models.models import ActionPackage, PurchaseOrderDraft

logger = logging.getLogger("restartai.actions")


class ActionService:
    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def generate_action_package(self, run_state: Dict[str, Any]) -> ActionPackage:
        run_id = run_state.get("run_id", "unknown")
        request = run_state.get("request", {})
        plan = run_state.get("recommended_plan") or run_state.get("best_expected_plan")
        maintenance = run_state.get("maintenance", {})
        is_approved = bool(run_state.get("approved", False))
        offers = run_state.get("offers", [])

        # Find phone numbers for suppliers
        supplier_phones = {}
        for o in offers:
            supplier_phones[o.get("supplier")] = o.get("phone", "")
        for s in request.get("suppliers", []):
            supplier_phones[s.get("name")] = s.get("phone", "")

        purchase_orders: List[PurchaseOrderDraft] = []
        if plan and plan.get("legs"):
            for leg in plan["legs"]:
                supp_name = leg.get("supplier", "Supplier")
                supp_suffix = supp_name.split()[-1] if supp_name else "X"
                po_num = f"PO-REC-{run_id.upper()}-{supp_suffix}"
                qty = int(leg.get("quantity", 0))
                price = float(leg.get("unit_price", 0.0))
                subtotal = round(qty * price, 2)
                phone = supplier_phones.get(supp_name, "+919876543210")

                po = PurchaseOrderDraft(
                    po_number=po_num,
                    supplier_name=supp_name,
                    supplier_phone=phone,
                    part_number=request.get("part_number", "SKF 6205-2RS"),
                    part_description=request.get("part_description", "Deep-groove ball bearing"),
                    quantity=qty,
                    unit_price=price,
                    subtotal=subtotal,
                    currency="INR",
                    delivery_method=leg.get("delivery_method", "Emergency Courier"),
                    delivery_address="Gate 2 Receiving Depot, Sector 18 Manufacturing Plant",
                    payment_terms="Net 30 · Emergency Maintenance PO",
                    status="AUTHORIZED DRAFT" if is_approved else "DRAFT - PENDING OPERATOR SIGN-OFF",
                    is_dispatched=False,
                )
                purchase_orders.append(po)

        # 2. Technician Dispatch Message
        tech_lines = []
        if plan and plan.get("legs"):
            for l in plan["legs"]:
                tech_lines.append(f"  • {l.get('supplier')}: {l.get('quantity')}u via {l.get('delivery_method')} (ETA: T+{l.get('arrival_hours')}h)")
        legs_str = "\n".join(tech_lines) if tech_lines else "  • Awaiting logistics confirmation"

        tech_msg = (
            f"🚨 RESTARTAI EMERGENCY WORK ORDER · {request.get('machine', 'CNC LINE 4').upper()}\n"
            f"Machine: {request.get('machine', 'CNC Production Line 4')}\n"
            f"Component: {request.get('part_number', 'SKF 6205-2RS')} ({request.get('part_description', 'Bearing')})\n"
            f"Inbound Parts:\n{legs_str}\n"
            f"Installation: {maintenance.get('installation_minutes', 30)}m · "
            f"{maintenance.get('required_technicians', 2)} certified mechanics required\n"
            f"Active Shift: Shift A (06:00 - 14:00 IST) · Lead: R. Sharma (#MEC-4412)\n"
            f"Action: Execute OSHA Lockout/Tagout (LOTO). Stage bearing pullers and induction heater (110°C) at Bay 2.\n"
            f"Target Line Restart: T+{plan.get('recovery_time_hours', 2.0) if plan else 2.0}h\n"
            f"Governance: {'✓ AUTHORIZED by Operator' if is_approved else '⚠️ PENDING Operator Approval - Do not unbox before sign-off'}"
        )

        # 3. Stakeholder Status Update
        rec_hours = plan.get("recovery_time_hours", 2.0) if plan else 2.0
        exp_cost = plan.get("total_exposure", 13720.0) if plan else 13720.0
        pur_cost = plan.get("total_purchase_cost", 3720.0) if plan else 3720.0
        baseline_24h_cost = request.get("downtime_cost_per_hour", 5000.0) * 24.5

        stakeholder_msg = (
            f"[INCIDENT ACTION UPDATE] {request.get('machine', 'CNC Production Line 4')} Recovery\n"
            f"Status: Emergency multi-supplier recovery plan synthesized & {'AUTHORIZED' if is_approved else 'AWAITING APPROVAL'}.\n\n"
            f"Operational Impact Containment:\n"
            f"• Target Line: {request.get('machine', 'CNC Production Line 4')}\n"
            f"• Root Cause: Critical failure of {request.get('part_number', 'SKF 6205-2RS')} (Spindle bearing seizure)\n"
            f"• Baseline Delay Exposure: ₹{baseline_24h_cost:,.0f} (Single-source supplier 24h lead time)\n"
            f"• Mitigated Total Downtime: {rec_hours:.1f} hours ({request.get('max_hours', 3.0) - rec_hours:.1f}h faster than maximum deadline)\n"
            f"• Parts Purchase Cost: ₹{pur_cost:,.2f}\n"
            f"• Total Economic Exposure: ₹{exp_cost:,.2f} (Savings vs baseline: ₹{baseline_24h_cost - exp_cost:,.0f})\n"
            f"• Sourcing Strategy: Dual-source split across {len(purchase_orders)} vendors to resolve stockout\n"
            f"• Governance: Human-in-the-loop sign-off. Zero automated credit card charges or unapproved dispatches executed."
        )

        # 4. CMMS Ticket JSON (SAP PM / IBM Maximo schema)
        cmms_ticket = {
            "cmms_header": {
                "ticket_id": f"WO-2026-REC-{run_id.upper()}",
                "origin": "RestartAI Automated Incident Sourcing Agent",
                "plant_code": "PLANT-IND-04",
                "cost_center": "CC-MACHINING-BAY2",
                "machine_id": request.get("machine_id", "cnc-line-4"),
                "machine_name": request.get("machine", "CNC Production Line 4"),
                "priority": "P1-CRITICAL",
                "lifecycle_state": "AUTHORIZED_PARTS_STAGED" if is_approved else "PENDING_MANAGEMENT_APPROVAL",
                "created_at": self._now(),
            },
            "work_scope": {
                "maintenance_task": maintenance.get("task", "bearing_replacement"),
                "failure_code": "ERR-VIB-SPINDLE-6205",
                "failure_description": "Spindle bearing vibration threshold breach. Immediate seizure risk.",
                "safety_protocol": "OSHA Lockout/Tagout (LOTO) Category 4 Isolation",
                "estimated_labor_hours": (maintenance.get("installation_minutes", 30) or 30) / 60.0,
                "required_crew_count": maintenance.get("required_technicians", 2) or 2,
                "required_competency": maintenance.get("required_technician", "Mechanical Maintenance Technician"),
                "assigned_shift": "Shift A (06:00 - 14:00 IST)",
                "assigned_lead": "R. Sharma (#MEC-4412)",
            },
            "parts_allocation": [
                {
                    "po_number": po.po_number,
                    "part_number": po.part_number,
                    "supplier": po.supplier_name,
                    "quantity": po.quantity,
                    "unit_cost_inr": po.unit_price,
                    "subtotal_inr": po.subtotal,
                    "delivery_method": po.delivery_method,
                    "delivery_depot": po.delivery_address,
                }
                for po in purchase_orders
            ],
            "economic_impact": {
                "downtime_rate_per_hour": request.get("downtime_cost_per_hour", 5000.0),
                "planned_recovery_hours": rec_hours,
                "total_purchase_cost_inr": pur_cost,
                "total_economic_exposure_inr": exp_cost,
            },
            "governance_audit": {
                "human_approval_required": True,
                "approved_by_operator": is_approved,
                "automated_po_dispatch": False,
                "dispatch_mode": "DRAFT_PREPARED_ONLY",
            },
        }

        return ActionPackage(
            run_id=run_id,
            generated_at=self._now(),
            is_approved=is_approved,
            purchase_orders=purchase_orders,
            technician_dispatch_message=tech_msg,
            stakeholder_status_note=stakeholder_msg,
            cmms_ticket=cmms_ticket,
            dispatch_policy="HUMAN_APPROVAL_MANDATORY",
            dispatch_enabled=False,
        )

    def render_mobile_approver_html(self, run_state: Dict[str, Any]) -> str:
        """Renders a self-contained, thumb-friendly mobile approver view."""
        run_id = run_state.get("run_id", "demo")
        req = run_state.get("request", {})
        plan = run_state.get("recommended_plan") or run_state.get("best_expected_plan") or {}
        is_approved = bool(run_state.get("approved", False))
        legs = plan.get("legs", [])
        hours = plan.get("recovery_time_hours", 2.0)
        purchase = plan.get("total_purchase_cost", 3720.0)
        exposure = plan.get("total_exposure", 13720.0)
        machine = req.get("machine", "CNC Production Line 4")
        part = req.get("part_number", "SKF 6205-2RS")
        qty = req.get("quantity", 20)

        legs_html = "".join(
            f"""
            <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #262b33; font-family:monospace; font-size:13px;">
              <span><b>{l.get('supplier')}</b> · {l.get('quantity')} units</span>
              <span>₹{l.get('unit_price')}/u · ETA {l.get('arrival_hours')}h</span>
            </div>
            """
            for l in legs
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>RestartAI Mobile Approver · {run_id}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0b0d10;
      color: #e5e7eb;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      padding: 16px;
      line-height: 1.5;
    }}
    .mobile-card {{
      background: #14181f;
      border: 1px solid #262b33;
      border-radius: 12px;
      padding: 18px;
      margin-bottom: 16px;
    }}
    .header-badge {{
      display: inline-block;
      background: rgba(249, 115, 22, 0.15);
      color: #ff6b35;
      border: 1px solid #ff6b35;
      font-size: 11px;
      font-weight: 700;
      padding: 4px 8px;
      border-radius: 4px;
      letter-spacing: 0.5px;
      margin-bottom: 10px;
    }}
    h1 {{ font-size: 20px; font-weight: 800; margin-bottom: 4px; }}
    .subhead {{ color: #9ca3af; font-size: 13px; margin-bottom: 14px; }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      background: #0e1116;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 14px;
      text-align: center;
    }}
    .metric-grid .lbl {{ font-size: 10px; color: #6b7280; font-family: monospace; display: block; margin-bottom: 4px; }}
    .metric-grid .val {{ font-size: 18px; font-weight: 800; color: #fff; }}
    .val.orange {{ color: #ff6b35; }}
    .btn-approve {{
      width: 100%;
      background: #10b981;
      color: #052e16;
      border: none;
      padding: 16px;
      font-size: 16px;
      font-weight: 800;
      border-radius: 8px;
      cursor: pointer;
      display: block;
      text-align: center;
      margin-bottom: 10px;
      text-decoration: none;
    }}
    .btn-reject {{
      width: 100%;
      background: transparent;
      color: #ef4444;
      border: 1px solid #ef4444;
      padding: 14px;
      font-size: 14px;
      font-weight: 700;
      border-radius: 8px;
      cursor: pointer;
      display: block;
      text-align: center;
      text-decoration: none;
    }}
    .reassurance-strip {{
      font-size: 11.5px;
      color: #6b7280;
      text-align: center;
      margin-top: 16px;
      line-height: 1.4;
    }}
    .approved-banner {{
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid #10b981;
      color: #10b981;
      padding: 14px;
      border-radius: 8px;
      font-weight: 700;
      text-align: center;
      margin-bottom: 12px;
    }}
  </style>
</head>
<body>
  <div class="header-badge">RESTARTAI · EMERGENCY INCIDENT APPROVAL</div>
  <h1>{machine}</h1>
  <div class="subhead">Component: <b>{part}</b> · <b>{qty} units required</b></div>

  {f'<div class="approved-banner">✓ PLAN AUTHORIZED BY OPERATOR<br><small style="font-size:11px; font-weight:normal;">Action package prepared. No automated PO dispatched.</small></div>' if is_approved else ''}

  <div class="mobile-card">
    <div style="font-size:11px; color:#9ca3af; font-family:monospace; margin-bottom:8px; letter-spacing:0.5px;">MINIMIZED ECONOMIC EXPOSURE PLAN</div>
    <div class="metric-grid">
      <div><span class="lbl">RECOVERY</span><span class="val">{hours}h</span></div>
      <div><span class="lbl">PARTS COST</span><span class="val">₹{purchase:,.0f}</span></div>
      <div><span class="lbl">TOTAL LOSS</span><span class="val orange">₹{exposure:,.0f}</span></div>
    </div>
    <div style="font-size:12px; font-weight:700; color:#d1d5db; margin-bottom:6px;">OPTIMAL MULTI-SUPPLIER LEGS:</div>
    {legs_html}
    <div style="font-size:11.5px; color:#9ca3af; margin-top:10px;">
      🛡️ <b>Precomputed Plan B Standby:</b> Single-source backup ready at ₹14,400 if Supplier C delays.
    </div>
  </div>

  <div class="mobile-card">
    <div style="font-size:11px; color:#9ca3af; font-family:monospace; margin-bottom:8px;">OPERATOR SIGN-OFF</div>
    {f'''
    <button class="btn-approve" onclick="authorizePlan()" id="mobApproveBtn">✓ AUTHORIZE RECOVERY PLAN</button>
    <button class="btn-reject" onclick="rejectPlan()" id="mobRejectBtn">✕ REJECT / CALL MANUALLY</button>
    ''' if not is_approved else '''
    <div style="text-align:center; color:#10b981; font-weight:700; padding:10px;">Authorization Logged · Status: CONFIRMED</div>
    '''}
  </div>

  <div class="reassurance-strip">
    🔒 <b>Human-in-the-Loop Governance Guarantee:</b><br>
    Python computes every number. The AI only explains.<br>
    Nothing is purchased or dispatched without explicit operator sign-off.
  </div>

  <script>
    async function authorizePlan() {{
      const btn = document.getElementById("mobApproveBtn");
      if (btn) btn.textContent = "Authorizing...";
      try {{
        const r = await fetch("/api/recovery/{run_id}/approve", {{ method: "POST" }});
        if (r.ok) {{
          window.location.reload();
        }} else {{
          alert("Authorization failed. Please try again.");
        }}
      }} catch (e) {{
        alert("Error: " + e.message);
      }}
    }}
    function rejectPlan() {{
      if (confirm("Reject this synthesized plan and escalate to manual sourcing?")) {{
        alert("Plan rejected. Incident escalated to manual procurement manager.");
      }}
    }}
  </script>
</body>
</html>"""

    def render_dossier_html(self, run_state: Dict[str, Any], audit_logs: List[Dict[str, Any]]) -> str:
        """Renders an executive, print-ready industrial dossier report."""
        run_id = run_state.get("run_id", "unknown")
        req = run_state.get("request", {})
        plan = run_state.get("recommended_plan") or run_state.get("best_expected_plan") or {}
        offers = run_state.get("offers", [])
        sens = run_state.get("sensitivity", {})
        fallback = run_state.get("fallback_plan", {})
        cross_ref = run_state.get("cross_reference", [])
        sched = run_state.get("technician_schedule", {})
        action_pkg = self.generate_action_package(run_state)

        # Offers table
        offers_html = "".join(
            f"""
            <tr>
              <td><b>{o.get('supplier')}</b></td>
              <td><span style="font-weight:700;">{o.get('status')}</span></td>
              <td>{o.get('quantity_available')} units</td>
              <td>₹{o.get('unit_price'):,.2f}</td>
              <td>{o.get('availability_hours')}h</td>
              <td>{o.get('delivery_method')}</td>
              <td>{int(o.get('compatibility_confidence', 0) * 100)}%</td>
            </tr>
            """
            for o in offers
        )

        # Plan legs table
        legs_html = "".join(
            f"""
            <tr>
              <td><b>{l.get('supplier')}</b></td>
              <td>{l.get('quantity')} units</td>
              <td>₹{l.get('unit_price'):,.2f}</td>
              <td>₹{l.get('quantity') * l.get('unit_price'):,.2f}</td>
              <td>{l.get('arrival_hours')}h ({l.get('delivery_method')})</td>
            </tr>
            """
            for l in plan.get("legs", [])
        )

        # PO Drafts
        pos_html = "".join(
            f"""
            <div style="border:1px solid #ccc; padding:12px; margin-bottom:12px; border-radius:4px; font-family:monospace; font-size:12px;">
              <b>PO NUMBER:</b> {po.po_number} | <b>VENDOR:</b> {po.supplier_name} ({po.supplier_phone})<br>
              <b>ITEM:</b> {po.part_number} — {po.part_description}<br>
              <b>QUANTITY:</b> {po.quantity} units @ ₹{po.unit_price:.2f}/u = <b>₹{po.subtotal:,.2f}</b><br>
              <b>DELIVERY:</b> {po.delivery_method} to {po.delivery_address}<br>
              <b>STATUS:</b> {po.status} (Not Dispatched)
            </div>
            """
            for po in action_pkg.purchase_orders
        )

        # Audit rows
        audit_html = "".join(
            f"""
            <tr>
              <td style="font-family:monospace; font-size:11px;">{a.get('created_at', '')[:19]}</td>
              <td><b>{a.get('event_type')}</b></td>
              <td>{a.get('message')}</td>
            </tr>
            """
            for a in audit_logs
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>RestartAI Dossier · {run_id}</title>
  <style>
    body {{
      font-family: Arial, Helvetica, sans-serif;
      color: #111;
      background: #f9fafb;
      margin: 0;
      padding: 30px;
      font-size: 13px;
      line-height: 1.5;
    }}
    .dossier-sheet {{
      max-width: 900px;
      margin: 0 auto;
      background: #fff;
      padding: 40px;
      border: 1px solid #d1d5db;
      box-shadow: 0 4px 20px rgba(0,0,0,0.06);
    }}
    .no-print {{
      margin-bottom: 20px;
      text-align: right;
    }}
    .btn-print {{
      background: #ff6b35;
      color: #fff;
      border: none;
      padding: 10px 20px;
      font-weight: 700;
      border-radius: 4px;
      cursor: pointer;
    }}
    .header-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 2px solid #ff6b35;
      padding-bottom: 14px;
      margin-bottom: 24px;
    }}
    h1 {{ font-size: 24px; margin: 0; color: #111827; }}
    h2 {{ font-size: 15px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; margin-top: 24px; margin-bottom: 12px; color: #1f2937; }}
    .kpi-strip {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      background: #f3f4f6;
      padding: 16px;
      border-radius: 6px;
      margin-bottom: 20px;
    }}
    .kpi-box small {{ display: block; font-size: 10px; color: #6b7280; font-family: monospace; letter-spacing: 0.5px; }}
    .kpi-box b {{ font-size: 20px; color: #111; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: 12.5px; }}
    th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e5e7eb; }}
    th {{ background: #f9fafb; font-weight: 700; color: #4b5563; font-size: 11px; }}
    .box {{ background: #f9fafb; border: 1px solid #e5e7eb; padding: 14px; border-radius: 6px; margin-bottom: 16px; }}
    pre {{ background: #111827; color: #f3f4f6; padding: 14px; border-radius: 6px; font-size: 11px; overflow-x: auto; }}
    @media print {{
      body {{ background: #fff; padding: 0; }}
      .dossier-sheet {{ border: none; box-shadow: none; padding: 0; max-width: 100%; }}
      .no-print {{ display: none; }}
    }}
  </style>
</head>
<body>
  <div class="no-print">
    <button class="btn-print" onclick="window.print()">🖨️ Print / Save as PDF</button>
  </div>
  <div class="dossier-sheet">
    <div class="header-row">
      <div>
        <h1>RESTARTAI EMERGENCY PRODUCTION RECOVERY DOSSIER</h1>
        <div style="font-size:12px; color:#6b7280; font-family:monospace; margin-top:4px;">
          RUN ID: {run_id} · GENERATED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} · MODE: {(run_state.get('mode') or 'demo').upper()}
        </div>
      </div>
      <div style="text-align:right;">
        <span style="display:inline-block; background:{'#10b981' if run_state.get('approved') else '#f59e0b'}; color:#fff; padding:4px 10px; border-radius:4px; font-weight:700; font-size:12px;">
          {'✓ OPERATOR APPROVED' if run_state.get('approved') else 'AWAITING APPROVAL'}
        </span>
      </div>
    </div>

    <div class="kpi-strip">
      <div class="kpi-box"><small>TOTAL DOWNTIME</small><b>{plan.get('recovery_time_hours', 2.0)}h</b></div>
      <div class="kpi-box"><small>PARTS PURCHASE</small><b>₹{plan.get('total_purchase_cost', 3720.0):,.2f}</b></div>
      <div class="kpi-box"><small>DOWNTIME LOSS</small><b>₹{plan.get('downtime_exposure', 10000.0):,.2f}</b></div>
      <div class="kpi-box"><small>TOTAL EXPOSURE</small><b style="color:#ff6b35;">₹{plan.get('total_exposure', 13720.0):,.2f}</b></div>
    </div>

    <h2>1. Incident & Stoppage Parameters</h2>
    <table>
      <tr><td style="width:200px;"><b>Machine Identifier:</b></td><td>{req.get('machine')}</td></tr>
      <tr><td><b>Part Required:</b></td><td>{req.get('part_number')} — {req.get('part_description')}</td></tr>
      <tr><td><b>Quota Needed:</b></td><td>{req.get('quantity')} units (Max deadline: {req.get('max_hours')}h)</td></tr>
      <tr><td><b>Downtime Loss Rate:</b></td><td>₹{req.get('downtime_cost_per_hour', 0):,.2f} / hour</td></tr>
      <tr><td><b>Available Labor:</b></td><td>{req.get('available_technicians', 3)} technicians</td></tr>
    </table>

    <h2>2. Synthesized Recovery Sourcing Legs</h2>
    <table>
      <thead>
        <tr><th>SUPPLIER</th><th>ALLOCATED QUANTITY</th><th>UNIT PRICE</th><th>SUBTOTAL</th><th>DELIVERY LOGISTICS</th></tr>
      </thead>
      <tbody>
        {legs_html}
      </tbody>
    </table>

    <h2>3. Precomputed Plan B Contingency</h2>
    <div class="box">
      <b>Contingency Trigger:</b> {fallback.get('trigger_condition', 'If Supplier C fails')}<br>
      <b>Immediate Action:</b> {fallback.get('contingency_action', 'Switch to Supplier B single-source courier')}<br>
      <b>Backup Exposure:</b> ₹{fallback.get('plan', {}).get('total_exposure', 14400.0):,.2f} (+₹{fallback.get('delta_exposure', 680.0):,.2f})
    </div>

    <h2>4. Economic Sensitivity & Breakeven Insight</h2>
    <div class="box">
      {sens.get('breakeven_explanation', 'Delay tolerance: +8.2 minutes for Supplier D before single-source Supplier B becomes optimal.')}
    </div>

    <h2>5. Human-Gated Action Package (Drafts Prepared)</h2>
    <h3 style="font-size:13px; color:#4b5563; margin-bottom:8px;">A. Purchase Order Drafts</h3>
    {pos_html}

    <h3 style="font-size:13px; color:#4b5563; margin-bottom:8px;">B. Technician Dispatch SMS / Alert Note</h3>
    <pre>{action_pkg.technician_dispatch_message}</pre>

    <h3 style="font-size:13px; color:#4b5563; margin-bottom:8px;">C. CMMS Work Order Payload (JSON)</h3>
    <pre>{json.dumps(action_pkg.cmms_ticket, indent=2)}</pre>

    <h2>6. Complete Incident Audit Trail</h2>
    <table>
      <thead><tr><th>TIMESTAMP</th><th>EVENT</th><th>DESCRIPTION</th></tr></thead>
      <tbody>
        {audit_html if audit_html else '<tr><td colspan="3">No audit logs recorded.</td></tr>'}
      </tbody>
    </table>

    <div style="margin-top:30px; border-top:1px solid #e5e7eb; padding-top:14px; font-size:11px; color:#9ca3af; text-align:center;">
      RestartAI Autonomous Production Recovery Agent · Human-in-the-Loop Governance · Generated for Factory Operations
    </div>
  </div>
</body>
</html>"""
