# ControlPlane

**A consequence-aware control plane for enterprise AI.**

Every other tool in this space asks *"is this text bad?"* ControlPlane asks
*"what is this about to do, and what happens if it is wrong?"* — then prices
that, routes on the price, and writes a receipt you can replay.

---

## Run it

```powershell
pip install -r requirements.txt
python -m uvicorn python.controlplane.api:app --port 8000
```

Then open:

| URL | For | Audience |
|---|---|---|
| <http://localhost:8000/chat> | **User page** — the employee-facing assistant every decision is about | an employee |
| <http://localhost:8000/> | **AI portfolio** — five systems, owners, budgets, status | the accountable executive |
| <http://localhost:8000/console> | **Mission Control** — live stream, receipts, controls, scenario bench | Arun, who operates it |
| <http://localhost:8000/review> | **Review** — questions stopped before the model, waiting on a human | a human controller |
| <http://localhost:8000/advisor> | **Advisories** — per-department briefings: the budget forecast, the specific fix, and the email that delivers it | each system's named owner |
| <http://localhost:8000/developer> | **Developer view** — the policy in force, the arithmetic behind a score, how to integrate | the team whose system is governed |
| <http://localhost:8000/docs> | OpenAPI | |
| <http://localhost:8000/health> | Provider, decision count, whether the data is synthetic | |

Six surfaces because there are six questions, asked by six different people.
*Can I trust this answer?* *What have we got and is any of it on fire?* *What is
happening right now and what do I do about it?* *Should this question have been
asked at all?* *What should I change, and when do I run out of budget?* *Why was
I flagged?* One page answering all six answers none of them well.

`python/controlplane/api.py` **is the app.** There is one runtime. `legacy/`
holds the superseded scaffold and is imported by nothing — see
[`legacy/README.md`](legacy/README.md) for what was wrong with it.

### Tests

```powershell
python -m pytest test/ -q
```

369 tests. Each one names the property it protects, including an
end-to-end HTTP suite that drives **the exact requests the browser issues**, so
the console and the server can never silently disagree about authentication
again.

And the adjudicator has its own labelled evaluation set, because "you used a
model to check a model" deserves a number rather than an assurance:

```powershell
python -m python.controlplane.judge_eval          # the deterministic judge, 0 tokens
python -m python.controlplane.judge_eval --live   # whatever provider is configured
```

Sixteen labelled cases, nine of them deliberately clean. It reports catch rate
and false alarm rate separately, because for a checker the false alarm is the
expensive error.

### Live agent (optional)

The offline provider is the reference runtime and needs no network. To run the
real model instead:

```powershell
$env:CONTROLPLANE_PROVIDER = "gemini"
$env:GEMINI_API_KEY = "..."        # never commit this; use .env, which is gitignored
python -m uvicorn python.controlplane.api:app --port 8000
```

`httpx` is imported lazily inside the Gemini provider, so the offline runtime
works with it absent. A test asserts that by hiding `httpx` from the import
system.

---

## The idea, in one page

```
risk_price = P(failure) × blast_radius × 100
```

**Blast radius is derived, never declared.** An application says what it thinks
it is doing; the tool binding proves what it can actually do. If those disagree
on an irreversible action, the action is refused — and the text is handed back
as a draft rather than destroyed.

```
ACTION_RADIUS   read 0.10 · draft 0.35 · advise 0.70 · decide 0.90 · execute 1.00
                × 1.15 external audience · × 1.2 regulated · capped at 1.0
IRREVERSIBLE    {decide, execute}
```

**P(failure) is noisy-OR at half weight** on the residual, so a second
independent signal matters without four weak signals summing to certainty.

**Four routes:** `pass` · `repair` · `escalate` · `block`, against thresholds
from the resolved policy snapshot — base profile + jurisdiction overlay +
active control overlays. Overlays only ever tighten; a test proves that for
every profile × jurisdiction combination we ship.

**Two clocks, not one.** `decision_latency` is what the user waits.
`verification_latency` is when the checking actually finished. Conflating them
is how a governance product ends up claiming a budget it does not keep.

**Absence is explicit.** A detector has a *status* as well as a score:
`completed · timed_out · failed · not_configured · skipped_by_policy ·
queued_async · completed_async · stale`. A check that did not run is never
priced as though it returned zero.

**Governance completeness is consequence-weighted** —
`Σ(blast_radius × fully_governed) / Σ(blast_radius)` — and reports
`not_available` at zero decisions rather than 100%.

**Two gates, not one.** The **question** is checked before the model is called —
injection, pasted personal data, bulk-export requests, out-of-scope intent — all
deterministic and local, so a refused question costs **zero tokens**. The
**answer** is checked after. A flagged answer goes back to the person who asked,
with what was found; a flagged question goes to a human who passes or blocks it.

