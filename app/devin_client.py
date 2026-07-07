"""Devin v3 API wrapper (httpx).

Auth: Authorization: Bearer {DEVIN_API_KEY}
All paths under {DEVIN_API_BASE}/v3/organizations/{DEVIN_ORG_ID}.

Session-detail endpoints take a `devin_id`, which is the session_id prefixed
with `devin-`. Use `to_devin_id()` to normalize.
"""
import logging
from typing import Any, Optional

import httpx

from . import config

log = logging.getLogger("devin_client")

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _base_url() -> str:
    return f"{config.DEVIN_API_BASE}/v3/organizations/{config.DEVIN_ORG_ID}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.DEVIN_API_KEY}",
        "Content-Type": "application/json",
    }


def to_devin_id(session_id: str) -> str:
    """Normalize a session_id into the `devin-` prefixed form the detail endpoints expect."""
    if not session_id:
        return session_id
    return session_id if session_id.startswith("devin-") else f"devin-{session_id}"


def _request(method: str, path: str, *, json_body: Optional[dict] = None) -> Optional[dict]:
    """Issue a request with one retry on 5xx / timeout. Returns parsed JSON or None on failure."""
    url = f"{_base_url()}{path}"
    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.request(method, url, headers=_headers(), json=json_body)
            if resp.status_code >= 500:
                log.warning("Devin %s %s -> %s (attempt %s): %s",
                            method, path, resp.status_code, attempt, resp.text[:500])
                if attempt == 1:
                    continue
                return None
            if resp.status_code >= 400:
                log.error("Devin %s %s -> %s: %s",
                          method, path, resp.status_code, resp.text[:500])
                return None
            return resp.json() if resp.content else {}
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            log.warning("Devin %s %s network error (attempt %s): %s", method, path, attempt, exc)
            if attempt == 1:
                continue
            return None
    return None


def create_session(prompt: str, title: str, tags: list[str], category: str,
                   issue_number: int) -> Optional[dict[str, Any]]:
    """POST /sessions — create a Devin session with a required structured output schema.

    Returns dict with session_id, url, status (or None on failure).
    """
    body = {
        "prompt": prompt,
        "title": title,
        "tags": tags,
        "structured_output_required": True,
        "structured_output_schema": {
            "type": "object",
            "properties": {
                "issue_number": {"type": "integer"},
                "outcome": {
                    "type": "string",
                    "enum": ["pr_opened", "blocked", "no_change_needed"],
                },
                "pr_url": {"type": "string"},
                "summary": {"type": "string"},
                "risk_notes": {"type": "string"},
            },
            "required": ["outcome", "summary"],
        },
    }
    return _request("POST", "/sessions", json_body=body)


def get_session(devin_id: str) -> Optional[dict[str, Any]]:
    """GET /sessions/{devin_id} — poll session status, PRs, structured output, ACUs."""
    return _request("GET", f"/sessions/{to_devin_id(devin_id)}")


def send_message(devin_id: str, message: str) -> Optional[dict[str, Any]]:
    """POST /sessions/{devin_id}/messages — escalation hook (not used in main flow)."""
    return _request(
        "POST",
        f"/sessions/{to_devin_id(devin_id)}/messages",
        json_body={"message": message},
    )


# ── Org-level observability (beyond the session API) ──────────────
# These read Devin's OWN analytics endpoints so the dashboard surfaces
# platform-native metrics, not just what this orchestrator recorded.

def list_session_insights() -> list[dict[str, Any]]:
    """GET /sessions/insights — org sessions enriched with size classification,
    message counts, PRs, ACUs, and Devin's AI-generated analysis."""
    resp = _request("GET", "/sessions/insights")
    if isinstance(resp, dict):
        return resp.get("items", []) or []
    return []


def org_consumption_daily() -> Optional[dict[str, Any]]:
    """GET /consumption/daily — org ACU consumption (total + per-day breakdown)."""
    return _request("GET", "/consumption/daily")
