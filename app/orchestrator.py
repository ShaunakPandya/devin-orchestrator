"""Orchestrator: enqueue issues, launch Devin sessions under a concurrency cap,
and poll sessions to completion — commenting back on the GitHub issue at each
meaningful state transition.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from . import config, db, devin_client, github_client

log = logging.getLogger("orchestrator")

# States that count against the concurrency cap.
ACTIVE_STATES = ("RUNNING", "NEEDS_ATTENTION")

PROMPT_TEMPLATE = """You are remediating a GitHub issue in the repository {repo} (a fork of apache/superset).

Issue #{issue_number}: {issue_title}

Issue body:
{issue_body}

Instructions:
1. Clone {repo} and work on the master branch.
2. Create a branch named devin/issue-{issue_number}.
3. Make the smallest change that fully resolves the issue. Do NOT refactor beyond the issue's scope.
4. Run any linters or tests directly relevant to the files you changed and make sure they pass. Do not run the full superset test suite.
5. Open a pull request against master of {repo}. The PR body must start with "Fixes #{issue_number}" and include a short summary of the change and how you verified it.
6. If the issue cannot be resolved with a small, safe change, do NOT force it: comment your findings and stop, and report outcome "blocked" in your structured output.
7. Report your structured output with the PR URL when done.
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _build_prompt(issue_number: int, issue_title: str, issue_body: str) -> str:
    return PROMPT_TEMPLATE.format(
        repo=config.GITHUB_REPO,
        issue_number=issue_number,
        issue_title=issue_title,
        issue_body=issue_body or "(no description provided)",
    )


def enqueue(issue: dict[str, Any]) -> bool:
    """Insert a QUEUED row for the issue if not already tracked, then try to launch.

    Returns True if newly enqueued, False if it was already present.
    """
    issue_number = issue["number"]
    if db.exists(issue_number):
        log.info("Issue #%s already tracked; skipping enqueue.", issue_number)
        maybe_launch()
        return False

    category = github_client.category_from_labels(issue)
    db.insert_remediation({
        "issue_number": issue_number,
        "issue_title": issue.get("title", ""),
        "category": category,
        "state": "QUEUED",
        "created_at": _now_iso(),
    })
    log.info("Enqueued issue #%s (%s).", issue_number, category)
    maybe_launch()
    return True


def maybe_launch() -> None:
    """Launch QUEUED sessions until the concurrency cap is reached."""
    while db.count_by_state(*ACTIVE_STATES) < config.MAX_CONCURRENT_SESSIONS:
        queued = db.get_by_state("QUEUED")
        if not queued:
            return
        row = sorted(queued, key=lambda r: r.get("created_at") or "")[0]
        _launch_one(row)


def _launch_one(row: dict[str, Any]) -> None:
    issue_number = row["issue_number"]
    category = row.get("category") or "other"

    # Fetch the freshest issue body (the DB row only stores the title).
    issue = github_client.get_issue(issue_number) or {}
    issue_body = issue.get("body") or ""
    issue_title = row.get("issue_title") or issue.get("title") or ""

    prompt = _build_prompt(issue_number, issue_title, issue_body)
    title = f"Remediate #{issue_number}: {issue_title}"
    tags = ["auto-remediation", category, f"issue-{issue_number}"]

    resp = devin_client.create_session(prompt, title, tags, category, issue_number)
    if not resp or not resp.get("session_id"):
        log.error("Failed to create Devin session for issue #%s; leaving QUEUED.", issue_number)
        return

    session_id = resp["session_id"]
    session_url = resp.get("url", "")
    db.update_remediation(
        issue_number,
        session_id=session_id,
        session_url=session_url,
        status=resp.get("status"),
        state="RUNNING",
        launched_at=_now_iso(),
    )
    log.info("Launched Devin session %s for issue #%s.", session_id, issue_number)

    github_client.comment(
        issue_number,
        f"🤖 Devin session started for this issue: {session_url}\n\n"
        f"Tagged: {category}. The orchestrator will report back here when a PR is open.",
    )


