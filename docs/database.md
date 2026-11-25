# RestartAI Database Schema & Persistence

RestartAI utilizes an embedded SQLite database configured in Write-Ahead Logging (`WAL`) mode for robust, concurrent read-write persistence across server restarts.

## Storage Location

- Default path: `data/restartai.db` (configurable via `DB_PATH` environment variable).
- Ignored in `.gitignore` to prevent committing live run data.

---

## Entity Relationship Diagram

```mermaid
erDiagram
    RUNS ||--o{ OFFERS : contains
    RUNS ||--o{ PLANS : generates
    RUNS ||--o{ CALLS : links
    RUNS ||--o{ AUDIT_LOGS : tracks
    RUNS ||--o| IDEMPOTENCY : keyed_by

    RUNS {
        string run_id PK
        string stage
        string mode
        string request_json
        string maintenance_json
        int next_supplier_index
        int approved
        string call_failures_json
        string created_at
        string updated_at
    }

    OFFERS {
        int id PK
        string run_id FK
        string supplier
        string phone
        int quantity_available
        float unit_price
        string currency
        float availability_hours
        string delivery_method
        int compatible
        float compatibility_confidence
        int confirmed
        string status
        string source
        string call_id
        string notes
        string created_at
    }

    PLANS {
        int id PK
        string run_id FK
        int rank
        int is_recommended
        string plan_json
        float total_exposure
        float recovery_time_hours
        int feasible
        string created_at
    }

    CALLS {
        string call_id PK
        string run_id
        string supplier
        string phone
        string status
        string record_json
        string created_at
        string updated_at
    }

    AUDIT_LOGS {
        int id PK
        string run_id
        string event_type
        string message
        string payload_json
        string created_at
    }

    IDEMPOTENCY {
        string key PK
        string run_id
        string created_at
    }
```
