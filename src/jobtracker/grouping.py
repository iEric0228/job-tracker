"""Application identity: normalization plus fuzzy matching.

Thread continuity is checked first because it is cheap and exact, but
cross-thread merging by normalized (company, role) is the primary
mechanism — ATSes routinely send the rejection in a fresh thread with a
different subject, and role strings drift between emails.
"""

from __future__ import annotations

import re
import sqlite3
from difflib import SequenceMatcher

from jobtracker import db
from jobtracker.config import Config
from jobtracker.models import EmailMessage, Extraction

_COMPANY_SUFFIXES = {
    "inc",
    "llc",
    "corp",
    "corporation",
    "co",
    "ltd",
    "company",
    "careers",
    "talent",
    "recruiting",
    "team",
    "the",
}
_REQ_PREFIX = re.compile(r"^\s*\d{3,}\s*[-–—:.]*\s*")
_REQ_TOKEN = re.compile(r"\b(?:r|req|jr|job)[-#]?\d{3,}\b", re.IGNORECASE)
_PAREN_NOTE = re.compile(r"\((?:open|closed|remote|hybrid|on-?site|contract)\)", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_company(name: str, aliases: dict[str, str]) -> str:
    tokens = [t for t in _NON_ALNUM.sub(" ", name.lower()).split() if t not in _COMPANY_SUFFIXES]
    norm = " ".join(tokens)
    return aliases.get(norm, norm)


def normalize_role(title: str) -> str:
    t = _REQ_PREFIX.sub("", title.lower())
    t = _REQ_TOKEN.sub(" ", t)
    t = _PAREN_NOTE.sub(" ", t)
    return " ".join(_NON_ALNUM.sub(" ", t).split())


def roles_match(a: str, b: str) -> bool:
    """Exact, containment ('cloud support engineer' vs
    'cloud support engineer i aws'), or difflib ratio >= 0.8."""
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 8 and len(b) >= 8 and (a in b or b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def resolve_application(
    conn: sqlite3.Connection, ext: Extraction, email: EmailMessage, cfg: Config
) -> tuple[int, bool]:
    """Map one classified email to an application id, creating it if new.

    Returns (application_id, needs_review). needs_review is set when the
    attachment was a guess (e.g. a rejection that names no role).
    """
    by_thread = db.app_id_for_thread(conn, email.thread_id)
    if by_thread is not None:
        return by_thread, False

    first_seen = email.date.isoformat()
    company_norm = normalize_company(ext.company, cfg.company_aliases)
    role_norm = normalize_role(ext.role_title)

    if not company_norm:
        app_id = db.create_application(
            conn,
            company=ext.company or "(unknown)",
            company_norm="",
            role_title=ext.role_title or "(unknown role)",
            role_norm=role_norm,
            category=ext.category,
            first_seen=first_seen,
        )
        return app_id, True

    candidates = db.apps_for_company(conn, company_norm)

    if role_norm:
        for row in candidates:
            if roles_match(role_norm, row["role_norm"]):
                if row["category"] == "Other" and ext.category != "Other":
                    db.update_category(conn, row["id"], ext.category)
                return row["id"], False
        app_id = db.create_application(
            conn,
            company=ext.company,
            company_norm=company_norm,
            role_title=ext.role_title,
            role_norm=role_norm,
            category=ext.category,
            first_seen=first_seen,
        )
        return app_id, False

    # No role extracted — common for terse rejections. Attach if unambiguous,
    # otherwise guess the most recently active application and flag it.
    if len(candidates) == 1:
        return candidates[0]["id"], True
    if candidates:
        newest = max(candidates, key=lambda r: r["last_activity"])
        return newest["id"], True
    app_id = db.create_application(
        conn,
        company=ext.company,
        company_norm=company_norm,
        role_title="(unknown role)",
        role_norm="",
        category=ext.category,
        first_seen=first_seen,
    )
    return app_id, True
