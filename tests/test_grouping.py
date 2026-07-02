from __future__ import annotations

from datetime import datetime, timezone

from jobtracker import db, grouping
from jobtracker.models import EmailMessage, Extraction

ALIASES = {"aws": "amazon", "amazon web services": "amazon"}
NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


def make_email(message_id: str, thread_id: str) -> EmailMessage:
    return EmailMessage(
        message_id=message_id,
        thread_id=thread_id,
        sender="x <x@example.com>",
        subject="s",
        date=NOW,
    )


def test_normalize_company_aliases():
    assert grouping.normalize_company("Amazon Web Services", ALIASES) == "amazon"
    assert grouping.normalize_company("AWS", ALIASES) == "amazon"


def test_normalize_company_strips_suffixes():
    assert grouping.normalize_company("Comcast Careers", {}) == "comcast"
    assert grouping.normalize_company("Staples, Inc.", {}) == "staples"


def test_normalize_role_strips_req_codes():
    assert grouping.normalize_role("70140  DevOps Engineer I") == "devops engineer i"
    assert (
        grouping.normalize_role("R440149 Engineer 1, Software Dev & Eng (Open)")
        == "engineer 1 software dev eng"
    )


def test_roles_match_fuzzy():
    assert grouping.roles_match("cloud support engineer", "cloud support engineer i aws")
    assert not grouping.roles_match("backend engineer", "data analyst")
    assert not grouping.roles_match("", "backend engineer")


def _resolve(conn, cfg, ext, email):
    app_id, review = grouping.resolve_application(conn, ext, email, cfg)
    db.insert_event(conn, app_id, email, ext, review)
    db.refresh_application(conn, app_id)
    return app_id, review


def test_cross_thread_rejection_merges(conn, cfg):
    applied = Extraction(
        relevance="my_application",
        company="Comcast",
        role_title="Engineer 1, Software Dev & Eng",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.9,
    )
    rejected = Extraction(
        relevance="my_application",
        company="Comcast Careers",
        role_title="R440149 Engineer 1, Software Dev & Eng (Open)",
        status_signal="rejected",
        email_kind="automated_notice",
        confidence=0.9,
    )
    app_1, _ = _resolve(conn, cfg, applied, make_email("m1", "t1"))
    app_2, review = _resolve(conn, cfg, rejected, make_email("m2", "t2"))
    assert app_1 == app_2
    assert not review


def test_thread_continuity_beats_missing_company(conn, cfg):
    applied = Extraction(
        relevance="my_application",
        company="Acme",
        role_title="Cloud Support Engineer",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.9,
    )
    followup = Extraction(
        relevance="my_application",
        company="",
        role_title="",
        status_signal="other",
        email_kind="human_reply",
        confidence=0.7,
    )
    app_1, _ = _resolve(conn, cfg, applied, make_email("m1", "t1"))
    app_2, review = _resolve(conn, cfg, followup, make_email("m2", "t1"))
    assert app_1 == app_2
    assert not review


def test_roleless_rejection_attaches_when_unambiguous(conn, cfg):
    applied = Extraction(
        relevance="my_application",
        company="Staples",
        role_title="DevOps Engineer I",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.9,
    )
    rejected = Extraction(
        relevance="my_application",
        company="Staples",
        role_title="",
        status_signal="rejected",
        email_kind="automated_notice",
        confidence=0.8,
    )
    app_1, _ = _resolve(conn, cfg, applied, make_email("m1", "t1"))
    app_2, review = _resolve(conn, cfg, rejected, make_email("m2", "t2"))
    assert app_1 == app_2
    assert review  # attached by company alone — flag it


def test_different_roles_stay_separate(conn, cfg):
    a = Extraction(
        relevance="my_application",
        company="Globex",
        role_title="Platform Engineer",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.9,
    )
    b = Extraction(
        relevance="my_application",
        company="Globex",
        role_title="Data Engineer",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.9,
    )
    app_1, _ = _resolve(conn, cfg, a, make_email("m1", "t1"))
    app_2, _ = _resolve(conn, cfg, b, make_email("m2", "t2"))
    assert app_1 != app_2
