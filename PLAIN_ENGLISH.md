# In plain English

*Explaining this system to a smart non-engineer — the way I'd say it out loud to a VP. Six short paragraphs, one per part of the brief.*

---

**1. The problem we're solving.** Every engineering team has a pile of small, important chores that never get done: security patches, library updates, cleaning up sloppy error handling, adding missing tests, fixing stale documentation. None of it is exciting, none of it is on the roadmap, so it only gets touched when a senior engineer sacrifices a Friday. The pile just grows. We built a system that drains that pile automatically and continuously — without pulling a single engineer off their real work.

**2. The work we pointed it at.** In our copy of Superset (a large, real open-source product with hundreds of dependencies), we filed five tickets across four kinds of chores: two security fixes (one Python dependency, one JavaScript dependency), one code-cleanup task (making silent errors visible), one testing task (covering an untested piece of code), and one documentation task. Deliberately, we did *not* tell the system how to fix anything — we described the problem the way a real ticket would, and let the agent figure out the specifics. For example, the security ticket just said "find the most serious vulnerable package and safely update it" — it never named the package.

**3. What actually happens.** When a ticket gets tagged, our system automatically wakes up Devin — Cognition's autonomous coding agent — and hands it that ticket. Devin then does what a real engineer would: it downloads the codebase, investigates, makes the smallest safe fix, checks its own work, and opens a pull request (a proposed code change) for a human to review. Our system tracks every step and posts updates back onto the original ticket, so the whole history lives where engineers already work. It handles several of these at once and queues the rest, exactly like scheduling a team.

**4. How a leader would know it's working.** We built a live dashboard that answers that in one glance: how many issues came in, how many are being worked, how many fixes are ready for review, the success rate, how long each fix took, and what it cost in compute. There's also a "needs attention" panel: when Devin is genuinely unsure — say, the only available fix would break something else — it doesn't guess. It stops and asks, and that shows up on the dashboard. A system that knows when it *doesn't* know is one you can actually trust.

**5. Why this needs Devin specifically, not a simpler tool.** Autocomplete tools help a human who is already doing the work. Devin *is* the one doing the work — cloning a huge codebase, orienting inside it, running the right checks, and shipping a reviewed change end to end, on its own. And because each Devin session is something we can start with a single programmatic command, we can run a whole fleet of them in parallel, tagged and measured, the way you'd spin up computing power. What we hand-built in an afternoon — trigger a session, gate the result on review — is exactly what Cognition already offers as a full platform. That's the tell: the building block is general enough that the platform is the obvious next step.

**6. What this becomes.** Today it drains five chores for a few dollars of compute, turning weeks-of-backlog into under-an-hour fixes. In a real engagement, we'd wire the trigger to your actual signals — your security scanner, your error tracker, your ticketing system — add automated review as the gate before a human ever looks, and point it at your busiest repositories. The dashboard proves the throughput. And the honest punchline: this took one person one afternoon using a public interface. That's the floor, not the ceiling — so imagine the same machine draining broken builds, flaky tests, and upgrade migrations across every team. The value compounds.

---

### The five issues, in plain terms

| # | Type | What we asked | What Devin did |
|---|------|---------------|----------------|
| 1 | Security (Python) | "Find the most serious vulnerable Python package and safely bump it." | Found the advisory itself, updated one package, opened a reviewed PR — and *noted* a second vulnerable package it deliberately left alone because there was no safe fix. |
| 2 | Security (JavaScript) | "Find a safe high-severity JavaScript fix." | Investigated, found the only available fix would break other things, and **honestly stopped and asked** rather than forcing it. |
| 3 | Code quality | "Make silently-swallowed errors visible in a utilities file." | Found real error-hiding code, replaced it so failures now surface, verified with the linter, opened a PR. |
| 4 | Testing | "Add tests to an untested utility module." | Picked an untested module, wrote ten passing tests covering edge cases, opened a PR — without touching the code under test. |
| 5 | Documentation | "Fix broken links and stale commands in the docs." | (Held for the live demo.) |

The takeaway: three produced real, reviewable fixes; one honestly reported it couldn't be done safely; and the fifth is our live demo. The "couldn't do it safely" case isn't a weakness — it's proof the fixes are real and the system won't fabricate work.
