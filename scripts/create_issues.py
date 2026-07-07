"""Seed the fork with the 5 remediation issues + labels.

Standalone: reads GITHUB_TOKEN and GITHUB_REPO from .env. Idempotent-ish —
labels ignore 422 (already exists); issues are skipped if an open issue with the
same title already exists.

Usage:  python scripts/create_issues.py
"""
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "ShaunakPandya/superset")
API_BASE = "https://api.github.com"

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

LABELS = [
    ("devin-remediate", "5319e7"),
    ("security", "d73a4a"),
    ("code-quality", "fbca04"),
    ("tests", "0e8a16"),
    ("docs", "0075ca"),
]

ISSUES = [
    {
        "title": "[security] Upgrade vulnerable Python dependency flagged by pip-audit",
        "labels": ["devin-remediate", "security"],
        "body": (
            "Run `pip-audit -r requirements/base.txt` (or inspect this fork's Dependabot "
            "alerts). Pick the single flagged package with the most severe advisory that "
            "has a patch or minor version fix available. Bump only that pin in the "
            "requirements file(s) where it appears. Keep the diff minimal — one package. "
            "In the PR body, name the CVE/advisory ID and the version change."
        ),
    },
    {
        "title": "[security] Upgrade a vulnerable npm dependency in superset-frontend",
        "labels": ["devin-remediate", "security"],
        "body": (
            "Run `npm audit` in `superset-frontend/` (or inspect this fork's Dependabot "
            "alerts). Pick one high-severity advisory with a non-breaking (patch/minor) fix. "
            "Update `package.json` and the lockfile for that single package. In the PR body, "
            "name the advisory and version change. Do not run `npm audit fix --force`."
        ),
    },
    {
        "title": "[code-quality] Replace silent broad exception handlers in superset/utils",
        "labels": ["devin-remediate", "code-quality"],
        "body": (
            "Find up to 5 instances under `superset/utils/` where a broad `except Exception` "
            "block swallows an error silently (no logging, no re-raise). In a single module of "
            "your choosing, replace them with either a specific exception type or add "
            "`logger.exception(...)` so failures are observable. Do not change behavior beyond "
            "making errors visible. Run the linter on the changed file."
        ),
    },
    {
        "title": "[tests] Add unit tests for an untested utility module",
        "labels": ["devin-remediate", "tests"],
        "body": (
            "Identify one small, pure-function module under `superset/utils/` with little or no "
            "direct unit test coverage. Add a pytest test file covering its main functions, "
            "including at least one edge case each. All new tests must pass locally. Do not "
            "modify the module under test."
        ),
    },
    {
        "title": "[docs] Fix broken links and outdated commands in CONTRIBUTING documentation",
        "labels": ["devin-remediate", "docs"],
        "body": (
            "Scan `CONTRIBUTING.md` and the top-level docs for broken internal links (files that "
            "don't exist at the referenced path) and obviously outdated commands. Fix up to 5 of "
            "them. List each fix in the PR body."
        ),
    },
]


def ensure_labels(client: httpx.Client) -> None:
    for name, color in LABELS:
        resp = client.post(
            f"{API_BASE}/repos/{GITHUB_REPO}/labels",
            json={"name": name, "color": color},
        )
        if resp.status_code == 201:
            print(f"  + label created: {name}")
        elif resp.status_code == 422:
            print(f"  = label exists:  {name}")
        else:
            print(f"  ! label {name}: {resp.status_code} {resp.text[:200]}")


def existing_titles(client: httpx.Client) -> set[str]:
    titles: set[str] = set()
    page = 1
    while True:
        resp = client.get(
            f"{API_BASE}/repos/{GITHUB_REPO}/issues",
            params={"state": "all", "per_page": 100, "page": page},
        )
        if resp.status_code != 200:
            print(f"  ! could not list issues: {resp.status_code} {resp.text[:200]}")
            break
        batch = resp.json()
        if not batch:
            break
        for item in batch:
            if "pull_request" not in item:
                titles.add(item["title"])
        page += 1
    return titles


def create_issues(client: httpx.Client) -> None:
    seen = existing_titles(client)
    for issue in ISSUES:
        if issue["title"] in seen:
            print(f"  = issue exists: {issue['title']}")
            continue
        resp = client.post(
            f"{API_BASE}/repos/{GITHUB_REPO}/issues",
            json={
                "title": issue["title"],
                "body": issue["body"],
                "labels": issue["labels"],
            },
        )
        if resp.status_code == 201:
            num = resp.json().get("number")
            print(f"  + issue #{num} created: {issue['title']}")
        else:
            print(f"  ! issue failed ({resp.status_code}): {resp.text[:200]}")


def main() -> int:
    if not GITHUB_TOKEN:
        print("ERROR: GITHUB_TOKEN not set (check your .env).", file=sys.stderr)
        return 1
    print(f"Seeding labels + issues in {GITHUB_REPO} ...")
    with httpx.Client(headers=HEADERS, timeout=30) as client:
        print("Labels:")
        ensure_labels(client)
        print("Issues:")
        create_issues(client)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
