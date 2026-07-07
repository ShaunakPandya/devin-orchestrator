"""FastAPI orchestrator: GitHub webhook + simulate endpoints, background poller."""
import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request

from . import config, db, devin_client, github_client, orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    log.info("DB initialized at %s", config.DB_PATH)
    log.info("Repo=%s trigger_label=%s max_concurrent=%s",
             config.GITHUB_REPO, config.TRIGGER_LABEL, config.MAX_CONCURRENT_SESSIONS)
    poller = asyncio.create_task(orchestrator.poll_loop())
    try:
        yield
    finally:
        poller.cancel()


app = FastAPI(title="Devin Remediation Orchestrator", lifespan=lifespan)


def _verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Verify GitHub's X-Hub-Signature-256 header (HMAC-SHA256 of raw body)."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    secret = config.GITHUB_WEBHOOK_SECRET.encode()
    expected = "sha256=" + hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
):
    raw = await request.body()
    if not _verify_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid or missing signature")

    payload = await request.json()
    action = payload.get("action")
    issue = payload.get("issue")

    if not issue or action not in ("labeled", "opened"):
        return {"ignored": True, "reason": f"action={action}"}

    label_names = github_client.get_label_names(issue)
    if config.TRIGGER_LABEL not in label_names:
        return {"ignored": True, "reason": "trigger label not present"}

    newly = orchestrator.enqueue(issue)
    return {"enqueued": issue["number"], "new": newly}


@app.post("/simulate/scan")
async def simulate_scan():
    """Demo path: scan the repo for labeled open issues and enqueue any not yet tracked."""
    issues = github_client.list_labeled_issues()
    enqueued, skipped = [], []
    for issue in issues:
        if db.exists(issue["number"]):
            skipped.append(issue["number"])
        elif orchestrator.enqueue(issue):
            enqueued.append(issue["number"])
        else:
            skipped.append(issue["number"])
    return {"enqueued": enqueued, "skipped": skipped}


@app.post("/simulate/issue/{issue_number}")
async def simulate_issue(issue_number: int):
    """Fetch a single issue and enqueue it."""
    issue = github_client.get_issue(issue_number)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    if "pull_request" in issue:
        raise HTTPException(status_code=400, detail="That number is a PR, not an issue")
    newly = orchestrator.enqueue(issue)
    return {"enqueued": issue_number, "new": newly}


@app.get("/status")
async def status():
    """Dump all remediation rows as JSON."""
    return {"remediations": db.get_all()}


@app.get("/devin/insights")
async def devin_insights():
    """Org-level analytics pulled straight from the Devin v3 API — demonstrates
    using more than the session API (/sessions/insights + /consumption/daily)."""
    insights = devin_client.list_session_insights()
    consumption = devin_client.org_consumption_daily() or {}
    return {
        "source": "devin_api",
        "session_count": len(insights),
        "consumption": consumption,
        "sessions": insights,
    }
