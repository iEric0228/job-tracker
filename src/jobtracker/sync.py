"""One sync run: fetch, prefilter, classify, group, store.

Idempotent by construction: every message id lands in either events or
skipped, and both are checked before any work (or LLM call) is repeated.
Incremental via a date window with overlap; safe to re-run at any time.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from jobtracker import db, grouping, prefilter
from jobtracker.classifier import Classifier
from jobtracker.config import Config
from jobtracker.models import EmailMessage

LAST_SYNC_KEY = "last_sync_epoch"
DAY_SECONDS = 86400


class MailSource(Protocol):
    def list_message_ids(self, after_epoch: int) -> list[str]: ...
    def get_metadata(self, message_id: str) -> EmailMessage: ...
    def get_full(self, message_id: str) -> EmailMessage: ...


@dataclass
class SyncResult:
    scanned: int = 0
    already_processed: int = 0
    filtered_out: int = 0
    classified: int = 0
    events_added: int = 0
    skipped_by_llm: int = 0
    flagged_for_review: int = 0
    duration_s: float = 0.0

    def summary(self) -> str:
        return (
            f"scanned {self.scanned} messages "
            f"({self.already_processed} already processed, "
            f"{self.filtered_out} filtered out)\n"
            f"classified {self.classified}: {self.events_added} events added, "
            f"{self.skipped_by_llm} not my applications, "
            f"{self.flagged_for_review} flagged for review "
            f"(took {self.duration_s:.1f}s)"
        )


def run_sync(
    conn: sqlite3.Connection,
    cfg: Config,
    mail: MailSource,
    classifier: Classifier,
    *,
    now: datetime | None = None,
    override_start_epoch: int | None = None,
) -> SyncResult:
    t0 = time.monotonic()
    now = now or datetime.now(timezone.utc)
    run_started = int(now.timestamp())
    if override_start_epoch is not None:
        start = override_start_epoch
    else:
        last = db.get_state(conn, LAST_SYNC_KEY)
        if last:
            start = int(last) - cfg.overlap_days * DAY_SECONDS
        else:
            start = run_started - cfg.backfill_days * DAY_SECONDS

    result = SyncResult()
    for message_id in mail.list_message_ids(start):
        result.scanned += 1
        if db.is_processed(conn, message_id):
            result.already_processed += 1
            continue

        meta = mail.get_metadata(message_id)
        verdict = prefilter.check(meta, cfg)
        if verdict != prefilter.CANDIDATE:
            db.insert_skipped(conn, meta, verdict)
            result.filtered_out += 1
            conn.commit()
            continue

        email = mail.get_full(message_id)
        ext = classifier.classify(email)
        result.classified += 1
        if ext.relevance != "my_application":
            db.insert_skipped(conn, email, f"llm_{ext.relevance}")
            result.skipped_by_llm += 1
            conn.commit()
            continue

        if ext.category not in cfg.categories:
            ext.category = "Other"
        app_id, review_extra = grouping.resolve_application(conn, ext, email, cfg)
        needs_review = review_extra or ext.confidence < cfg.confidence_threshold
        if needs_review:
            result.flagged_for_review += 1
        db.insert_event(conn, app_id, email, ext, needs_review)
        db.refresh_application(conn, app_id)
        result.events_added += 1
        conn.commit()

    db.set_state(conn, LAST_SYNC_KEY, str(run_started))
    conn.commit()
    result.duration_s = time.monotonic() - t0
    return result
