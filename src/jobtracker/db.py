"""SQLite storage. Events are the source of truth; application rows carry
derived fields recomputed after each insert (single-writer tool, so safe)."""

from __future__ import annotations

import sqlite3
from datetime import timezone
from pathlib import Path

from jobtracker import states
from jobtracker.models import EmailMessage, Extraction

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    company_norm TEXT NOT NULL,
    role_title TEXT NOT NULL,
    role_norm TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Other',
    current_status TEXT NOT NULL DEFAULT 'applied',
    furthest_stage TEXT NOT NULL DEFAULT 'applied',
    first_seen TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    message_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL DEFAULT '',
    event_date TEXT NOT NULL,
    status_signal TEXT NOT NULL,
    email_kind TEXT NOT NULL,
    confidence REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    raw_subject TEXT NOT NULL DEFAULT '',
    sender TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    needs_review INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS skipped (
    message_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    sender TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    event_date TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_app ON events(application_id);
CREATE INDEX IF NOT EXISTS idx_events_thread ON events(thread_id);
CREATE INDEX IF NOT EXISTS idx_apps_company ON applications(company_norm);
"""


def _iso(email: EmailMessage) -> str:
    return email.date.astimezone(timezone.utc).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    if p.name != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def is_processed(conn: sqlite3.Connection, message_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM events WHERE message_id = ? "
        "UNION SELECT 1 FROM skipped WHERE message_id = ? LIMIT 1",
        (message_id, message_id),
    ).fetchone()
    return row is not None


def insert_skipped(conn: sqlite3.Connection, email: EmailMessage, reason: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO skipped (message_id, reason, sender, subject, event_date) "
        "VALUES (?, ?, ?, ?, ?)",
        (email.message_id, reason, email.sender, email.subject, _iso(email)),
    )


def app_id_for_thread(conn: sqlite3.Connection, thread_id: str) -> int | None:
    if not thread_id:
        return None
    row = conn.execute(
        "SELECT application_id FROM events WHERE thread_id = ? LIMIT 1", (thread_id,)
    ).fetchone()
    return row["application_id"] if row else None


def apps_for_company(conn: sqlite3.Connection, company_norm: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM applications WHERE company_norm = ?", (company_norm,)
    ).fetchall()


def create_application(
    conn: sqlite3.Connection,
    *,
    company: str,
    company_norm: str,
    role_title: str,
    role_norm: str,
    category: str,
    first_seen: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO applications "
        "(company, company_norm, role_title, role_norm, category, first_seen, last_activity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (company, company_norm, role_title, role_norm, category, first_seen, first_seen),
    )
    return int(cur.lastrowid or 0)


def update_category(conn: sqlite3.Connection, app_id: int, category: str) -> None:
    conn.execute("UPDATE applications SET category = ? WHERE id = ?", (category, app_id))


def insert_event(
    conn: sqlite3.Connection,
    app_id: int,
    email: EmailMessage,
    ext: Extraction,
    needs_review: bool,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO events "
        "(application_id, message_id, thread_id, event_date, status_signal, email_kind, "
        "confidence, reason, raw_subject, sender, snippet, needs_review) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            app_id,
            email.message_id,
            email.thread_id,
            _iso(email),
            ext.status_signal,
            ext.email_kind,
            ext.confidence,
            ext.reason,
            email.subject,
            email.sender,
            email.snippet or email.body[:200],
            int(needs_review),
        ),
    )


def refresh_application(conn: sqlite3.Connection, app_id: int) -> None:
    """Recompute derived fields (current_status, furthest_stage, activity dates)
    from the application's events. Ghosting is intentionally not derived here."""
    rows = conn.execute(
        "SELECT status_signal, event_date FROM events WHERE application_id = ? ORDER BY event_date",
        (app_id,),
    ).fetchall()
    if not rows:
        return
    signals = [r["status_signal"] for r in rows]
    conn.execute(
        "UPDATE applications SET current_status = ?, furthest_stage = ?, "
        "first_seen = ?, last_activity = ? WHERE id = ?",
        (
            states.current_status(signals),
            states.furthest_stage(signals),
            rows[0]["event_date"],
            rows[-1]["event_date"],
            app_id,
        ),
    )


def get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
