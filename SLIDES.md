# Loom slides + talk track

Per Oscar: **index on business impact. Timing is 1 min current state / 2–3 min demo / 1 min wrap.** Persona = engineering *leader*, not just an engineer. Two simple slides bookend a pre-run demo.

---

## SLIDE 1 — CURRENT STATE  (≈ 1:00)

**Title:** The backlog nobody staffs

**Visual:** a growing "Unstaffed backlog" bar (security patches, dependency bumps, code-quality debt, missing tests, doc rot) with a `$` counter and a red "risk accumulating" clock.

**What I'm solving.** Every engineering org carries a class of work that's individually trivial and collectively enormous: CVE patches, dependency upgrades, silent exception handlers, missing tests, stale docs. It's real work, it's never the roadmap, and it only shrinks when a senior engineer donates a Friday.

**Context (the issues).** Your team runs Superset — 21,000+ commits, hundreds of dependencies. Dependency chores and quality debt land weekly. I filed real issues across four categories in a fork to represent exactly this backlog.

**Cost of doing nothing (say the number):**
> A 200-engineer org carries ~60 of these a quarter, ~2 loaded engineer-hours each ≈ **120 hours ≈ ~$18K/quarter** of senior-engineer time — spent on work nobody wants. And because it competes with the roadmap and loses, **it often doesn't get done at all**, so unpatched CVEs and quality debt keep compounding. The cost isn't just the hours — it's the risk that accrues while the queue sits.

**Transition line:** *"So I asked: what if that entire class of work drained continuously, without taking a single engineer off the roadmap?"*

---

## DEMO  (≈ 2:30 — the middle, keep it moving)

Keep **app.devin.ai visible** throughout (evaluators built it — showing it work is free points).

1. **The event (10s).** Terminal: `curl -X POST localhost:8000/simulate/issue/12` → `{"enqueued":12}`. *"The trigger is an event. Here it's a label; in production it's a Snyk finding, a Sentry alert, a Jira ticket — same endpoint."*
2. **Devin working (20s).** Cut to app.devin.ai: the new session cloning Superset. *"My orchestrator created a Devin session over the v3 API — with a structured-output schema, so it returns machine-readable results, not chat."*
3. **A finished result (40s).** Cut to a pre-completed PR (#6 flask CVE): `Fixes #1`, one-package diff, CVE named. *"I never told it which package — it ran pip-audit itself, found the advisory, scoped the fix, and even flagged a second CVE it safely left alone. That's an agent, not a script."*
4. **The leader's view (40s).** Dashboard: issues detected, PRs open, success rate, median time-to-fix, cost. *"This is how a leader knows it's working."* Point at **needs-attention (#2)**: *"when Devin can't fix it safely, it doesn't guess — it escalates. The system knows when it doesn't know."*
5. **Devin-native observability (20s).** Scroll to the "Devin-native analytics" panel. *"And this isn't just my dashboard — this bottom panel pulls straight from Devin's own analytics API: `/sessions/insights` and `/consumption/daily`. I'm not just calling the session API to create work; I'm using Devin's org-level observability — session sizing, message counts, ACU consumption — as first-class data. The platform already exposes what a leader needs to measure."*
6. **Breadth (20s).** *"Four categories, three outcome types: five shipped PRs, one safe escalation, two verified-clean. It doesn't just fix — it fixes, escalates, and verifies."*

> Never wait on the live session. Trigger #12, cut away immediately.

---

## SLIDE 2 — IDEAL STATE  (≈ 1:00)

**Title:** Continuous remediation, measured

**Visual:** the same backlog bar draining to near-zero; a before/after table; the four Devin platform pillars.

**Before → after (the outcomes table):**

| | Before | After (this system) |
|---|---|---|
| Who does it | A senior eng's donated Friday | A Devin session, on an event |
| Time-to-fix | Weeks in backlog | **Minutes** (median under 5 min this run) |
| Cost | ~$18K/quarter of eng time | A few dollars of compute |
| Visibility | Gut feel | A live funnel: throughput, success %, cost |
| Coverage | One heroic sprint | 4 categories, continuous |

**This run's proof:** 5 PRs shipped · 100% success · median under 5 min · 1 safe escalation · 2 verified-clean. *(Present the live dashboard for exact current figures.)*

**Platform, not tool (Oscar's heaviest point):** *"What I hand-built — a scheduler that fires sessions on an event and gates PRs on review — is a manual version of what Devin already productizes: Automations, Devin Review as the merge gate, Wiki so context compounds. The fact that I rebuilt a slice of the platform in an afternoon with the public API is the point: the primitive is general enough that the platform is the obvious next layer."*

**Next steps (a real engagement):** wire the trigger to your real signal (Snyk / Dependabot / Jira) → add Devin Review as the merge gate → point it at your top three repos → let the dashboard prove throughput for 30 days.

**Close (deliver with energy):** *"This took one engineer an afternoon and Devin's public API. Same webhook, new event source, and the same system drains CI failures, flaky tests, upgrade migrations. Minimal effort got us this far — so imagine how the value compounds across the whole backlog."*

---

## Timing discipline (Oscar's #1)
- **1:00** current state — land the `$18K/quarter` and the risk.
- **2:30** demo — biz narration over the tech; don't explain the state machine.
- **1:00** ideal state + close — the numbers, the platform line, the compounding close.
- Rehearse to **4:45**. If long, cut from the demo, never from the close.
- The bug-fix war stories (evidence-based completion, suspend≠fail, blocked=escalation) are **Q&A material, not Loom material.**
