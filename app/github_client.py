"""GitHub REST API wrapper (httpx).

Auth: Authorization: Bearer {GITHUB_TOKEN}, Accept: application/vnd.github+json.
Base https://api.github.com.
"""
import logging
from typing import Any, Optional

import httpx

from . import config

log = logging.getLogger("github_client")

API_BASE = "https://api.github.com"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _request(method: str, path: str, *, json_body: Optional[dict] = None,
            params: Optional[dict] = None) -> Optional[Any]:
    url = f"{API_BASE}{path}"
    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.request(
                    method, url, headers=_headers(), json=json_body, params=params
                )
            if resp.status_code >= 500:
                log.warning("GitHub %s %s -> %s (attempt %s)", method, path,
                            resp.status_code, attempt)
                if attempt == 1:
                    continue
                return None
            if resp.status_code >= 400:
                log.error("GitHub %s %s -> %s: %s", method, path,
                          resp.status_code, resp.text[:500])
                return None
            return resp.json() if resp.content else {}
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            log.warning("GitHub %s %s network error (attempt %s): %s",
                        method, path, attempt, exc)
            if attempt == 1:
                continue
            return None
    return None


def list_labeled_issues() -> list[dict[str, Any]]:
    """GET open issues carrying the trigger label. Filters out PRs (which the issues endpoint also returns)."""
    result = _request(
        "GET",
        f"/repos/{config.GITHUB_REPO}/issues",
        params={
            "labels": config.TRIGGER_LABEL,
            "state": "open",
            "per_page": 50,
        },
    )
    if not result:
        return []
    return [issue for issue in result if "pull_request" not in issue]


def get_issue(issue_number: int) -> Optional[dict[str, Any]]:
    """GET a single issue by number."""
    return _request("GET", f"/repos/{config.GITHUB_REPO}/issues/{issue_number}")


def comment(issue_number: int, body: str) -> Optional[dict[str, Any]]:
    """POST a comment on an issue."""
    return _request(
        "POST",
        f"/repos/{config.GITHUB_REPO}/issues/{issue_number}/comments",
        json_body={"body": body},
    )


def get_label_names(issue_payload: dict[str, Any]) -> list[str]:
    """Extract label name strings from an issue payload (labels may be strings or objects)."""
    names = []
    for label in issue_payload.get("labels", []) or []:
        if isinstance(label, dict):
            name = label.get("name")
        else:
            name = label
        if name:
            names.append(name)
    return names


def category_from_labels(issue_payload: dict[str, Any]) -> str:
    """Map an issue's labels to one of the known categories; default 'other'."""
    names = set(get_label_names(issue_payload))
    for category in config.KNOWN_CATEGORIES:
        if category in names:
            return category
    return "other"
