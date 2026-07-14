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


def test_placeholder_role_treated_as_missing(conn, cfg):
    # Every schema field is required, so when an email names no role the LLM
    # emits prose like "Not specified in the email" — that must behave like
    # an empty role (attach by company, flagged), not create a junk-role app.
    applied = Extraction(
        relevance="my_application",
        company="Reynolds and Reynolds",
        role_title="DevOps Engineer",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.9,
    )
    rejected = Extraction(
        relevance="my_application",
        company="Reynolds and Reynolds",
        role_title="Not specified in the email",
        status_signal="rejected",
        email_kind="automated_notice",
        confidence=0.9,
    )
    app_1, _ = _resolve(conn, cfg, applied, make_email("m1", "t1"))
    app_2, review = _resolve(conn, cfg, rejected, make_email("m2", "t2"))
    assert app_1 == app_2
    assert review


def test_placeholder_company_treated_as_missing(conn, cfg):
    ext = Extraction(
        relevance="my_application",
        company="Unknown",
        role_title="N/A",
        status_signal="rejected",
        email_kind="automated_notice",
        confidence=0.8,
    )
    app_id, review = _resolve(conn, cfg, ext, make_email("m1", "t1"))
    row = conn.execute(
        "SELECT company, role_title FROM applications WHERE id = ?", (app_id,)
    ).fetchone()
    assert row["company"] == "(unknown)"
    assert row["role_title"] == "(unknown role)"
    assert review


def test_scrub_role_drops_process_phrases():
    # Scheduling emails often name no role, so the LLM lifts phrases like
    # "Virtual Interview" from the subject — that's a stage, not a job title.
    assert grouping.scrub_role("Virtual Interview") == ""
    assert grouping.scrub_role("Recruiter Screening Call") == ""
    assert grouping.scrub_role("Technical Assessment") == ""
    assert grouping.scrub_role("Not specified in the email") == ""
    assert grouping.scrub_role("Interview Coordinator") == "Interview Coordinator"
    assert grouping.scrub_role("DevOps Engineer") == "DevOps Engineer"


def test_process_phrase_role_attaches_by_company(conn, cfg):
    applied = Extraction(
        relevance="my_application",
        company="FDM Group",
        role_title="IT Operations Practice",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.9,
    )
    invite = Extraction(
        relevance="my_application",
        company="FDM Group",
        role_title="Virtual Interview",
        status_signal="interview",
        email_kind="scheduling",
        confidence=0.9,
    )
    app_1, _ = _resolve(conn, cfg, applied, make_email("m1", "t1"))
    app_2, review = _resolve(conn, cfg, invite, make_email("m2", "t2"))
    assert app_1 == app_2
    assert review


def test_role_equal_to_company_treated_as_missing(conn, cfg):
    # OpenEye interview mail comes from parent company Alarm.com; one bare
    # "OpenEye" subject made the LLM emit the company as the role. With the
    # alarm.com -> openeye alias both normalize identically, and a role that
    # just restates the company should not split the application.
    applied = Extraction(
        relevance="my_application",
        company="OpenEye",
        role_title="Service Reliability Engineer",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.9,
    )
    scheduling = Extraction(
        relevance="my_application",
        company="Alarm.com",
        role_title="OpenEye",
        status_signal="interview",
        email_kind="scheduling",
        confidence=0.8,
    )
    app_1, _ = _resolve(conn, cfg, applied, make_email("m1", "t1"))
    app_2, review = _resolve(conn, cfg, scheduling, make_email("m2", "t2"))
    assert app_1 == app_2
    assert review


def test_job_details_backfill_across_thread(conn, cfg):
    # The first email is often the terse auto-confirmation with none of the
    # job-detail fields; a later human reply on the same thread is where
    # location/salary/recruiter usually surface. Confirm they get merged in.
    applied = Extraction(
        relevance="my_application",
        company="Initech",
        role_title="Backend Engineer",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.9,
    )
    reply = Extraction(
        relevance="my_application",
        company="Initech",
        role_title="Backend Engineer",
        status_signal="other",
        email_kind="human_reply",
        confidence=0.9,
        location="Austin, TX",
        remote_type="hybrid",
        salary_range="$130k - $150k",
        recruiter_name="Jamie Lee",
    )
    app_1, _ = _resolve(conn, cfg, applied, make_email("m1", "t1"))
    app_2, _ = _resolve(conn, cfg, reply, make_email("m2", "t1"))
    assert app_1 == app_2
    row = conn.execute(
        "SELECT location, remote_type, salary_range, recruiter_name FROM applications WHERE id = ?",
        (app_1,),
    ).fetchone()
    assert row["location"] == "Austin, TX"
    assert row["remote_type"] == "hybrid"
    assert row["salary_range"] == "$130k - $150k"
    assert row["recruiter_name"] == "Jamie Lee"


def test_job_details_backfill_does_not_overwrite(conn, cfg):
    # A later email with vaguer info (or a placeholder the LLM invented)
    # should never clobber a value an earlier email already established.
    first = Extraction(
        relevance="my_application",
        company="Umbrella Corp",
        role_title="SRE",
        status_signal="applied",
        email_kind="auto_confirmation",
        confidence=0.9,
        location="Remote (US)",
        recruiter_name="Priya Nair",
    )
    second = Extraction(
        relevance="my_application",
        company="Umbrella Corp",
        role_title="SRE",
        status_signal="other",
        email_kind="human_reply",
        confidence=0.9,
        location="Not specified in the email",
        recruiter_name="Someone Else",
    )
    app_1, _ = _resolve(conn, cfg, first, make_email("m1", "t1"))
    app_2, _ = _resolve(conn, cfg, second, make_email("m2", "t1"))
    assert app_1 == app_2
    row = conn.execute(
        "SELECT location, recruiter_name FROM applications WHERE id = ?", (app_1,)
    ).fetchone()
    assert row["location"] == "Remote (US)"
    assert row["recruiter_name"] == "Priya Nair"


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
