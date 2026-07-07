# Architecture

A complete technical description of the Devin Remediation Orchestrator: what each part does, how data flows end to end, the Devin v3 API model, the state machine, and the real-world lessons that shaped the design.

---

## 1. The thesis

Every mature codebase accumulates a class of work that is individually trivial and collectively enormous — CVE bumps, dependency upgrades, silent `except` blocks, missing tests, doc rot. It never wins roadmap priority, so it's only ever cleared when a senior engineer volunteers time. This system turns that class from *manual, episodic, invisible* into *automated, continuous, measured*.

The architectural bet: **a Devin session is an API primitive** — something you create programmatically, in parallel, with structured inputs and structured outputs, the way you'd spin up a container or enqueue a job. An event creates a session; the session produces a PR; the whole flow is tracked and reported so a non-technical leader can see it working.

The system is **event-driven** so the trigger *source* is swappable. Today it's a GitHub label (or the `/simulate/scan` endpoint that mimics it); the same enqueue path would be driven by a Snyk finding, a Sentry alert, a Dependabot PR, or a Jira ticket. The trigger is deliberately thin.

---

## 2. Topology

Two processes, one Docker image, one shared database.

```
┌────────────────── docker-compose (one image, two services) ──────────────────┐
│                                                                               │
│  ┌─ api  (uvicorn, :8000) ─────────┐      ┌─ dashboard (streamlit, :8501) ─┐  │
│  │  FastAPI app (app/main.py)      │      │  read-only viewer              │  │
│  │  - webhook + simulate endpoints │      │  (dashboard/app.py)            │  │
│  │  - background poll loop (async) │      │  - opens the SAME sqlite file  │  │
│  │  writes ───────────┐            │      │    mode=ro, recomputes metrics │  │
│  └────────────────────┼───────────┘      └───────────────┬────────────────┘  │
│                       │                                   │ reads             │
│                       ▼                                   ▼                   │
│           ┌────── named volume  /data/orchestrator.db ──────────┐            │
│           │  SQLite in WAL mode (writer: api, reader: dashboard) │            │
│           └─────────────────────────────────────────────────────┘            │
└───────────────────────────────────────────────────────────────────────────────┘
        │ outbound HTTPS                              │ outbound HTTPS
        ▼                                             ▼
  Devin v3 API (api.devin.ai)                   GitHub REST (api.github.com)
  create / get / message sessions               list issues, comment, labels
```

Design decisions:
- **One image, two services.** The `Dockerfile` builds a single image with `app/`, `dashboard/`, `scripts/`. `docker-compose.yml` runs it twice with different commands. Less to build, identical dependencies.
- **Shared named volume at `/data`.** Both containers mount `orchestrator-data:/data`, so both see the same `orchestrator.db`. This is how the dashboard reads what the API writes.
- **WAL mode is load-bearing.** SQLite's default journal takes a whole-file lock on writes, which would collide the dashboard's reads with the API's writes across two containers. `PRAGMA journal_mode=WAL` lets readers proceed concurrently with a writer. Without it, two-container SQLite sharing is flaky.

---

## 3. End-to-end request lifecycle

1. **Trigger** — a real webhook (`POST /webhook/github`, HMAC-verified) or the demo endpoints (`/simulate/scan`, `/simulate/issue/{n}`). All converge on `orchestrator.enqueue(issue)`.
2. **Enqueue** — if the issue isn't already tracked, insert a row `state=QUEUED`, `created_at=now`, `category` derived from labels. Then `maybe_launch()`.
3. **Launch gating** (`maybe_launch`) — while `count(RUNNING + NEEDS_ATTENTION) < MAX_CONCURRENT_SESSIONS`, take the oldest `QUEUED` row and launch it. Concurrency cap and queue drain in one loop.
4. **Launch one** (`_launch_one`) — fetch the issue body from GitHub, render the prompt, `create_session(...)` with the structured-output schema. Store `session_id`/`session_url`, flip to `RUNNING`, stamp `launched_at`, post the `🤖 session started` comment.
5. **Poll** (`poll_loop → poll_once → _poll_row`) — every 45s, for each row in `RUNNING`/`NEEDS_ATTENTION`: `get_session`, refresh raw fields, run the state machine.
6. **Terminal transitions** — real PR → `COMPLETED` + `✅` comment; dead/blocked → `FAILED` + `⚠️` comment; paused/waiting → `NEEDS_ATTENTION` (no comment).
7. **Drain** — after each pass, `maybe_launch()` again; a freed slot launches the next `QUEUED` issue.
8. **Observe** — the dashboard, on a 15s refresh, reopens the DB read-only and recomputes the funnel. It never calls the API; it reads the shared truth.

