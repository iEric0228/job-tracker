from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jobtracker import states

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


def test_furthest_stage_survives_rejection():
    assert states.furthest_stage(["applied", "assessment", "rejected"]) == "assessment"


def test_furthest_stage_defaults_to_applied():
    # A lone rejection still implies an application existed.
    assert states.furthest_stage(["rejected"]) == "applied"
    assert states.furthest_stage([]) == "applied"


def test_current_status_terminal_wins():
    assert states.current_status(["applied", "assessment", "rejected"]) == "rejected"


def test_current_status_active_is_furthest():
    assert states.current_status(["applied", "recruiter_screen"]) == "recruiter_screen"


def test_human_touch():
    assert not states.has_human_touch([("applied", "auto_confirmation")])
    assert states.has_human_touch([("applied", "auto_confirmation"), ("other", "human_reply")])
    # An automated OA invite is still a real process step.
    assert states.has_human_touch([("assessment", "automated_notice")])


def test_terminal_status_never_ghosts():
    assert states.display_status("rejected", days_ago(90), True, NOW, 21) == "rejected"


def test_ghosted_after_applying():
    assert (
        states.display_status("applied", days_ago(25), False, NOW, 21) == "ghosted_after_applying"
    )


def test_ghosted_in_process():
    assert (
        states.display_status("recruiter_screen", days_ago(25), True, NOW, 21)
        == "ghosted_in_process"
    )


def test_recent_activity_is_active():
    assert states.display_status("applied", days_ago(3), False, NOW, 21) == "active"


def test_ghost_flips_back_when_they_reply():
    # Same application: ghosted at 25 days of silence, active again once a
    # fresh employer email lands. Nothing is stored, so nothing to un-store.
    assert states.display_status("applied", days_ago(25), False, NOW, 21).startswith("ghosted")
    assert states.display_status("applied", days_ago(1), False, NOW, 21) == "active"
