"""Streamlit dashboard — reads the orchestrator SQLite DB read-only and renders
funnel metrics, a needs-attention panel, the pipeline table, and category breakdown.

Manual refresh by default (🔄 button / browser); set DASHBOARD_REFRESH_SECONDS
to enable an auto-refresh meta tag (no heavy deps).
"""
import json
import os
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

# Make the `app` package importable so the dashboard can call Devin's own API
# for the native-analytics panel. The image lays this file at /app/dashboard/app.py,
# so its grandparent (/app) is the package root. Guarded so the dashboard still
# renders if the import/env is unavailable.
import sys  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from app import devin_client  # noqa: E402
    _DEVIN_CLIENT = True
except Exception:  # noqa: BLE001
    _DEVIN_CLIENT = False

DB_PATH = os.getenv("DB_PATH", "/data/orchestrator.db")
# Auto-refresh interval in seconds. 0 (default) = OFF: no page reload, refresh
# manually with the browser or the 🔄 button (best for screen recording).
# Set DASHBOARD_REFRESH_SECONDS=15 (or any value) to re-enable auto-refresh.
REFRESH_SECONDS = int(os.getenv("DASHBOARD_REFRESH_SECONDS", "0"))

STATE_CHIP = {
    "QUEUED": "🟡 QUEUED",
    "RUNNING": "🔵 RUNNING",
    "NEEDS_ATTENTION": "🟠 NEEDS_ATTENTION",
    "COMPLETED": "✅ COMPLETED",
    "NO_CHANGE": "☑️ NO CHANGE",
    "FAILED": "❌ FAILED",
}

st.set_page_config(page_title="Devin Remediation Orchestrator", layout="wide")

# Optional lightweight auto-refresh (no extra dependency). OFF by default so a
# page reload never interrupts a screen recording.
if REFRESH_SECONDS > 0:
    st.markdown(
        f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">',
        unsafe_allow_html=True,
    )


def load_rows() -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    # Read-only connection so we never block the API writer.
    uri = f"file:{DB_PATH}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM remediations ORDER BY created_at DESC"
        ).fetchall()]
        conn.close()
    except sqlite3.OperationalError:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def minutes_to_fix(row) -> float | None:
    try:
        start = datetime.fromisoformat(row["launched_at"])
        end = datetime.fromisoformat(row["completed_at"])
    except (TypeError, ValueError):
        return None
    return round((end - start).total_seconds() / 60, 1)


# ── Header ────────────────────────────────────────────────────
head_left, head_right = st.columns([5, 1])
with head_left:
    st.title("Devin Remediation Orchestrator · live")
with head_right:
    st.write("")  # vertical nudge so the button lines up under the title row
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

_refresh_note = (
    f"Auto-refreshes every {REFRESH_SECONDS}s."
    if REFRESH_SECONDS > 0
    else "Refresh with the 🔄 button (or your browser)."
)
st.caption(
    "Event-driven remediation of the unstaffed backlog. GitHub issue → FastAPI "
    f"orchestrator → Devin v3 sessions → PRs on the fork. {_refresh_note}"
)

df = load_rows()

if df.empty:
    st.info("No remediations yet. Trigger a scan: `curl -X POST localhost:8000/simulate/scan`")
    st.stop()

# Derived duration column: how long Devin was engaged before its verdict.
# Shown for terminal / escalated rows that actually did work (a PR, a "no change"
# verdict, or a blocked escalation). RUNNING/QUEUED show nothing yet.
_TIMED_STATES = {"COMPLETED", "NO_CHANGE", "NEEDS_ATTENTION"}
df["mins"] = df.apply(
    lambda r: minutes_to_fix(r) if r["state"] in _TIMED_STATES else None, axis=1
)

detected = len(df)
active = int(df["state"].isin(["RUNNING", "NEEDS_ATTENTION"]).sum())
completed = int((df["state"] == "COMPLETED").sum())
failed = int((df["state"] == "FAILED").sum())
prs_open = int(df["pr_url"].notna().sum()) if "pr_url" in df else 0
resolved = completed + failed
success_rate = round(100 * completed / resolved, 0) if resolved else 0
median_ttp = df.loc[df["state"] == "COMPLETED", "mins"].median()
median_ttp = round(median_ttp, 1) if pd.notna(median_ttp) else None
total_acus = round(float(df["acus_consumed"].fillna(0).sum()), 2)
avg_acus = round(total_acus / completed, 2) if completed else 0