---

## 4. Components

### `app/config.py`
Loads env once via `python-dotenv`, exposes constants, normalizes types (`rstrip("/")`, int casts). Holds `KNOWN_CATEGORIES` and `masked()`. Rule: **nothing else reads `os.getenv` directly** — config is the single chokepoint, which makes the app testable by setting env before import.

### `app/db.py`
Stdlib `sqlite3`, no ORM. `_connect()` sets `row_factory=Row`, WAL, and a busy timeout. One table `remediations`, `issue_number` primary key. CRUD is small: `insert_remediation` (`INSERT OR IGNORE` → re-enqueue is a no-op), `update_remediation` (patches arbitrary columns, JSON-encodes dicts), and query helpers. The primary key is what makes the whole system **idempotent** — scan the same repo repeatedly, never double-launch.

### `app/github_client.py`
httpx wrapper; `_request` centralizes headers and retries once on 5xx/timeout.
- `list_labeled_issues()` — GETs open labeled issues **and filters out anything with a `pull_request` key**, because GitHub's issues endpoint also returns PRs. Without this filter you'd "remediate" your own PRs.
- `comment`, `get_issue`.
- `category_from_labels()` — maps labels to `security | code-quality | tests | docs`, default `other`.

### `app/devin_client.py`
The Devin v3 wrapper — most protocol nuance lives here.
- Base: `{DEVIN_API_BASE}/v3/organizations/{DEVIN_ORG_ID}`; auth `Bearer {DEVIN_API_KEY}`.
- **`to_devin_id()`** — the create response returns `session_id`; the detail/message endpoints want a `devin_id` = that id **prefixed with `devin-`**. The response may or may not already carry it, so normalize. Get this wrong and every poll 404s.
- **`create_session()`** — POSTs prompt/title/tags plus `structured_output_required: true` and a JSON Schema (`outcome`, `summary` required; `pr_url`, `risk_notes`, `issue_number` optional). This forces machine-readable results instead of prose.
- **`get_session()`** — the poll read.
- **`send_message()`** — the **escalation hook** (not on the main path). Programmatically nudges a `waiting_for_user`/suspended session — the API version of clicking "wake up Devin."
- All calls retry once on 5xx/timeout, log on 4xx, return `None` on failure so a bad poll leaves the row unchanged until next tick.

### `app/orchestrator.py` — the brain
- **`PROMPT_TEMPLATE`** — scoped instructions: work on `master`, branch `devin/issue-N`, make the *smallest* change, run only relevant checks (not the full Superset suite), open a PR whose body starts with `Fixes #N`, and if it can't be done safely, **comment findings and report `blocked` rather than forcing it**. It never names the specific package/file — Devin scopes its own work. That's the "agent, not script" property.
- **`enqueue` / `maybe_launch` / `_launch_one`** — see §3. `maybe_launch` counts `RUNNING`+`NEEDS_ATTENTION` against the cap and launches oldest-first (FIFO by `created_at`).
- **`_poll_row`** — the state machine (§6).
- **`poll_loop`** — infinite async loop; `await asyncio.to_thread(poll_once)` every 45s. `to_thread` matters: the httpx/sqlite calls are synchronous, and running them in the event loop would block the API. Offloading keeps the server responsive.

