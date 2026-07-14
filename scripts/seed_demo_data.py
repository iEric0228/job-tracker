"""Populate data/tracker.db with realistic-looking sample data, purely so the
dashboard can be previewed/designed without a real Gmail sync. Not part of
the shipped product — safe to delete.
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobtracker import db as dbmod

random.seed(7)

DB_PATH = Path("data/tracker.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    # The real synced database lives here too; never destroy it silently.
    if "--overwrite" not in sys.argv:
        sys.exit(f"{DB_PATH} already exists (possibly real sync data). Re-run with --overwrite.")
    DB_PATH.unlink()

COMPANIES = [
    ("Amazon", "Cloud Support"),
    ("Datadog", "DevOps/SRE"),
    ("Stripe", "Backend"),
    ("Cloudflare", "Platform/Infra"),
    ("Snowflake", "Data"),
    ("HashiCorp", "DevOps/SRE"),
    ("Notion", "Backend"),
    ("Figma", "Backend"),
    ("Rippling", "Platform/Infra"),
    ("Anthropic", "Backend"),
    ("Vercel", "Platform/Infra"),
    ("Databricks", "Data"),
    ("MongoDB", "Data"),
    ("PagerDuty", "DevOps/SRE"),
    ("Ramp", "Backend"),
    ("Airtable", "Other"),
    ("Retool", "Backend"),
    ("Linear", "Backend"),
    ("Brex", "Platform/Infra"),
    ("Okta", "Cloud Support"),
    ("GitLab", "DevOps/SRE"),
    ("CrowdStrike", "Cloud Support"),
    ("Twilio", "Backend"),
    ("Confluent", "Data"),
    ("Elastic", "Data"),
    ("Grafana Labs", "DevOps/SRE"),
    ("Docker", "Platform/Infra"),
    ("Segment", "Backend"),
    ("Plaid", "Backend"),
    ("Chime", "Other"),
]

ROLES = [
    "Software Engineer II",
    "Senior Backend Engineer",
    "Site Reliability Engineer",
    "Platform Engineer",
    "Cloud Support Engineer",
    "DevOps Engineer",
    "Data Engineer",
    "Infrastructure Engineer",
]

LOCATIONS = ["Remote (US)", "New York, NY", "San Francisco, CA", "Austin, TX", "Seattle, WA", ""]
REMOTE_TYPES = ["remote", "hybrid", "onsite", "unknown"]
SALARY_RANGES = ["$120k - $150k", "$135k - $160k", "$95/hr", "", "", ""]
RECRUITERS = ["Jamie Lee", "Priya Nair", "Marcus Chen", "Sofia Alvarez", "", "", ""]

STAGE_ORDER = ["applied", "recruiter_screen", "assessment", "interview", "onsite_final", "offer"]

conn = dbmod.connect(DB_PATH)
now = datetime.now(timezone.utc)


def make_app(i: int, company: str, category: str) -> None:
    role = random.choice(ROLES)
    days_ago = random.randint(2, 170)
    first_seen = now - timedelta(days=days_ago)

    outcomes = [
        "ghost_early",
        "ghost_mid",
        "rejected_early",
        "rejected_late",
        "offer",
        "active",
        "withdrawn",
    ]
    outcome = random.choices(outcomes, weights=[22, 12, 28, 10, 6, 17, 5])[0]

    reached = 0
    if outcome in ("ghost_mid", "rejected_late", "offer"):
        reached = random.randint(1, 4)
    elif outcome == "active":
        reached = random.randint(0, 3)

    app_id = dbmod.create_application(
        conn,
        company=company,
        company_norm=company.lower(),
        role_title=role,
        role_norm=role.lower(),
        category=category,
        first_seen=first_seen.isoformat(),
        location=random.choice(LOCATIONS),
        remote_type=random.choice(REMOTE_TYPES),
        salary_range=random.choice(SALARY_RANGES),
        recruiter_name=random.choice(RECRUITERS),
    )

    t = first_seen
    events: list[tuple[str, str, datetime]] = [("applied", "auto_confirmation", first_seen)]
    for r in range(1, reached + 1):
        t = t + timedelta(days=random.randint(2, 12))
        kind = "human_reply" if r >= 1 and random.random() < 0.6 else "automated_notice"
        if STAGE_ORDER[r] == "recruiter_screen" and random.random() < 0.5:
            kind = "scheduling"
        events.append((STAGE_ORDER[r], kind, t))

    final_gap = random.randint(3, 15)
    if outcome in ("rejected_early", "rejected_late"):
        t = t + timedelta(days=final_gap)
        events.append(("rejected", random.choice(["automated_notice", "human_reply"]), t))
    elif outcome == "offer":
        t = t + timedelta(days=final_gap)
        events.append(("offer", "human_reply", t))
    elif outcome == "withdrawn":
        t = t + timedelta(days=final_gap)
        events.append(("withdrawn", "human_reply", t))
    # ghost_early / ghost_mid / active: no terminal event, last event stands.

    for idx, (signal, kind, ts) in enumerate(events):
        needs_review = 1 if random.random() < 0.04 else 0
        conn.execute(
            "INSERT INTO events (application_id, message_id, thread_id, event_date, status_signal, "
            "email_kind, confidence, reason, raw_subject, sender, snippet, needs_review) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                app_id,
                f"msg-{i}-{idx}",
                f"thread-{i}",
                ts.astimezone(timezone.utc).isoformat(),
                signal,
                kind,
                round(random.uniform(0.55, 0.99), 2),
                "demo data" if not needs_review else "ambiguous role reference in thread",
                f"Re: your application to {company}",
                f"careers@{company.lower().replace(' ', '')}.com",
                f"Thanks for applying to {company} — {role}.",
                needs_review,
            ),
        )
    dbmod.refresh_application(conn, app_id)


for i, (company, category) in enumerate(COMPANIES):
    make_app(i, company, category)

# A couple of classifier failures for the "Classifier failures" expander.
for i, (sender, subject) in enumerate(
    [
        ("noreply@greenhouse.io", "Your interview scheduling link"),
        ("jobs-noreply@linkedin.com", "Update on your application"),
    ]
):
    conn.execute(
        "INSERT INTO skipped (message_id, reason, sender, subject, event_date) "
        "VALUES (?, ?, ?, ?, ?)",
        (f"skip-{i}", "llm_unknown", sender, subject, (now - timedelta(days=i + 1)).isoformat()),
    )

conn.commit()
conn.close()
print(f"Seeded {len(COMPANIES)} applications into {DB_PATH}")
