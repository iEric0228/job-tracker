"""Streamlit dashboard. Run: uv run streamlit run dashboard/app.py

Ghosting is recomputed against the current date on every load — an employer
that finally replies flips back to active on the next sync + reload.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from jobtracker import states
from jobtracker.config import load_config
from jobtracker.models import STAGE_RANK, STAGES

sys.path.insert(0, str(Path(__file__).resolve().parent))
from theme import (  # noqa: E402
    REMOTE_COLORS,
    REMOTE_LABELS,
    REMOTE_ORDER,
    STAGE_LABELS,
    STATUS_COLORS,
    STATUS_LABELS,
    STATUS_LABELS_SHORT,
    STATUS_ORDER,
    apply_chart_style,
    fmt_date,
    now_utc,
    relative_days,
    week_start_labels,
)

st.set_page_config(page_title="Job application tracker", page_icon="📬", layout="wide")

cfg = load_config()
if not cfg.db_path.exists():
    st.title("📬 Job application pipeline")
    st.info("No database yet — run `uv run jobtracker-sync` first.")
    st.stop()

conn = sqlite3.connect(cfg.db_path)
apps = pd.read_sql_query("SELECT * FROM applications", conn)
events = pd.read_sql_query("SELECT * FROM events ORDER BY event_date", conn)
skipped = pd.read_sql_query("SELECT * FROM skipped", conn)
conn.close()

if apps.empty:
    st.title("📬 Job application pipeline")
    st.info("Database is empty — run `uv run jobtracker-sync` first.")
    st.stop()

now = now_utc()
events_by_app = dict(tuple(events.groupby("application_id")))
SCREEN_RANK = STAGE_RANK["recruiter_screen"]


def _naive(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


now_naive = _naive(pd.Timestamp(now))


def derive(row: pd.Series) -> pd.Series:
    group = events_by_app.get(row["id"])
    if group is None:
        first_seen = _naive(pd.Timestamp(row["first_seen"]))
        return pd.Series(
            {
                "display_status": "active",
                "responded": False,
                "first_response_days": None,
                "days_to_rejection": None,
                "days_since_activity": (now_naive - first_seen).days,
            }
        )
    pairs = list(zip(group["status_signal"], group["email_kind"], strict=True))
    touched = states.has_human_touch(pairs)
    dates = [pd.Timestamp(d) for d in group["event_date"]]
    last_activity = max(dates)
    status = states.display_status(
        row["current_status"], last_activity.to_pydatetime(), touched, now, cfg.ghost_days
    )
    first_seen = _naive(pd.Timestamp(row["first_seen"]))
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
                (_naive(min(response_dates)) - first_seen).days if response_dates else None
            ),
            "days_to_rejection": (
                (_naive(min(rejection_dates)) - first_seen).days if rejection_dates else None
            ),
            "days_since_activity": (now_naive - _naive(last_activity)).days,
        }
    )


apps = pd.concat([apps, apps.apply(derive, axis=1)], axis=1)

# ---------------------------------------------------------------- sidebar --

category_options = sorted(apps["category"].unique())
status_options = [s for s in STATUS_ORDER if s in apps["display_status"].unique()]
remote_options = [r for r in REMOTE_ORDER if r in apps["remote_type"].unique()]
min_date = pd.to_datetime(apps["first_seen"]).min().date()
max_date = pd.to_datetime(apps["first_seen"]).max().date()

DEFAULT_FILTERS = {
    "f_categories": category_options,
    "f_statuses": status_options,
    "f_remote": remote_options,
    "f_stage_min": "applied",
    "f_search": "",
    "f_date_range": (min_date, max_date),
    "f_follow_up_only": False,
    "f_stale_days": 7,
}
for key, value in DEFAULT_FILTERS.items():
    st.session_state.setdefault(key, value)


def apply_preset(**overrides) -> None:
    for key, value in DEFAULT_FILTERS.items():
        st.session_state[key] = overrides.get(key, value)


st.sidebar.header("📬 Job tracker")
st.sidebar.caption(f"{len(apps)} applications tracked")

st.sidebar.subheader("Quick views")
preset_cols = st.sidebar.columns(2)
if preset_cols[0].button("Active pipeline", width="stretch"):
    apply_preset(f_statuses=["active"])
if preset_cols[1].button("Interview+", width="stretch"):
    apply_preset(f_stage_min="interview")
if preset_cols[0].button("This week", width="stretch"):
    apply_preset(f_date_range=(max_date - pd.Timedelta(days=7), max_date))
if preset_cols[1].button("Needs follow-up", width="stretch"):
    apply_preset(f_statuses=["active"], f_follow_up_only=True)
if st.sidebar.button("Reset", width="stretch"):
    apply_preset()

st.sidebar.subheader("Filters")
st.sidebar.multiselect("Track", category_options, key="f_categories")
st.sidebar.multiselect(
    "Status", status_options, key="f_statuses", format_func=lambda s: STATUS_LABELS_SHORT.get(s, s)
)
st.sidebar.select_slider(
    "Furthest stage reached, at least",
    options=STAGES,
    key="f_stage_min",
    format_func=lambda s: STAGE_LABELS[s],
)
st.sidebar.multiselect(
    "Work setting", remote_options, key="f_remote", format_func=lambda r: REMOTE_LABELS.get(r, r)
)
st.sidebar.date_input("Applied between", key="f_date_range", min_value=min_date, max_value=max_date)
st.sidebar.text_input(
    "Search company, role, recruiter, or notes", key="f_search", placeholder="e.g. Amazon"
)
stale_cols = st.sidebar.columns([3, 2])
stale_cols[0].checkbox("Needs follow-up only", key="f_follow_up_only")
stale_cols[1].number_input(
    "Stale after (d)", min_value=1, max_value=60, key="f_stale_days", label_visibility="visible"
)

st.sidebar.divider()
st.sidebar.caption(
    "**Ghosted** — no employer email for "
    f"{cfg.ghost_days}+ days, not in a terminal state. "
    "**Response** — any human/scheduling email, or recruiter screen+."
)

stage_min_rank = STAGE_RANK[st.session_state["f_stage_min"]]
date_range = st.session_state["f_date_range"]
range_start, range_end = date_range if len(date_range) == 2 else (min_date, max_date)

filtered = apps[
    apps["category"].isin(st.session_state["f_categories"])
    & apps["display_status"].isin(st.session_state["f_statuses"])
    & apps["remote_type"].isin(st.session_state["f_remote"])
    & (apps["furthest_stage"].map(lambda s: STAGE_RANK.get(s, 1)) >= stage_min_rank)
    & pd.to_datetime(apps["first_seen"]).dt.date.between(range_start, range_end)
]
search = st.session_state["f_search"]
if search:
    needle = search.lower()
    haystack = (
        filtered[["company", "role_title", "recruiter_name", "notes", "location"]]
        .fillna("")
        .agg(" ".join, axis=1)
        .str.lower()
    )
    filtered = filtered[haystack.str.contains(needle)]

filtered = filtered.assign(
    needs_follow_up=(filtered["display_status"] == "active")
    & (filtered["days_since_activity"] >= st.session_state["f_stale_days"])
)
if st.session_state["f_follow_up_only"]:
    filtered = filtered[filtered["needs_follow_up"]]

st.title("Job application pipeline")

if filtered.empty:
    st.warning("No applications match the current filters.")
    st.stop()


def fmt_days(value: float) -> str:
    return "–" if pd.isna(value) else f"{value:.0f}d"


# ------------------------------------------------------------------- KPIs --

kpi_cols = st.columns(7)
kpi_cols[0].metric("Applications", len(filtered))
kpi_cols[1].metric(
    "Response rate",
    f"{filtered['responded'].mean() * 100:.0f}%",
    help="Any human-written or scheduling email, or any stage at recruiter screen or beyond.",
)
kpi_cols[2].metric(
    "Rejection rate",
    f"{(filtered['current_status'] == 'rejected').mean() * 100:.0f}%",
)
kpi_cols[3].metric(
    "Ghost rate",
    f"{filtered['display_status'].str.startswith('ghosted').mean() * 100:.0f}%",
    help=f"No employer email for {cfg.ghost_days}+ days and not in a terminal state.",
)
kpi_cols[4].metric(
    "Median days to response", fmt_days(filtered["first_response_days"].dropna().median())
)
kpi_cols[5].metric(
    "Median days to rejection", fmt_days(filtered["days_to_rejection"].dropna().median())
)
kpi_cols[6].metric(
    "Needs follow-up",
    int(filtered["needs_follow_up"].sum()),
    help=f"Active, with no employer email for {st.session_state['f_stale_days']}+ days.",
)

st.divider()

overview_tab, applications_tab, review_tab = st.tabs(
    ["Overview", f"Applications ({len(filtered)})", "Needs review"]
)

# --------------------------------------------------------------- overview --

with overview_tab:
    left, right = st.columns(2)

    with left:
        st.subheader("Pipeline funnel")
        st.caption("Furthest stage ever reached, so a late rejection still counts upstream.")
        ranks = filtered["furthest_stage"].map(lambda s: STAGE_RANK.get(s, 1))
        labels = [STAGE_LABELS[s] for s in STAGES]
        counts = [int((ranks >= STAGE_RANK[stage]).sum()) for stage in STAGES]
        funnel = go.Figure(
            go.Funnel(
                y=labels,
                x=counts,
                textinfo="value+percent initial",
                marker=dict(color="#4F46E5"),
                connector=dict(line=dict(color="#EEF0F6", width=1)),
            )
        )
        apply_chart_style(funnel)
        st.plotly_chart(funnel, width="stretch")

    with right:
        st.subheader("Current status")
        st.caption("Where each application stands right now.")
        status_counts = filtered["display_status"].value_counts().reindex(STATUS_ORDER).dropna()
        status_fig = go.Figure(
            go.Bar(
                y=[STATUS_LABELS[s] for s in status_counts.index],
                x=status_counts.values,
                orientation="h",
                marker_color=[STATUS_COLORS[s] for s in status_counts.index],
                text=status_counts.values,
                textposition="outside",
            )
        )
        status_fig.update_yaxes(autorange="reversed")
        apply_chart_style(status_fig)
        st.plotly_chart(status_fig, width="stretch")

    left2, right2 = st.columns(2)

    with left2:
        st.subheader("Applications per week")
        weekly = week_start_labels(filtered["first_seen"]).value_counts().sort_index()
        weekly_fig = px.bar(
            x=weekly.index, y=weekly.values, labels={"x": "week", "y": "applications"}
        )
        weekly_fig.update_traces(marker_color="#4F46E5")
        apply_chart_style(weekly_fig)
        st.plotly_chart(weekly_fig, width="stretch")

    with right2:
        st.subheader("By track")
        cat_fig = px.histogram(
            filtered,
            x="category",
            color="display_status",
            barmode="stack",
            labels={"category": "track", "display_status": "status"},
            color_discrete_map=STATUS_COLORS,
            category_orders={"display_status": STATUS_ORDER},
        )
        cat_fig.for_each_trace(lambda t: t.update(name=STATUS_LABELS.get(t.name, t.name)))
        apply_chart_style(cat_fig, showlegend=True)
        st.plotly_chart(cat_fig, width="stretch")

    left3, right3 = st.columns(2)

    with left3:
        st.subheader("Work setting")
        st.caption("Remote/hybrid/onsite, as stated in the emails — blank when never mentioned.")
        remote_counts = filtered["remote_type"].value_counts().reindex(REMOTE_ORDER).dropna()
        remote_fig = go.Figure(
            go.Pie(
                labels=[REMOTE_LABELS[r] for r in remote_counts.index],
                values=remote_counts.values,
                marker=dict(colors=[REMOTE_COLORS[r] for r in remote_counts.index]),
                hole=0.55,
                sort=False,
            )
        )
        apply_chart_style(remote_fig, showlegend=True)
        st.plotly_chart(remote_fig, width="stretch")

    with right3:
        st.subheader("Top locations")
        st.caption("Where extracted; excludes applications with no stated location.")
        locations = filtered.loc[filtered["location"] != "", "location"].value_counts().head(8)
        if locations.empty:
            st.info("No location data extracted yet.")
        else:
            loc_fig = go.Figure(
                go.Bar(
                    y=locations.index,
                    x=locations.values,
                    orientation="h",
                    marker_color="#4F46E5",
                    text=locations.values,
                    textposition="outside",
                )
            )
            loc_fig.update_yaxes(autorange="reversed")
            apply_chart_style(loc_fig)
            st.plotly_chart(loc_fig, width="stretch")

# ----------------------------------------------------------- applications --

with applications_tab:
    SORT_OPTIONS = {
        "Last activity": "last_activity",
        "First seen": "first_seen",
        "Company": "company",
        "Role": "role_title",
        "Status": "display_status",
        "Stage reached": "furthest_stage",
    }
    sort_cols = st.columns([2, 1, 3])
    sort_label = sort_cols[0].selectbox("Sort by", list(SORT_OPTIONS), index=0)
    ascending = sort_cols[1].selectbox("Order", ["Descending", "Ascending"], index=0) == "Ascending"
    sort_col = SORT_OPTIONS[sort_label]
    if sort_col == "furthest_stage":
        sort_key = filtered["furthest_stage"].map(lambda s: STAGE_RANK.get(s, 1))
    else:
        sort_key = filtered[sort_col]
    ordered = filtered.assign(_sort_key=sort_key).sort_values(
        "_sort_key", ascending=ascending, kind="stable"
    )

    table = ordered.copy()
    table["status"] = table["display_status"].map(STATUS_LABELS)
    table["stage reached"] = table["furthest_stage"].map(STAGE_LABELS)
    table["work setting"] = table["remote_type"].map(lambda r: REMOTE_LABELS.get(r, r))
    table["first seen"] = table["first_seen"].map(fmt_date)
    table["last activity"] = table["last_activity"].map(lambda d: relative_days(d, now))
    table["follow up"] = table["needs_follow_up"].map(lambda f: "⚠️" if f else "")
    table = table.rename(
        columns={
            "role_title": "role",
            "category": "track",
            "location": "location",
            "salary_range": "salary",
            "recruiter_name": "recruiter",
        }
    )
    table = table[
        [
            "follow up",
            "company",
            "role",
            "track",
            "status",
            "stage reached",
            "work setting",
            "location",
            "salary",
            "recruiter",
            "first seen",
            "last activity",
        ]
    ]
    st.download_button(
        "Download as CSV",
        table.to_csv(index=False),
        file_name="job_applications.csv",
        mime="text/csv",
    )
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "status": st.column_config.TextColumn(width="medium"),
            "follow up": st.column_config.TextColumn(width="small"),
        },
    )

    st.divider()
    st.subheader("Notes")
    st.caption(
        "The one manually-entered field in this app — everything else comes from your email."
    )
    notes_df = ordered.set_index("id")[["company", "role_title", "notes"]].rename(
        columns={"role_title": "role"}
    )
    edited_notes = st.data_editor(
        notes_df,
        width="stretch",
        hide_index=True,
        disabled=["company", "role"],
        column_config={"notes": st.column_config.TextColumn("notes", width="large")},
        key="notes_editor",
    )
    changed_ids = edited_notes.index[edited_notes["notes"] != notes_df["notes"]]
    if len(changed_ids) > 0:
        notes_conn = sqlite3.connect(cfg.db_path)
        for app_id in changed_ids:
            notes_conn.execute(
                "UPDATE applications SET notes = ? WHERE id = ?",
                (edited_notes.loc[app_id, "notes"], int(app_id)),
            )
        notes_conn.commit()
        notes_conn.close()
        st.rerun()

# ----------------------------------------------------------------- review --

with review_tab:
    review = events[events["needs_review"] == 1]
    if review.empty:
        st.success("Nothing flagged — every extraction met the confidence threshold.")
    else:
        st.caption(
            f"{len(review)} extraction(s) below the confidence threshold "
            f"({cfg.confidence_threshold:.0%}). Verify manually."
        )
        review = review.merge(
            apps[["id", "company", "role_title"]],
            left_on="application_id",
            right_on="id",
            suffixes=("", "_app"),
        )
        review_cols = [
            "event_date",
            "company",
            "role_title",
            "status_signal",
            "email_kind",
            "confidence",
            "reason",
            "raw_subject",
        ]
        review_display = review[review_cols].rename(
            columns={"role_title": "role", "status_signal": "signal", "email_kind": "kind"}
        )
        st.dataframe(
            review_display,
            width="stretch",
            hide_index=True,
            column_config={
                "confidence": st.column_config.ProgressColumn(
                    min_value=0, max_value=1, format="%.2f"
                ),
            },
        )

    failures = skipped[skipped["reason"] == "llm_unknown"]
    if not failures.empty:
        with st.expander(f"Classifier failures ({len(failures)})"):
            st.dataframe(
                failures[["event_date", "sender", "subject"]],
                width="stretch",
                hide_index=True,
            )