**Evidence is graded, and its absence is priced.** `authoritative` (a chunk of a
document you own) · `system_of_record` (a live lookup) · `parametric` (the
model's memory, unverifiable by construction). The tier required rises with the
action class: an irreversible action resting on the model's memory is refused
whatever it scored. When evidence is weak *and* the price is already high, a
second model adjudicates claim by claim — triggered, advisory, fail-closed, and
recorded so replay stays exact.

**Fleet status is ternary:** `governed · breaching · unknown`. Silence is not
health. A system that stopped reporting goes grey, never green.

**A warning is worth nothing without a remedy.** Every advisory carries what is
wrong, **what to change in your code**, and what happens if nothing changes —
and a burn-rate forecast says when the budget runs out rather than reporting
after it already has. A system can read `governed` on its card and `two days of
budget left` in its forecast at the same time; that gap is the point.

---

## What is honest about this build

- The ledger holds the **full decision receipt**, not a summary, and state is
  **recovered from it** on start. Seeding happens only when there is nothing to
  recover, and `/health` reports `containsSyntheticSeedData`.
- Replay uses `detectorsAtDecision` — the evidence **as it stood when the
  decision was made**. Deferred verification amends the record but never that
  snapshot, which is what makes "reproduce this decision" deterministic rather
  than approximately true.
- A reproduce compares **eight canonical fields**, including the confidence
  band and the side-effect state. Comparing only action and price would let a
  replay report "identical" while showing two different bands.
- A ledger write failure downgrades the decision to
  `ungoverned_due_to_failure` and surfaces in the ops strip. It is never
  swallowed.
- Deferred work that could not be queued is recorded as `queue_saturated`,
  never left looking merely pending.
- The agent cites **source IDs**. The server resolves them against an immutable
  corpus, so a model cannot author the evidence it is graded against. A cited ID
  that does not exist becomes an `unverifiable` finding.
- Every decision states its **side effect** explicitly: `withheld ·
  held_for_human · released · performed`. A blocked draft and a blocked
  `execute` are not the same event.
- Notifying an owner is **itself a governed action**: who sent it, to whom, what
  it said and whether it was delivered all land in the ledger. A briefing that
  silently failed to arrive is recorded as `notification.failed`, never as
  nothing. No credential ever reaches the ledger, the API or the screen.
- The burn-rate forecast **declines to project** when there is not enough of the
  billing month elapsed, rather than dividing a month-to-date figure by a few
  hours and calling every system critical.

## What we do not claim

- **Grounding** is lexical support checking plus numeric conflict detection, not
  semantic verification.
- **Privacy** finds format-valid candidate identifiers — Luhn for 13–19 digit
  card numbers, Verhoeff for 12-digit national IDs — not confirmed personal
  data. A random 17-digit number fails the checksum and is not flagged.
- **Fairness** is a bounded counterfactual probe over four substitution pairs,
  not a fairness guarantee.
- The **operator token** is a prototype boundary, not enterprise IAM.
- The ledger is **tamper-evident** under protected key management — a SHA-256
  chain with an HMAC signature, an in-process lock and a cross-process file
  lock. It is not tamper-proof and we will not call it that.
- Seeded history is **synthetic demonstration data** and is labelled as such
  everywhere it appears.

---

## Layout

| Path | Role |
|---|---|
| `python/controlplane/api.py` | HTTP surface. **This is the app.** |
| `python/controlplane/plane.py` | Turn orchestration, projections, advisor, controls, ledger recovery |
| `python/controlplane/gate.py` | Enforced deadline, pools, pricing, routing, governance status, policy composition |
| `python/controlplane/registry.py` | Applications, tool bindings, capability derivation |
| `python/controlplane/detectors.py` | Grounding, privacy, fairness, cost — score **and** status |
| `python/controlplane/providers/` | Agent seam: `offline` (deterministic) and `gemini` (live) |
| `python/controlplane/org.py` | Five departments, tool bindings, addressable source corpus |
| `python/controlplane/overview.html` | AI portfolio — the landing page |
| `python/controlplane/dashboard.html` | Mission Control |
| `python/controlplane/chat.html` | The user page — the employee-facing assistant |
| `python/controlplane/review.html` | Question review — held questions, passed or blocked by a human |
| `python/controlplane/advisor.html` | Advisories and owner briefings |
| `python/controlplane/ingress.py` | The gate on the **question**, before a token is spent |
| `python/controlplane/ingest.py` | Documents in, citable chunks out. BM25, deterministic |
| `python/controlplane/adjudicator.py` | The second opinion, for what documents cannot settle. Two charges, calibrated, advisory by construction |
| `python/controlplane/judge_cases.py` | Sixteen labelled cases the adjudicator is scored against |
| `python/controlplane/judge_eval.py` | Catch rate, false alarm rate, confusion matrix |
| `python/controlplane/scope.py` | Is this question this assistant's business? Derived from its own documents |
| `python/controlplane/purpose.py` | Every sentence true, the reader's purpose defeated |
| `python/controlplane/briefing.py` | The owner briefing, rendered as HTML and plain text |
| `python/controlplane/notify.py` | Email transport — HTTPS API and/or SMTP, with automatic fallback |
| `python/controlplane/env.py` | Dependency-free `.env` loader; a real environment variable always wins |
| `python/controlplane/developer.html` | Developer view |
| `python/controlplane/ledger.py` | Hash-chained, signed, lock-protected append-only log |
| `seed_history.py` | Synthetic ambient history for a cold start |
| `smoke.py` | One-shot run of every scenario, printed |
| `test/` | The suite |
| `legacy/` | Superseded scaffold. Imported by nothing. |

## Operator token

Mutating routes require two headers:

```
X-ControlPlane-Token: operator-dev-token     # CONTROLPLANE_OPERATOR_TOKEN
X-ControlPlane-Actor: Arun Mehta
```

Human approval is the **authenticated actor**, not a caller-supplied string.
The console attributes control actions to the operator named in the masthead and
ambient simulator traffic to `ambient-simulator`, so the ledger never records a
machine's traffic under a person's name.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `CONTROLPLANE_PROVIDER` | `offline` | `offline` or `gemini` |
| `GEMINI_API_KEY` | — | required for `gemini` |
| `CONTROLPLANE_OPERATOR_TOKEN` | `operator-dev-token` | token for mutating routes |
| `CONTROLPLANE_SEED_TURNS` | `110` | synthetic history on a cold start |
| `CONTROLPLANE_AGENT_TIMEOUT_S` | `20` | the agent's own budget, separate from the detector deadline |
| `LEDGER_PATH` | `data/ledger.jsonl` | append-only log |
| `LEDGER_SIGNING_KEY` | `development-only` | HMAC key |