### `app/main.py` — the FastAPI surface
- **`lifespan`** — startup runs `init_db()` then `asyncio.create_task(poll_loop())`. The poller is tied to app lifecycle; no external scheduler needed.
- **`/webhook/github`** — reads the **raw body** (raw bytes, not re-serialized JSON, or the signature won't match), computes `"sha256=" + HMAC_SHA256(secret, body)`, compares to `X-Hub-Signature-256` with `hmac.compare_digest` (constant-time). Mismatch → 401. Acts only on `action in ("labeled","opened")` with the trigger label present.
- **`/simulate/scan`** — lists labeled issues, enqueues new ones, returns `{enqueued, skipped}`. Runs the *identical* code as the webhook — demo path = production path.
- **`/simulate/issue/{n}`** — enqueue exactly one.
- **`/status`** — all rows as JSON. **`/healthz`** — liveness.

### `dashboard/app.py` — observability
Opens the DB read-only (`file:...?mode=ro`) so it can never block the writer. Loads rows into pandas, derives `mins` (time-to-fix = `completed_at − launched_at`), computes the funnel (detected, active, PRs open, completed, success rate, median time-to-PR, total/avg ACUs), and renders three panels: needs-attention list, pipeline table (emoji state chips, PR/session links), category bar chart. Auto-refresh is a plain `<meta http-equiv="refresh" content="15">` — no extra dependency. Stateless: recomputed each refresh.

### `scripts/create_issues.py`
Standalone seeder. Creates five labels (ignoring 422), then issues — skipping any whose title already exists, so re-running is safe. Note: GitHub **disables the Issues tab on forks by default**, so the fork needs `has_issues` enabled first (a one-time PATCH), otherwise issue creation returns `410`.

---

## 5. The Devin v3 data model

Every poll reads a session object. Decision-driving fields:
- **`status`** — coarse lifecycle: `new → claimed → running → exit/error/suspended/resuming`.
- **`status_detail`** — fine sub-state: `working`, `waiting_for_user`, `waiting_for_approval`, `finished`, `inactivity`, …
- **`pull_requests`** — array of `{pr_url, pr_state}`. **Ground truth for "a PR exists."**
- **`structured_output`** — the JSON your schema requested (`outcome`, `pr_url`, `summary`, `risk_notes`). May be a dict or a JSON string.
- **`acus_consumed`** — compute cost in ACUs. `0.0` on the free trial.

The key mental model: **`status`/`status_detail` describe the *session*; `pull_requests`/`structured_output` describe the *work product*.** They can disagree — a session can be `running/waiting_for_user` (alive, waiting on CI) while a PR already exists (work done). The state machine resolves the disagreement by **prioritizing the work product**.

---

## 6. The state machine (`_poll_row`)

Order matters; each check returns if it fires. There are six states: `QUEUED`, `RUNNING`, `NEEDS_ATTENTION`, `COMPLETED`, `NO_CHANGE`, `FAILED`.

1. **Real PR exists → `COMPLETED`.** "Real PR" = non-empty `pull_requests` OR a truthy structured `pr_url`. `✅` comment (PR link, minutes, ACUs). *Work product trumps session state.*
2. **`outcome == no_change_needed` (and not actively `working`) → `NO_CHANGE`.** A terminal, *successful* "nothing to do": Devin exhaustively verified the code is already clean. `☑️` comment. Distinct from FAILED (couldn't) and NEEDS_ATTENTION (waiting). Guarded by "not working" so it can't fire optimistically mid-flight.
3. **`outcome == blocked` OR `suspended` OR `waiting_for_user/approval` → `NEEDS_ATTENTION`.** All three are *recoverable escalations that need a human*, not failures: `blocked` = Devin stopped safely and needs a decision; `suspended` = idle-timeout, resumable; `waiting_*` = waiting on input/approval. No comment from us (Devin posts its own findings; the dashboard surfaces the row). Checked **before** exit/error so a `blocked` conclusion stays an escalation even if the session later ends.
4. **`status in (exit, error)` → `FAILED`.** The session *itself* died without a PR, a no-change verdict, or a blocked escalation. `⚠️` comment.
5. **Otherwise → stay `RUNNING`** (and un-flag if it had been `NEEDS_ATTENTION` but is working again).

Every terminal branch guards with `if prev_state == <target>: return`, so a transition **comments exactly once**. Polls happen every 45s; the issue only gets one comment per real state change.

```
QUEUED ─launch─▶ RUNNING ─real PR──────────────────────────▶ COMPLETED
                   │
                   ├─ outcome=no_change_needed ─────────────▶ NO_CHANGE (verified clean)
                   │
                   ├─ blocked / suspended / waiting_for_user ▶ NEEDS_ATTENTION ─(resume)─▶ RUNNING / COMPLETED
                   │
                   └─ exit / error (session died) ───────────▶ FAILED
```

Design note: `FAILED` is reserved for a session that genuinely crashed. A `blocked` outcome is **not** a failure — it's Devin correctly refusing to force an unsafe change and escalating to a human, so it maps to `NEEDS_ATTENTION`. This makes the classification stable (a blocked session whose `status_detail` flickers won't oscillate into a terminal FAILED).

---

## 7. Real-world lessons (where spec met reality)

These are the most valuable parts of the build — each is a live discovery, not a hypothetical.

**(a) `outcome` is optimistic — completion must be evidence-based.** The brief said "PR array non-empty OR `outcome==pr_opened` → COMPLETED." Live, Devin set `outcome=pr_opened` *while still writing tests* (empty PR array). Trusting the enum marked the row done and posted `✅ PR opened: ⟨blank⟩`. **Fix:** require a real PR artifact; never trust the enum alone. *Trust the work product, not the self-report.*

**(b) Suspend ≠ fail.** Idle sessions get auto-suspended for inactivity to save compute. The brief said "suspended, no PR → FAILED." But suspend is a **resumable pause** — a suspended session was woken and shipped its PR. **Fix:** `suspended → NEEDS_ATTENTION`. *Distinguish "dead" from "paused"; paused work is recoverable and must not be silently written off.*

**(c) `blocked` is an escalation, not a failure.** The prompt tells Devin to stop and report `blocked` rather than force an unsafe change. Mapping `blocked → FAILED` mislabels correct, safe behavior as failure — and because a session's `status_detail` flickers, #2 oscillated between `NEEDS_ATTENTION` and a sticky `FAILED`. **Fix:** `blocked` (like `suspended` and `waiting_*`) maps to `NEEDS_ATTENTION`, checked before `exit/error`; `FAILED` now means only that the session itself crashed. Separately, `no_change_needed` gets its own terminal `NO_CHANGE` ("verified clean") state. *Principle: reserve FAILED for genuine faults — a safe refusal and a clean bill of health are successes, not failures.*

Two conditions that aren't bugs but invite questions:
- **ACUs read `0.0`** — Devin Review free trial; ACUs bill on paid plans. Plumbing is correct; it's a data condition. Cite list price for the cost story.
- **Time-to-fix is detection-based.** `completed_at` is stamped when the poller sees the PR (or, when corrected, the PR's real `created_at`). Idle time between launch and PR inflates it — which is exactly why **median** (robust to outliers) is the headline, not mean.

---

## 8. Concurrency & async

One event loop (uvicorn) runs the FastAPI handlers and the poll loop. Handlers are `async` and return in milliseconds. The poll loop is the only long-running thing and wraps its synchronous work in `asyncio.to_thread`, so it never blocks request handling. The concurrency *cap* is application-level backpressure enforced in `maybe_launch` — you don't fire 50 sessions at once and blow past org limits or budget.

---

## 9. Security

- Secrets live only in `.env` (gitignored, verified untracked). `.env.example` documents the shape.
- The webhook is HMAC-SHA256 verified over the raw body with `compare_digest`; unsigned/mismatched → 401. That's the inbound auth boundary.
- Outbound tokens go as `Bearer` headers, never logged (`config.masked()` available for diagnostics).
- Honest gaps for a real deployment: `/simulate/*` and `/status` are unauthenticated (fine for a local demo; gate them in prod), and the webhook needs a public tunnel (ngrok/smee) for real GitHub delivery — the simulate path is the demo substitute and runs identical code.

---

## 10. Real vs. synthetic

The **issue categories are 100% real** classes of backlog work. The **specific CVE IDs are synthetic** for the exercise (Devin's own reasoning flagged them). What matters: issues were scoped so Devin *discovers* the fix (runs `pip-audit` itself) rather than being handed it — making the pattern byte-identical to a real Snyk/Dependabot signal. `superset/utils/version.py`'s broad-except blocks and `dates.py`'s missing tests were **real conditions in the actual code**, and Devin's fixes (PR #7, PR #8) are real, reviewable remediations. An agent that recognizes a staged CVE and still ships the correct minimal PR is a strength, not a hole.

---

## 11. File map

```
devin-remediation-orchestrator/
├── docker-compose.yml     # api + dashboard, shared /data volume
├── Dockerfile             # python:3.11-slim, one image
├── .env.example           # secret shape (copy to .env)
├── requirements.txt
├── README.md              # pitch, quickstart, how Devin is used
├── PLAIN_ENGLISH.md       # VP-facing, no-jargon explanation
├── ARCHITECTURE.md        # this document
├── DEMO_EVIDENCE.md       # recording cheat-sheet (ask → proof → camera)
├── app/
│   ├── config.py          # env loading (single chokepoint)
│   ├── db.py              # SQLite (WAL) init + CRUD
│   ├── devin_client.py    # Devin v3 wrapper (create/get/message, retry)
│   ├── github_client.py   # GitHub REST wrapper (issues, comments, labels)
│   ├── orchestrator.py    # enqueue, maybe_launch, poll loop, state machine
│   └── main.py            # FastAPI: webhook + simulate endpoints, poller lifespan
├── dashboard/app.py       # Streamlit dashboard (read-only)
└── scripts/create_issues.py  # seed labeled issues in the fork
```
