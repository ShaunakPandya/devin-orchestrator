# Devin Remediation Orchestrator

**Drain the unstaffed backlog automatically.** Every engineering org carries a class of
work nobody staffs — CVE patches, dependency bumps, silent exception handlers, missing
tests, stale docs. It's real work, it's never the roadmap, and it only shrinks when a
senior engineer donates a Friday. This is an event-driven automation that remediates that
backlog continuously: a GitHub issue gets labeled, a [Devin](https://devin.ai) session is
created via the v3 REST API, Devin opens a scoped PR on the fork, and the orchestrator
tracks it to completion and reports back — treating **a Devin session as an API primitive
you schedule like compute**, not a chatbot you babysit.

---

## Architecture

```
  GitHub issue labeled            ┌──────────────────────────────┐
  `devin-remediate`  ──webhook──▶ │   FastAPI Orchestrator       │
       │                          │                              │
  (or) POST /simulate/scan ─────▶ │  • enqueue (SQLite, QUEUED)  │
                                  │  • concurrency cap (N)       │
                                  │  • create Devin session      │──▶ Devin v3 API
                                  │  • poll loop (every 45s)     │◀──  (sessions, PRs,
                                  │  • comment back on issue     │      structured output,
                                  └──────────────┬───────────────┘      ACUs)
                                                 │                         │
                                       SQLite (WAL, /data) ◀───────────────┘
                                                 │                    Devin opens PR
                                                 ▼                    on ShaunakPandya/superset
                                  ┌──────────────────────────────┐         │
                                  │   Streamlit Dashboard        │         ▼
                                  │  funnel metrics · pipeline   │   "Fixes #N" PR on fork
                                  │  needs-attention · cost      │
                                  └──────────────────────────────┘
```

Two containers off one image, sharing a named volume at `/data`:
- **api** — FastAPI orchestrator (webhook + simulate endpoints + background poller) on `:8000`
- **dashboard** — Streamlit read-only view on `:8501`

---

## Quickstart

```bash
# 1. Configure secrets
cp .env.example .env
#    edit .env — set DEVIN_API_KEY (cog_…), DEVIN_ORG_ID (org-…),
#    GITHUB_TOKEN (PAT, repo scope), GITHUB_WEBHOOK_SECRET (any random string)

# 2. Bring up both services
docker compose up --build

# 3. Seed the fork with 5 labeled issues (run once, from the host)
python scripts/create_issues.py

# 4. Trigger remediation (the demo path — same code the webhook runs)
curl -X POST localhost:8000/simulate/scan
#    → {"enqueued":[1,2,3,4,5],"skipped":[]}

# 5. Watch it work
open http://localhost:8501            # dashboard
curl localhost:8000/status | jq       # raw rows: QUEUED → RUNNING → COMPLETED
```

> `scripts/create_issues.py` needs `httpx` and `python-dotenv` locally
> (`pip install httpx python-dotenv`), or run it inside the api container:
> `docker compose exec api python scripts/create_issues.py`.

---

## Real-webhook setup (optional)

The `/simulate/scan` endpoint runs the **exact same** enqueue → launch code as the webhook,
so the demo needs no public URL. To wire the real event instead:

1. Expose the api port publicly with [ngrok](https://ngrok.com) (`ngrok http 8000`) or
   [smee.io](https://smee.io).
2. GitHub fork → **Settings → Webhooks → Add webhook**.
3. **Payload URL:** `https://<your-tunnel>/webhook/github`
4. **Content type:** `application/json`
5. **Secret:** the same value as `GITHUB_WEBHOOK_SECRET` in your `.env`.
6. **Events:** *Let me select individual events* → **Issues**.

Now labeling any issue `devin-remediate` fires a signed `POST /webhook/github`, verified via
HMAC-SHA256 before anything runs.

---

## How Devin is used

| Step | What the orchestrator does |
|------|----------------------------|
| **Create** | `POST /v3/organizations/{org}/sessions` with a scoped prompt **and a required `structured_output_schema`** — so every session returns machine-readable results (`outcome`, `pr_url`, `summary`, `risk_notes`), not just chat. |
| **Tag** | Each session is tagged `auto-remediation`, its category, and `issue-N` — a fleet you can filter in the Devin web app. |
| **Poll** | `GET /sessions/{devin_id}` every 45s reads `status`, `status_detail`, `pull_requests`, `structured_output`, `acus_consumed`. (Note: `devin_id` = `session_id` prefixed with `devin-`.) |
| **PR detection** | A non-empty `pull_requests` array **or** `structured_output.outcome == "pr_opened"` flips the row to `COMPLETED` and posts the ✅ comment with PR link, minutes, and ACU cost. |
| **Escalation** | `status_detail` of `waiting_for_user` / `waiting_for_approval` → `NEEDS_ATTENTION`, surfaced on the dashboard (no comment spam). `send_message()` is implemented as the escalation hook to nudge a waiting session. |
| **Concurrency** | `MAX_CONCURRENT_SESSIONS` caps live sessions; the rest stay `QUEUED` and drain as slots free. |

### State machine

```
QUEUED ──launch──▶ RUNNING ──PR opened / outcome=pr_opened──▶ COMPLETED
                     │
                     ├── waiting_for_user/approval ──▶ NEEDS_ATTENTION ──▶ (RUNNING / COMPLETED)
                     │
                     └── exit/error/blocked/suspended, no PR ──▶ FAILED
```

The orchestrator comments **exactly once per transition**, so the GitHub issue is a clean
audit trail: session started → PR opened (or blocked findings).

---

## Observability — "how would a leader know this is working?"

The Streamlit dashboard answers it directly:

- **Funnel:** issues detected · sessions active · PRs open · completed · **success rate %**
- **Speed:** median time-to-PR (launched → completed)
- **Cost:** total ACUs · avg ACUs per fix (Devin compute is priced in ACUs)
- **Needs attention:** sessions paused on a human — *the system knows when it doesn't know*
- **Pipeline table:** every issue, category, state chip, PR + session links
- **Category breakdown:** completed fixes by category (security / code-quality / tests / docs)

`GET /status` dumps the same data as JSON for curl demos and scripting.

---

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/webhook/github` | GitHub webhook, HMAC-verified. `labeled`/`opened` + trigger label → enqueue. |
| `POST` | `/simulate/scan` | Scan the repo for labeled open issues; enqueue any not yet tracked. **Demo path.** |
| `POST` | `/simulate/issue/{n}` | Fetch and enqueue one issue. |
| `GET`  | `/status` | All remediation rows as JSON. |
| `GET`  | `/devin/insights` | Org-level analytics pulled **straight from the Devin v3 API** (`/sessions/insights` + `/consumption/daily`) — proves the orchestrator uses more than the session API. |
| `GET`  | `/healthz` | Liveness check. |

---

## Issues seeded (broad coverage, not one task)

`scripts/create_issues.py` creates five issues spanning four categories, so the demo lands
the "imagine how this compounds" point:

1. **security** — upgrade a vulnerable Python dependency flagged by pip-audit
2. **security** — upgrade a vulnerable npm dependency in `superset-frontend`
3. **code-quality** — replace silent broad exception handlers in `superset/utils`
4. **tests** — add unit tests for an untested utility module
5. **docs** — fix broken links / outdated commands in CONTRIBUTING docs

---

## Security note

- Secrets live in `.env` only — gitignored, never committed. `.env.example` documents the shape.
- The webhook verifies GitHub's `X-Hub-Signature-256` via HMAC-SHA256 with
  `hmac.compare_digest` (constant-time); unsigned or mismatched payloads get `401`.
- Devin and GitHub tokens are sent as `Authorization: Bearer` headers and never logged
  (`config.masked()` is available for any diagnostic printing).

---

## Project layout

```
devin-remediation-orchestrator/
├── docker-compose.yml        # api + dashboard, shared /data volume
├── Dockerfile                # python:3.11-slim, one image
├── .env.example              # secret shape (copy to .env)
├── requirements.txt
├── app/
│   ├── main.py               # FastAPI: webhook + simulate endpoints, poller lifespan
│   ├── config.py             # env loading
│   ├── db.py                 # SQLite (WAL) init + CRUD
│   ├── devin_client.py       # Devin v3 wrapper (create/get/message), retry on 5xx
│   ├── github_client.py      # GitHub REST wrapper (issues, comments, labels)
│   └── orchestrator.py       # enqueue, maybe_launch, poll loop, state machine
├── dashboard/app.py          # Streamlit dashboard
└── scripts/create_issues.py  # seed 5 labeled issues in the fork
```
