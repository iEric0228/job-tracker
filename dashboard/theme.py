"""Shared visual constants for the dashboard: status colors/labels and small
formatting helpers, kept separate from app.py so the page script stays a
readable top-to-bottom layout."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

# One color per display_status, reused across every chart and table so a
# color always means the same thing on this page.
STATUS_COLORS = {
    "active": "#4F46E5",
    "offer": "#0EA572",
    "rejected": "#E24957",
    "ghosted_in_process": "#E8992B",
    "ghosted_after_applying": "#C9CDD9",
    "withdrawn": "#8A8FA3",
}

STATUS_LABELS = {
    "active": "Active",
    "offer": "Offer",
    "rejected": "Rejected",
    "ghosted_in_process": "Ghosted (in process)",
    "ghosted_after_applying": "Ghosted (after applying)",
    "withdrawn": "Withdrawn",
}

STATUS_ORDER = list(STATUS_COLORS)

# Shorter variant for tight spaces (sidebar filter chips).
STATUS_LABELS_SHORT = {
    "active": "Active",
    "offer": "Offer",
    "rejected": "Rejected",
    "ghosted_in_process": "Ghosted (active)",
    "ghosted_after_applying": "Ghosted (early)",
    "withdrawn": "Withdrawn",
}

REMOTE_LABELS = {
    "remote": "Remote",
    "hybrid": "Hybrid",
    "onsite": "Onsite",
    "unknown": "Not specified",
}
REMOTE_ORDER = ["remote", "hybrid", "onsite", "unknown"]
REMOTE_COLORS = {
    "remote": "#4F46E5",
    "hybrid": "#7C83EB",
    "onsite": "#B7BCF2",
    "unknown": "#E8EAF6",
}

STAGE_LABELS = {
    "applied": "Applied",
    "recruiter_screen": "Recruiter screen",
    "assessment": "Assessment",
    "interview": "Interview",
    "onsite_final": "Onsite / final",
    "offer": "Offer",
}

CHART_FONT = dict(family="sans-serif", size=13, color="#1E2233")


def apply_chart_style(fig, *, showlegend: bool = False) -> None:
    """House style for every plotly figure: transparent chrome, shared font,
    tight margins so charts don't fight the surrounding cards for space."""
    fig.update_layout(
        margin=dict(t=8, b=8, l=8, r=8),
        font=CHART_FONT,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=showlegend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(gridcolor="#EEF0F6", zeroline=False)
    fig.update_yaxes(gridcolor="#EEF0F6", zeroline=False)


def relative_days(iso_value: str, now: datetime) -> str:
    """'3d ago' style label; falls back to the raw value if unparsable."""
    try:
        dt = datetime.fromisoformat(iso_value)
    except (TypeError, ValueError):
        return str(iso_value)
    delta = (now - dt).days
    if delta <= 0:
        return "today"
    if delta == 1:
        return "yesterday"
    return f"{delta}d ago"


def fmt_date(iso_value: str) -> str:
    try:
        return datetime.fromisoformat(iso_value).strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return str(iso_value)


def status_badge(status: str) -> str:
    """Small colored-dot + label markdown for the table's status column."""
    color = STATUS_COLORS.get(status, "#8A8FA3")
    label = STATUS_LABELS.get(status, status)
    return f":{_dot_color(color)}[●] {label}"


def _dot_color(hex_color: str) -> str:
    # st.markdown's colored-text syntax only accepts named colors; map our
    # palette to the closest named color so status dots render in color.
    mapping = {
        "#4F46E5": "violet",
        "#0EA572": "green",
        "#E24957": "red",
        "#E8992B": "orange",
        "#C9CDD9": "gray",
        "#8A8FA3": "gray",
    }
    return mapping.get(hex_color, "gray")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def week_start_labels(dates: pd.Series) -> pd.Series:
    return pd.to_datetime(dates, utc=True).dt.tz_localize(None).dt.to_period("W").dt.start_time
