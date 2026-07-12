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


def test_allowed_sender_beats_noise_list(cfg):
    # jobs-noreply@linkedin.com carries Easy Apply confirmations and
    # rejections; it must get through even though linkedin.com is noise.
    email = make(
        "LinkedIn <jobs-noreply@linkedin.com>",
        "Your application to DevOps Engineer at TCI Technology Consulting Inc",
    )
    assert prefilter.check(email, cfg) == "candidate"


def test_other_linkedin_mail_is_still_noise(cfg):
    email = make("LinkedIn <notifications-noreply@linkedin.com>", "You appeared in 8 searches")
    assert prefilter.check(email, cfg) == "noise_sender"


def test_resume_submission_subject_is_candidate(cfg):
    email = make(
        '"Reyrey.com" <noreply@reyrey.com>',
        "Reynolds and Reynolds: Thank You For Your Resume Submission",
    )
    assert prefilter.check(email, cfg) == "candidate"


def test_greenhouse_promo_is_noise(cfg):
    # Greenhouse's own marketing comes from an ATS domain and would otherwise
    # sail through the domain rule straight into the classifier.
    email = make(
        "Greenhouse <no-reply@greenhouse.io>",
        "Show recruiters you're really interested with Dream Job",
    )
    assert prefilter.check(email, cfg) == "noise_subject"


def test_adp_ats_domain_is_candidate(cfg):
    email = make(
        '"World Wide Technology Holding, LLC Career Opportunities" <jobs@adp.com>',
        "Additional Information Needed - World Wide Technology Holding, LLC",
    )
    assert prefilter.check(email, cfg) == "candidate"


def test_noise_subject_beats_allowed_sender(cfg):
    # jobs-noreply@linkedin.com also blasts job alerts; the allow override
    # rescues the sender from the noise_senders list, not from subject rules.
    email = make(
        "LinkedIn <jobs-noreply@linkedin.com>",
        "New jobs similar to DevOps Engineer at Axway",
    )
    assert prefilter.check(email, cfg) == "noise_subject"


def test_apply_now_blast_from_allowed_sender_is_noise(cfg):
    email = make(
        "LinkedIn <jobs-noreply@linkedin.com>",
        "Eric, apply now to 'Platform Engineer Intern at Veryable'",
    )
    assert prefilter.check(email, cfg) == "noise_subject"


def test_job_board_alert_sender_is_noise(cfg):
    email = make(
        "Jobright Job Alert <noreply@jobright.ai>",
        "Yahoo is hiring for a role like you — 87% match",
    )
    assert prefilter.check(email, cfg) == "noise_sender"


def test_verification_code_from_ats_domain_is_noise(cfg):
    # ADP is a real ATS domain, but its security mail must not reach the LLM.
    email = make(
        "<SecurityServices_NoReply@adp.com>",
        "Here's your verification code from ADP",
    )
    assert prefilter.check(email, cfg) == "noise_subject"
