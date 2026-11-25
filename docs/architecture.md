# RestartAI Architecture

RestartAI is an emergency parts-recovery automation agent for industrial manufacturing plants. When critical factory machinery halts due to component failure, RestartAI identifies the failure, coordinates quotes across suppliers, formulates optimal recovery plans under deadline and technician constraints, and prepares actionable dispatch packages for human sign-off.

## Core Architectural Invariants

1. **Deterministic Python Core**: The LLM never computes arithmetic, downtime exposure, technician feasibility, or plan ranking. All calculations are strictly implemented in deterministic Python.
2. **Human-in-the-Loop Gate**: No real purchase orders or field dispatches are executed automatically. The system prepares drafts and awaits human operator approval.
3. **Safe Offline Demo Default**: `DEMO` mode operates offline and deterministically without requiring API keys or telephony credits. `LIVE` mode requires explicit confirmation and E.164 phone validation.
4. **Golden Scenario Invariant**: The standard CNC Production Line 4 benchmark must consistently yield Plan C + D (2.0h recovery, Rs 3,720 purchase, Rs 13,720 total exposure).

---

## Modular Layout

```
restartai/
├── app/
│   ├── api/             # FastAPI routers and HTTP endpoint handlers
│   ├── core/            # Central settings, SQLite connection manager, structured logging
│   ├── engine/          # Combinatorial recovery engine & maintenance intelligence
│   ├── models/          # Pydantic data schemas (Requests, Offers, Plans, Suppliers)
│   ├── services/        # External services: CALL-E telephony, LLM explanation, SQLite storage
│   ├── static/          # CSS, JavaScript (4-module UI), and asset files
│   └── templates/       # Jinja2 HTML templates
├── data/
│   ├── maintenance_tasks.json  # Maintenance knowledge base (technician capabilities & durations)
│   └── restartai.db            # SQLite persistence database (WAL mode)
├── docs/                # Architecture and database documentation
├── tests/
│   ├── integration/     # End-to-end API tests and golden scenario regression tests
│   └── unit/            # Unit tests for engine, CALL-E service, and storage persistence
├── Dockerfile           # Production container build
├── Makefile             # Unix developer targets (install, run, test, clean)
└── run.ps1              # Windows PowerShell developer runner
```

---

## Request Flow: Sense -> Decide -> Act

```mermaid
flowchart LR
    A[Event: Machine Halt / Sensor Webhook] --> B[Asset Registry Lookup]
    B --> C[Incident Formulation & Default Suppliers]
    C --> D[Supplier Quote Collection / CALL-E]
    D --> E[Deterministic Recovery Planner]
    E --> F[LLM Plain-English Explanation]
    F --> G[Human Operator Dashboard]
    G -->|Approved| H[Action Package Drafts]
```

---

## Phase 2 SENSE Layer (Asset Registry & Industrial IoT Webhook)

The SENSE subsystem provides automated ingestion of machine stoppage and sensor telemetry:
- **Asset Registry (`data/assets.json`)**: Preconfigures plant assets (`CNC Production Line 4`, `Injection Molding Machine 02`, `Stamping Press P-12`, `Packaging Line Conveyor C-1`), their telemetry thresholds, downtime costs, technician requirements, critical replacement parts, specifications, and brand equivalents.
- **Sensor Webhook (`POST /api/events/fault`)**: Ingests automated telemetry fault payloads from SCADA/PLC systems or the dashboard trigger button.
- **Incident Formulation**: Automatically resolves machine specs, downtime rate (e.g. ₹5,000/hr), and spare part requirements (e.g. SKF 6205-2RS, qty 20) with zero manual data entry.
- **Auto-Recovery**: If `auto_start=True`, directly kicks off the recovery dialing workflow and persists the fault event linked to the generated `run_id`.

---

## Phase 3: Messy Supplier Conversations & Chaos Simulation

Real emergency procurement calls with suppliers are noisy, ambiguous, and subject to inventory surprises. Phase 3 equips RestartAI with defensible dialogue handling:
- **Extended Offer Statuses**: `CONFIRMED`, `TENTATIVE` ("maybe tomorrow, let me check"), `CONFLICTING`, `UNAVAILABLE`, `NO_ANSWER`, `CALLBACK_PROMISED`.
- **Verbatim Audio Transcripts & Ground-Truth Extraction**: Every supplier quote stores the full dialogue transcript and, for every extracted parameter (`quantity`, `unit_price`, `availability_hours`, `delivery_method`, `compatibility`), records the exact verbatim source quote and extraction confidence score.
- **Python-Driven Escalation & Retries**: Timeouts, no-answers, and unconfirmed tentative offers automatically trigger Python-controlled retries and escalation to subsequent suppliers in the sequence without relying on LLM heuristics.
- **Deterministic Chaos Scenarios**:
  - `standard`: The baseline golden scenario (clean C + D split recovery).
  - `supplier_unsure`: Supplier A returns tentative status (`TENTATIVE`, confidence 0.45); stock is excluded from the plan until confirmed.
  - `midcall_quantity_shift`: Supplier C discovers mid-call that units are allocated, revising stock from 16 to 8.
  - `no_answer`: Ringing times out; Python auto-retries with backoff and escalates to the next supplier.
  - `price_revised_upward`: Supplier B applies an emergency rush surcharge (+55%), altering economic ranking.
  - `callback_promised`: Counter closed for lunch, callback promised in 45m.
- **Interactive Transcript Viewer**: The dashboard UI allows operators to inspect audio transcripts, speaker turns, and highlighted evidence quotes with one click.


