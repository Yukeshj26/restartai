"""Unified database connection manager and schema initialization.

Supports both SQLite (default embedded) and PostgreSQL (via DATABASE_URL).
"""

import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Generator, Any, Optional
from .config import settings

logger = logging.getLogger("restartai.db")

SCHEMA_SQL_SQLITE = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    mode TEXT NOT NULL,
    request_json TEXT NOT NULL,
    maintenance_json TEXT NOT NULL,
    next_supplier_index INTEGER NOT NULL DEFAULT 0,
    approved INTEGER NOT NULL DEFAULT 0,
    call_failures_json TEXT DEFAULT '[]',
    decisions_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    supplier TEXT NOT NULL,
    phone TEXT NOT NULL,
    quantity_available INTEGER NOT NULL DEFAULT 0,
    unit_price REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'INR',
    availability_hours REAL NOT NULL DEFAULT 999,
    delivery_method TEXT NOT NULL DEFAULT 'unknown',
    compatible INTEGER NOT NULL DEFAULT 0,
    compatibility_confidence REAL NOT NULL DEFAULT 0,
    confirmed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'UNAVAILABLE',
    source TEXT NOT NULL DEFAULT 'demo',
    call_id TEXT,
    notes TEXT DEFAULT '',
    transcript TEXT DEFAULT '',
    extracted_fields_json TEXT DEFAULT '{}',
    retry_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    is_recommended INTEGER NOT NULL DEFAULT 0,
    plan_json TEXT NOT NULL,
    total_exposure REAL NOT NULL,
    recovery_time_hours REAL NOT NULL,
    feasible INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    run_id TEXT,
    supplier TEXT NOT NULL,
    phone TEXT NOT NULL,
    status TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fault_events (
    event_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    machine_name TEXT NOT NULL,
    sensor_id TEXT NOT NULL,
    fault_code TEXT NOT NULL,
    severity TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    run_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_offers_run_id ON offers(run_id);
CREATE INDEX IF NOT EXISTS idx_plans_run_id ON plans(run_id);
CREATE INDEX IF NOT EXISTS idx_calls_run_id ON calls(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_run_id ON audit_logs(run_id);
CREATE INDEX IF NOT EXISTS idx_faults_created ON fault_events(created_at DESC);
"""

SCHEMA_SQL_POSTGRES = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    mode TEXT NOT NULL,
    request_json TEXT NOT NULL,
    maintenance_json TEXT NOT NULL,
    next_supplier_index INTEGER NOT NULL DEFAULT 0,
    approved INTEGER NOT NULL DEFAULT 0,
    call_failures_json TEXT DEFAULT '[]',
    decisions_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    supplier TEXT NOT NULL,
    phone TEXT NOT NULL,
    quantity_available INTEGER NOT NULL DEFAULT 0,
    unit_price REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'INR',
    availability_hours REAL NOT NULL DEFAULT 999,
    delivery_method TEXT NOT NULL DEFAULT 'unknown',
    compatible INTEGER NOT NULL DEFAULT 0,
    compatibility_confidence REAL NOT NULL DEFAULT 0,
    confirmed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'UNAVAILABLE',
    source TEXT NOT NULL DEFAULT 'demo',
    call_id TEXT,
    notes TEXT DEFAULT '',
    transcript TEXT DEFAULT '',
    extracted_fields_json TEXT DEFAULT '{}',
    retry_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    is_recommended INTEGER NOT NULL DEFAULT 0,
    plan_json TEXT NOT NULL,
    total_exposure REAL NOT NULL,
    recovery_time_hours REAL NOT NULL,
    feasible INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    run_id TEXT,
    supplier TEXT NOT NULL,
    phone TEXT NOT NULL,
    status TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    run_id TEXT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fault_events (
    event_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    machine_name TEXT NOT NULL,
    sensor_id TEXT NOT NULL,
    fault_code TEXT NOT NULL,
    severity TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    run_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_offers_run_id ON offers(run_id);
CREATE INDEX IF NOT EXISTS idx_plans_run_id ON plans(run_id);
CREATE INDEX IF NOT EXISTS idx_calls_run_id ON calls(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_run_id ON audit_logs(run_id);
CREATE INDEX IF NOT EXISTS idx_faults_created ON fault_events(created_at DESC);
"""


def is_postgres_url(url: Optional[str]) -> bool:
    if not url:
        return False
    u = url.strip().lower()
    return u.startswith("postgresql://") or u.startswith("postgres://")


class DatabaseConnection:
    """Unified wrapper around SQLite or PostgreSQL connections."""

    def __init__(self, raw_conn: Any, is_postgres: bool = False):
        self._conn = raw_conn
        self.is_postgres = is_postgres

    def execute(self, query: str, params: Any = None):
        if self.is_postgres:
            pg_query = query.replace("?", "%s")
            cur = self._conn.cursor()
            cur.execute(pg_query, params or ())
            return cur
        else:
            return self._conn.execute(query, params or ())

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _migrate_sqlite_db(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(offers)")
    columns = {row[1] for row in cursor.fetchall()}
    if "transcript" not in columns:
        cursor.execute("ALTER TABLE offers ADD COLUMN transcript TEXT DEFAULT ''")
    if "extracted_fields_json" not in columns:
        cursor.execute(
            "ALTER TABLE offers ADD COLUMN extracted_fields_json TEXT DEFAULT '{}'"
        )
    if "retry_count" not in columns:
        cursor.execute("ALTER TABLE offers ADD COLUMN retry_count INTEGER DEFAULT 0")

    cursor.execute("PRAGMA table_info(runs)")
    run_columns = {row[1] for row in cursor.fetchall()}
    if "decisions_json" not in run_columns:
        cursor.execute("ALTER TABLE runs ADD COLUMN decisions_json TEXT DEFAULT '{}'")


def init_db(db_path: Optional[Path] = None, database_url: Optional[str] = None) -> None:
    """Initialize database tables and indexes (PostgreSQL or SQLite)."""
    db_url = database_url or settings.database_url
    if is_postgres_url(db_url):
        try:
            import psycopg

            with psycopg.connect(db_url, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(SCHEMA_SQL_POSTGRES)
            logger.info("PostgreSQL database initialized at %s", db_url.split("@")[-1])
            return
        except Exception as exc:
            logger.warning(
                "PostgreSQL init failed (%s), falling back to SQLite: %s",
                db_url.split("@")[-1] if db_url else "",
                exc,
            )

    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SCHEMA_SQL_SQLITE)
        _migrate_sqlite_db(conn)
        conn.commit()
    logger.info("SQLite database initialized at %s", path)


@contextmanager
def get_db(
    db_path: Optional[Path] = None, database_url: Optional[str] = None
) -> Generator[DatabaseConnection, None, None]:
    """Yields a unified DatabaseConnection configured for dict rows and foreign keys."""
    db_url = database_url or settings.database_url
    if is_postgres_url(db_url):
        try:
            import psycopg
            from psycopg.rows import dict_row

            conn = psycopg.connect(db_url, row_factory=dict_row)
            wrapper = DatabaseConnection(conn, is_postgres=True)
            try:
                yield wrapper
                wrapper.commit()
            except Exception:
                wrapper.rollback()
                raise
            finally:
                wrapper.close()
            return
        except Exception as exc:
            logger.warning(
                "PostgreSQL connection failed, falling back to SQLite: %s", exc
            )

    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_conn = sqlite3.connect(path, timeout=15.0)
    raw_conn.row_factory = sqlite3.Row
    raw_conn.execute("PRAGMA foreign_keys = ON;")
    wrapper = DatabaseConnection(raw_conn, is_postgres=False)
    try:
        yield wrapper
        wrapper.commit()
    except Exception:
        wrapper.rollback()
        raise
    finally:
        wrapper.close()
