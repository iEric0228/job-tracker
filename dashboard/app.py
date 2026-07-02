"""Streamlit dashboard. Run: uv run streamlit run dashboard/app.py

Ghosting is recomputed against the current date on every load — an employer
that finally replies flips back to active on the next sync + reload.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from jobtracker import states
from jobtracker.config import load_config
from jobtracker.models import STAGE_RANK, STAGES

st.set_page_config(page_title="Job application tracker", layout="wide")
st.title("Job application pipeline")

cfg = load_config()
if not cfg.db_path.exists():
    st.info("No database yet — run `uv run jobtracker-sync` first.")
    st.stop()

conn = sqlite3.connect(cfg.db_path)
apps = pd.read_sql_query("SELECT * FROM applications", conn)
events = pd.read_sql_query("SELECT * FROM events ORDER BY event_date", conn)
skipped = pd.read_sql_query("SELECT * FROM skipped", conn)
conn.close()

if apps.empty:
    st.info("Database is empty — run `uv run jobtracker-sync` first.")
    st.stop()

now = datetime.now(timezone.utc)
events_by_app = dict(tuple(events.groupby("application_id")))
SCREEN_RANK = STAGE_RANK["recruiter_screen"]


def derive(row: pd.Series) -> pd.Series:
    group = events_by_app.get(row["id"])
    if group is None:
        return pd.Series(
            {
                "display_status": "active",
                "responded": False,
                "first_response_days": None,
                "days_to_rejection": None,
            }
        )
    pairs = list(zip(group["status_signal"], group["email_kind"], strict=True))
    touched = states.has_human_touch(pairs)
    dates = [datetime.fromisoformat(d) for d in group["event_date"]]
    status = states.display_status(row["current_status"], max(dates), touched, now, cfg.ghost_days)
    first_seen = datetime.fromisoformat(row["first_seen"])
    response_dates = [
        d
        for d, (signal, kind) in zip(dates, pairs, strict=True)
        if kind in ("human_reply", "scheduling") or STAGE_RANK.get(signal, 0) >= SCREEN_RANK
    ]
    rejection_dates = [
        d for d, (signal, _) in zip(dates, pairs, strict=True) if signal == "rejected"
    ]
    return pd.Series(
        {
            "display_status": status,
            "responded": bool(response_dates),
            "first_response_days": (
                (min(response_dates) - first_seen).days if response_dates else None
            ),
            "days_to_rejection": (
                (min(rejection_dates) - first_seen).days if rejection_dates else None
            ),
        }
    )


apps = pd.concat([apps, apps.apply(derive, axis=1)], axis=1)


def fmt_days(value: float) -> str:
    return "–" if pd.isna(value) else f"{value:.0f}d"


cols = st.columns(6)
cols[0].metric("Applications", len(apps))
cols[1].metric("Response rate", f"{apps['responded'].mean() * 100:.0f}%")
cols[2].metric("Rejection rate", f"{(apps['current_status'] == 'rejected').mean() * 100:.0f}%")
cols[3].metric(
    "Ghost rate", f"{apps['display_status'].str.startswith('ghosted').mean() * 100:.0f}%"
)
cols[4].metric("Median days to response", fmt_days(apps["first_response_days"].dropna().median()))
cols[5].metric("Median days to rejection", fmt_days(apps["days_to_rejection"].dropna().median()))

left, right = st.columns(2)

with left:
    st.subheader("Pipeline funnel (furthest stage reached)")
    ranks = apps["furthest_stage"].map(lambda s: STAGE_RANK.get(s, 1))
    labels = ["Applied", "Recruiter screen", "Assessment", "Interview", "Onsite / final", "Offer"]
    counts = [int((ranks >= STAGE_RANK[stage]).sum()) for stage in STAGES]
    funnel = go.Figure(go.Funnel(y=labels, x=counts, textinfo="value+percent initial"))
    funnel.update_layout(margin=dict(t=10, b=10))
    st.plotly_chart(funnel, use_container_width=True)

with right:
    st.subheader("Current status")
    order = [
        "active",
        "offer",
        "rejected",
        "ghosted_in_process",
        "ghosted_after_applying",
        "withdrawn",
    ]
    status_counts = apps["display_status"].value_counts().reindex(order).dropna()
    status_fig = px.bar(
        x=status_counts.index,
        y=status_counts.values,
        labels={"x": "status", "y": "applications"},
    )
    status_fig.update_layout(margin=dict(t=10, b=10))
    st.plotly_chart(status_fig, use_container_width=True)

left2, right2 = st.columns(2)

with left2:
    st.subheader("Applications per week")
    first_seen = pd.to_datetime(apps["first_seen"], utc=True)
    weekly = first_seen.dt.to_period("W").dt.start_time.value_counts().sort_index()
    weekly_fig = px.bar(x=weekly.index, y=weekly.values, labels={"x": "week", "y": "applications"})
    weekly_fig.update_layout(margin=dict(t=10, b=10))
    st.plotly_chart(weekly_fig, use_container_width=True)

with right2:
    st.subheader("By category")
    cat_fig = px.histogram(
        apps,
        x="category",
        color="display_status",
        barmode="stack",
        labels={"category": "track"},
    )
    cat_fig.update_layout(margin=dict(t=10, b=10))
    st.plotly_chart(cat_fig, use_container_width=True)

st.subheader("Applications")
table = apps[
    [
        "company",
        "role_title",
        "category",
        "display_status",
        "furthest_stage",
        "first_seen",
        "last_activity",
    ]
].sort_values("last_activity", ascending=False)
st.dataframe(table, use_container_width=True, hide_index=True)

st.subheader("Needs review")
review = events[events["needs_review"] == 1]
if review.empty:
    st.caption("Nothing flagged.")
else:
    review = review.merge(
        apps[["id", "company", "role_title"]],
        left_on="application_id",
        right_on="id",
        suffixes=("", "_app"),
    )
    st.dataframe(
        review[
            [
                "event_date",
                "company",
                "role_title",
                "status_signal",
                "email_kind",
                "confidence",
                "reason",
                "raw_subject",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

failures = skipped[skipped["reason"] == "llm_unknown"]
if not failures.empty:
    with st.expander(f"Classifier failures ({len(failures)})"):
        st.dataframe(
            failures[["event_date", "sender", "subject"]],
            use_container_width=True,
            hide_index=True,
        )

st.caption(
    "Definitions — response: any human-written or scheduling email, or any stage at "
    "recruiter screen or beyond. Ghosted: no employer email for "
    f"{cfg.ghost_days}+ days and not in a terminal state; recomputed on every load, "
    "split by whether the process ever went beyond the automated confirmation. "
    "Funnel counts applications that ever reached each stage, so a rejection after "
    "an onsite still counts in the onsite bar."
)