# ── Metric cards ──────────────────────────────────────────────
c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
c1.metric("Issues detected", detected)
c2.metric("Sessions active", active)
c3.metric("PRs open", prs_open)
c4.metric("Completed", completed)
c5.metric("Success rate", f"{success_rate:.0f}%")
c6.metric("Median time-to-PR", f"{median_ttp}m" if median_ttp is not None else "—")
c7.metric("Total ACUs", total_acus)
c8.metric("Avg ACUs / fix", avg_acus)

st.divider()

# ── Needs attention panel ─────────────────────────────────────
attention = df[df["state"] == "NEEDS_ATTENTION"]
if not attention.empty:
    st.subheader("🟠 Sessions waiting on a human")
    for _, r in attention.iterrows():
        st.markdown(
            f"- **#{r['issue_number']} — {r['issue_title']}** "
            f"({r.get('status_detail') or 'waiting'}) · "
            f"[open session]({r.get('session_url') or '#'})"
        )
    st.divider()

# ── Pipeline table ────────────────────────────────────────────
st.subheader("Pipeline")


def pr_link(url):
    # Return None (not "") for empty so the LinkColumn renders a blank cell
    # instead of a dead "view PR" link on non-completed rows.
    return url if url else None


table = pd.DataFrame({
    "Issue": df["issue_number"],
    "Title": df["issue_title"],
    "Category": df["category"],
    "State": df["state"].map(lambda s: STATE_CHIP.get(s, s)),
    "PR": df["pr_url"].map(pr_link) if "pr_url" in df else None,
    "Session": df["session_url"] if "session_url" in df else None,
    "ACUs": df["acus_consumed"].fillna(0).round(2),
    "Devin worked (m)": df["mins"],
})
# Predictable, human order: by issue number ascending (not creation time).
table = table.sort_values("Issue").reset_index(drop=True)

st.dataframe(
    table,
    use_container_width=True,
    hide_index=True,
    column_config={
        "PR": st.column_config.LinkColumn("PR", display_text="view PR"),
        "Session": st.column_config.LinkColumn("Session", display_text="view session"),
    },
)

# ── Category breakdown ────────────────────────────────────────
st.subheader("Completed fixes by category")
completed_df = df[df["state"] == "COMPLETED"]
if completed_df.empty:
    st.caption("No completed fixes yet.")
else:
    by_cat = completed_df.groupby("category").size().rename("completed")
    st.bar_chart(by_cat)


# ── Devin-native analytics (straight from the Devin v3 API) ────
st.divider()
st.subheader("Devin-native analytics · live from the Devin API")
st.caption(
    "Not reconstructed from my database. This pulls Devin's OWN org-level "
    "observability: `GET /v3/organizations/{org}/sessions/insights` and "
    "`/consumption/daily`. Proof the orchestrator uses more than the session API."
)


@st.cache_data(ttl=30, show_spinner=False)
def _devin_native():
    if not _DEVIN_CLIENT:
        return None
    try:
        return {
            "insights": devin_client.list_session_insights(),
            "consumption": devin_client.org_consumption_daily() or {},
        }
    except Exception:  # noqa: BLE001
        return None


native = _devin_native()
if not native or not native["insights"]:
    st.caption("Devin API not reachable right now — panel populates live when it responds.")
else:
    ins = native["insights"]
    cons = native["consumption"]
    remediation = [s for s in ins if "auto-remediation" in (s.get("tags") or [])]
    total_prs = sum(len(s.get("pull_requests") or []) for s in ins)

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Devin sessions (org)", len(ins))
    d2.metric("From this orchestrator", len(remediation))
    d3.metric("PRs across org", total_prs)
    d4.metric(
        "Org ACUs (billed)",
        round(float(cons.get("total_acus", 0) or 0), 2),
        help="From Devin's /consumption/daily API. 0 on the free trial; populates on paid plans.",
    )

    native_tbl = pd.DataFrame([{
        "Session": (s.get("title") or "")[:55],
        "Status": s.get("status"),
        "Size": s.get("session_size"),
        "Devin msgs": s.get("num_devin_messages"),
        "User msgs": s.get("num_user_messages"),
        "PRs": len(s.get("pull_requests") or []),
        "ACUs": round(float(s.get("acus_consumed") or 0), 2),
    } for s in ins])
    st.caption(
        "Per-session insights Devin computes for you — size classification and "
        "message counts my own DB never sees:"
    )
    st.dataframe(native_tbl, use_container_width=True, hide_index=True)
