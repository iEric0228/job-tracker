"""Stage and status derivation.

Ghosting is derived at read time against the current date — never stored.
If an employer finally replies, the next dashboard load flips the
application back to active with no state to clean up.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from jobtracker.models import STAGE_RANK, TERMINAL_SIGNALS


def furthest_stage(signals: Iterable[str]) -> str:
    """Highest funnel stage ever reached. A rejection after an onsite still
    counts as having reached the onsite — this is what the funnel plots."""
    best, best_rank = "applied", 0
    for signal in signals:
        rank = STAGE_RANK.get(signal, 0)
        if rank > best_rank:
            best, best_rank = signal, rank
    return best


def current_status(signals: Sequence[str]) -> str:
    """Latest terminal signal wins; otherwise the furthest stage reached.
    Expects signals in event-date order."""
    last_terminal = None
    for signal in signals:
        if signal in TERMINAL_SIGNALS:
            last_terminal = signal
    return last_terminal if last_terminal else furthest_stage(signals)


def has_human_touch(events: Iterable[tuple[str, str]]) -> bool:
    """True if the process ever went beyond automated confirmations.

    events are (status_signal, email_kind) pairs. Counts as touched: any
    human-written or scheduling email, or any stage at recruiter_screen or
    beyond (an automated OA invite is still a real process step).
    """
    screen_rank = STAGE_RANK["recruiter_screen"]
    for signal, kind in events:
        if kind in ("human_reply", "scheduling"):
            return True
        if STAGE_RANK.get(signal, 0) >= screen_rank:
            return True
    return False


def display_status(
    current: str, last_event: datetime, touched: bool, now: datetime, ghost_days: int
) -> str:
    """Status for display, with ghosting computed on the fly.

    The ghost clock runs from the last employer email (or the application
    confirmation, if that is all there ever was — same event either way).
    """
    if current in TERMINAL_SIGNALS:
        return current
    if (now - last_event).days >= ghost_days:
        return "ghosted_in_process" if touched else "ghosted_after_applying"
    return "active"
