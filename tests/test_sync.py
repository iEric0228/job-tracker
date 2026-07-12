from __future__ import annotations

from datetime import datetime, timezone

from conftest import FakeClassifier, FakeGmail, all_fixtures
from jobtracker.models import Extraction
from jobtracker.sync import run_sync

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

EXTRACTIONS = {
    "m-comcast-1": Extraction(
        relevance="my_application",
        company="Comcast",
        role_title="Engineer 1, Software Dev & Eng",
        category="Backend",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.92,
        reason="application confirmation",
    ),
    "m-staples-1": Extraction(
        relevance="my_application",
        company="Staples",
        role_title="70140 DevOps Engineer I",
        category="DevOps/SRE",
        status_signal="rejected",
        email_kind="automated_notice",
        confidence=0.88,
        reason="position has been filled",
    ),
    "m-acme-1": Extraction(
        relevance="my_application",
        company="Acme Cloud",
        role_title="Cloud Support Engineer",
        category="Cloud Support",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.95,
        reason="application confirmation",
    ),
    "m-acme-2": Extraction(
        relevance="my_application",
        company="Acme Cloud",
        role_title="Cloud Support Engineer",
        category="Cloud Support",
        status_signal="other",
        email_kind="human_reply",
        confidence=0.80,
        reason="human status update, no stage change",
    ),
    "m-northwind-1": Extraction(
        relevance="my_application",
        company="Northwind",
        role_title="DevOps Engineer",
        category="DevOps/SRE",
        status_signal="recruiter_screen",
        email_kind="scheduling",
        confidence=0.90,
        reason="recruiter screen scheduling",
    ),
    "m-globex-1": Extraction(
        relevance="my_application",
        company="Globex",
        role_title="Platform Engineer",
        category="Platform/Infra",
        status_signal="assessment",
        email_kind="automated_notice",
        confidence=0.90,
        reason="online assessment invite",
    ),
    "m-lead-1": Extraction(
        relevance="inbound_lead",
        company="TechStaffPro",
        role_title="DevOps role",
        status_signal="other",
        email_kind="human_reply",
        confidence=0.85,
        reason="cold outreach for a job not applied to",
    ),
}


def make_world() -> tuple[FakeGmail, FakeClassifier]:
    return FakeGmail(all_fixtures()), FakeClassifier(EXTRACTIONS)


def test_full_sync(conn, cfg):
    mail, clf = make_world()
    result = run_sync(conn, cfg, mail, clf, now=NOW)

    assert result.scanned == 8
    assert result.filtered_out == 1  # linkedin digest
    assert result.classified == 7
    assert result.events_added == 6
    assert result.skipped_by_llm == 1  # cold outreach -> inbound_lead

    apps = conn.execute("SELECT * FROM applications").fetchall()
    assert len(apps) == 5

    # The digest was dropped by the prefilter, before any LLM call.
    assert "m-noise-1" not in clf.calls
    skipped = {
        r["message_id"]: r["reason"] for r in conn.execute("SELECT * FROM skipped").fetchall()
    }
    assert skipped["m-noise-1"] == "noise_sender"
    assert skipped["m-lead-1"] == "llm_inbound_lead"


def test_rejection_keeps_furthest_stage(conn, cfg):
    mail, clf = make_world()
    run_sync(conn, cfg, mail, clf, now=NOW)
    row = conn.execute("SELECT * FROM applications WHERE company_norm = 'staples'").fetchone()
    assert row["current_status"] == "rejected"
    assert row["furthest_stage"] == "applied"


def test_thread_grouping_collects_both_acme_emails(conn, cfg):
    mail, clf = make_world()
    run_sync(conn, cfg, mail, clf, now=NOW)
    row = conn.execute("SELECT * FROM applications WHERE company_norm = 'acme cloud'").fetchone()
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE application_id = ?", (row["id"],)
    ).fetchone()["n"]
    assert count == 2
    assert row["current_status"] == "applied"  # human reply advances no stage
    assert row["first_seen"].startswith("2026-06-20")


def test_summary_reports_duration(conn, cfg):
    mail, clf = make_world()
    result = run_sync(conn, cfg, mail, clf, now=NOW)
    assert result.duration_s >= 0
    assert "(took " in result.summary()


def test_rerun_is_idempotent(conn, cfg):
    mail, clf = make_world()
    first = run_sync(conn, cfg, mail, clf, now=NOW)
    calls_after_first = len(clf.calls)

    # Normal incremental rerun: the window starts at last_sync - overlap,
    # so old mail is not even listed again.
    second = run_sync(conn, cfg, mail, clf, now=NOW)
    assert second.scanned == 0

    # Forced full rescan: everything is listed, nothing is reprocessed.
    third = run_sync(conn, cfg, mail, clf, now=NOW, override_start_epoch=0)
    assert third.scanned == 8
    assert third.already_processed == 8
    assert third.events_added == 0
    assert len(clf.calls) == calls_after_first  # no repeated LLM spend

    events = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    assert events == first.events_added == 6
