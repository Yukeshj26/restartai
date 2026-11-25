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

