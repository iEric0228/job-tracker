from __future__ import annotations

from datetime import datetime, timezone

from conftest import load_fixture
from jobtracker import prefilter
from jobtracker.models import EmailMessage

NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


def make(sender: str, subject: str, body: str = "") -> EmailMessage:
    return EmailMessage(
        message_id="m-x",
        thread_id="t-x",
        sender=sender,
        subject=subject,
        date=NOW,
        body=body,
        snippet=body[:120],
    )


def test_sender_domain():
    assert prefilter.sender_domain("Comcast Careers <comcast@myworkday.com>") == "myworkday.com"
    assert prefilter.sender_domain("no-reply@hire.lever.co") == "hire.lever.co"


def test_ats_domain_is_candidate(cfg):
    assert prefilter.check(load_fixture("comcast_workday_applied.txt"), cfg) == "candidate"


def test_subdomain_of_ats_domain_is_candidate(cfg):
    assert prefilter.check(load_fixture("lever_screen.txt"), cfg) == "candidate"


def test_custom_domain_with_keyword_is_candidate(cfg):
    # Staples sends from its own domain; the subject keyword must catch it.
    assert prefilter.check(load_fixture("staples_rejection.txt"), cfg) == "candidate"


def test_all_job_fixtures_pass(cfg):
    for name in [
        "comcast_workday_applied.txt",
        "staples_rejection.txt",
        "greenhouse_applied.txt",
        "acme_human_reply.txt",
        "lever_screen.txt",
        "ashby_assessment.txt",
        "cold_outreach.txt",
    ]:
        assert prefilter.check(load_fixture(name), cfg) == "candidate", name


def test_job_alert_digest_is_noise(cfg):
    assert prefilter.check(load_fixture("linkedin_alert.txt"), cfg) == "noise_sender"


def test_noise_wins_over_keywords(cfg):
    # A digest stuffed with the word "application" must still be dropped.
    email = make("Indeed <alert@indeed.com>", "Your application keywords matched 12 new jobs")
    assert prefilter.check(email, cfg) == "noise_sender"


def test_digest_subject_is_noise(cfg):
    email = make("Tech News <news@randomtech.io>", "Your weekly digest of cloud news")
    assert prefilter.check(email, cfg) == "noise_subject"


def test_unrelated_email_no_match(cfg):
    email = make("A Friend <friend@example.com>", "Lunch tomorrow?", "Ramen at noon?")
    assert prefilter.check(email, cfg) == "no_match"