def _extract_pr(session: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Return (pr_url, pr_state) from a session's pull_requests array, if any."""
    prs = session.get("pull_requests") or []
    if prs:
        first = prs[0]
        return first.get("pr_url"), first.get("pr_state")
    return None, None


def _structured_outcome(session: dict[str, Any]) -> tuple[Optional[str], dict[str, Any]]:
    """Return (outcome, structured_output_dict) from a session."""
    so = session.get("structured_output")
    if isinstance(so, str):
        try:
            so = json.loads(so)
        except (ValueError, TypeError):
            so = None
    if isinstance(so, dict):
        return so.get("outcome"), so
    return None, {}


def _minutes_between(start_iso: Optional[str], end_iso: Optional[str]) -> Optional[int]:
    start, end = _parse_iso(start_iso), _parse_iso(end_iso)
    if not start or not end:
        return None
    return max(0, round((end - start).total_seconds() / 60))


def poll_once() -> None:
    """One poll pass over all active sessions; update state and comment on transitions."""
    active = db.get_by_state(*ACTIVE_STATES)
    for row in active:
        try:
            _poll_row(row)
        except Exception:  # noqa: BLE001 — never let one bad row kill the loop
            log.exception("Error polling issue #%s", row.get("issue_number"))
    # Drain the queue in case a slot freed up.
    maybe_launch()


def _poll_row(row: dict[str, Any]) -> None:
    issue_number = row["issue_number"]
    session_id = row.get("session_id")
    if not session_id:
        return

    session = devin_client.get_session(session_id)
    if not session:
        return

    status = session.get("status")
    status_detail = session.get("status_detail")
    acus = session.get("acus_consumed", row.get("acus_consumed") or 0)
    pr_url, pr_state = _extract_pr(session)
    outcome, structured = _structured_outcome(session)

    # Always refresh raw fields for observability.
    db.update_remediation(
        issue_number,
        status=status,
        status_detail=status_detail,
        acus_consumed=acus,
        structured_output=structured or None,
    )

    prev_state = row.get("state")

    # A PR counts as done ONLY if there's an actual artifact — a non-empty
    # pull_requests array or a real pr_url in the structured output. Devin
    # sometimes reports outcome="pr_opened" optimistically while still working
    # (observed live on issue #4), so the enum alone is NOT proof of completion.
    structured_pr = structured.get("pr_url") if structured else None
    real_pr = pr_url or structured_pr or None

    # ── COMPLETED: a real PR artifact exists ──
    if real_pr:
        if prev_state == "COMPLETED":
            return
        completed_at = _now_iso()
        db.update_remediation(
            issue_number,
            state="COMPLETED",
            pr_url=real_pr,
            pr_state=pr_state or "open",
            completed_at=completed_at,
        )
        minutes = _minutes_between(row.get("launched_at"), completed_at)
        github_client.comment(
            issue_number,
            f"✅ PR opened: {real_pr}\n\n"
            f"Time to fix: {minutes}m · Devin compute: {round(float(acus), 2)} ACUs · "
            f"Session: {row.get('session_url')}",
        )
        log.info("Issue #%s COMPLETED (PR: %s).", issue_number, real_pr)
        return

    # ── NO_CHANGE: Devin exhaustively verified there is nothing to remediate.
    #    A terminal, SUCCESSFUL "nothing to do" outcome, distinct from FAILED
    #    (couldn't do it) and NEEDS_ATTENTION (waiting on a human). Guarded by
    #    "not actively working" so an optimistic mid-flight report cannot
    #    terminate the row early (same lesson as the pr_opened guard above). ──
    if outcome == "no_change_needed" and status_detail != "working":
        if prev_state == "NO_CHANGE":
            return
        summary = (structured.get("summary") if structured else None) or "verified clean"
        db.update_remediation(issue_number, state="NO_CHANGE", completed_at=_now_iso())
        github_client.comment(
            issue_number,
            f"☑️ No change needed. Devin verified the code is already clean.\n\n"
            f"Findings: {summary}\n\nSession: {row.get('session_url')}",
        )
        log.info("Issue #%s NO_CHANGE.", issue_number)
        return

    # ── NEEDS_ATTENTION: recoverable, needs a human. Three non-fatal cases:
    #    (a) outcome=blocked: Devin stopped safely and needs a human decision
    #        (e.g. #2, where the only npm fix is a forbidden breaking downgrade),
    #    (b) suspended for inactivity: resumable (a suspended #4 later shipped PR #8),
    #    (c) waiting_for_user / waiting_for_approval.
    #    Checked BEFORE exit/error so a "blocked" conclusion stays an escalation
    #    even if the session later ends. Devin posts its own findings comment,
    #    so we do not also spam the issue here. ──
    if (outcome == "blocked"
            or status == "suspended"
            or status_detail in ("waiting_for_user", "waiting_for_approval")):
        if outcome == "blocked":
            reason = "blocked: no safe fix"
        elif status == "suspended":
            reason = status_detail or "inactivity"
        else:
            reason = status_detail or "waiting"
        if prev_state != "NEEDS_ATTENTION":
            db.update_remediation(
                issue_number, state="NEEDS_ATTENTION", status_detail=reason
            )
            log.info("Issue #%s NEEDS_ATTENTION (%s).", issue_number, reason)
        return

    # ── FAILED: the session itself terminated (exit/error) without a PR, a
    #    "no change" verdict, or a "blocked" escalation, i.e. it genuinely died. ──
    if status in ("exit", "error"):
        if prev_state == "FAILED":
            return
        summary = (structured.get("summary") if structured else None) or status_detail or "no details"
        db.update_remediation(issue_number, state="FAILED", completed_at=_now_iso())
        github_client.comment(
            issue_number,
            f"⚠️ Devin could not safely remediate this issue. Findings: {summary}. "
            f"Session: {row.get('session_url')}",
        )
        log.info("Issue #%s FAILED (status=%s).", issue_number, status)
        return

    # ── Otherwise: still running. If it had been flagged, un-flag it. ──
    if prev_state == "NEEDS_ATTENTION":
        db.update_remediation(issue_number, state="RUNNING")


async def poll_loop() -> None:
    """Background task: poll every POLL_INTERVAL_SECONDS forever."""
    log.info("Poll loop started (interval=%ss).", config.POLL_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.to_thread(poll_once)
        except Exception:  # noqa: BLE001
            log.exception("Poll loop iteration failed.")
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
