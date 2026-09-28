# ControlPlane v2 — Locked Scope

Team Challenge_24 · Problem Track 1 · Grand Finale
Closes four rounds of review. This is the build contract.

---

# PART 1 — The subtraction pass

Four reviews have now proposed, in aggregate: 16 agents, 4 governors, 3
monitors, 8 detector statuses, 5 governance statuses, 3 lag measures, 2
latencies, 9 health states, 15 control types, 21 ledger event types, 10 rule
categories, 6 recommendation lifecycle states, ~60 fleet metrics, 10
implementation phases, and 7 demo beats.

Every individual item is defensible. **The aggregate is not buildable and, more
importantly, is not presentable.** A ten-minute slot with a jury seeing this for
the first time cannot absorb sixty metrics. The failure mode has changed: it is
no longer under-ambition, it is a system so broad that nothing lands.

So the most useful thing I can do in this round is **cut**, and then defend
what survives.

## The irreducible core — five things

If only these ship, you have a coherent, novel, defensible product:

| # | Thing | Why it is non-negotiable |
|---|---|---|
| **1** | **Enforced deadline + real deferred path + detector status** | It is a correctness fix for claims you have already made in writing. Everything else is built on truthful execution. |
| **2** | **Effective capability from the tool registry** | Blast radius is your whole idea. If its input can be forged by the caller, the idea is decorative. |
| **3** | **Governance completeness + the Unknown state** | "We checked and it was fine" ≠ "we released without checking" ≠ "we have no idea". Nobody else in the market makes this distinction. |
| **4** | **Fleet: exposure, two budgets, health, scoped expiring controls, deterministic arbitration** | This is Sir's reframe and the word "control" in your name. |
| **5** | **Replay: simulate · reproduce · shadow** | One engine, three products. Highest leverage code in the plan. |

## Demoted to "we can, and here is the design"

Not built. Answered in Q&A with one sentence each.

Multi-tenancy · data residency · OpenTelemetry · distributed projections ·
durable queue · provider fallback · model downgrade · throttling · shadow-AI
network discovery · asymmetric signing · criticality weighting · an Assurance
Governor as a separate agent (fold it into Safety) · remediation-lag SLOs ·
recommendation supersession chains.

**Saying "we designed for it and deliberately didn't build it" is a strength.**
Saying "we built forty things" invites the jury to find the three that are thin.

---

# PART 2 — What review 4 adds that is genuinely better

Five things. I am adopting all five.

## ✅ 1. "Silence is not health" — the best new idea in four rounds

> *"A disconnected application must not appear healthy because it generated no
> new events. Track separately: no traffic · stale source · detector
> unavailable · not registered · excluded by policy · fully governed."*

This is a real failure mode in every monitoring product ever built, and it is
subtle enough that most teams never think of it. A system that has stopped
reporting is not quiet — it may have been **moved off governance entirely**,
which is a security event, not a calm week.

I am extending it into the top-level display (Part 4, Idea A) because it
deserves to be more than a footnote.

## ✅ 2. Stale exposure rate — sharper than my "governance lag"

I proposed `4,217 decisions awaiting verification`. Review 4 proposes:

```
stale_exposure_rate =
    risk-weighted exposure during incomplete governance
  / total risk-weighted exposure
```

**This is your own exposure principle applied recursively to your own backlog.**
Four thousand unverified low-risk reads is an ops annoyance. Forty unverified
payment executions is an emergency. A raw count cannot tell them apart; this
can. Adopt it as the headline and keep the raw count as a sub-figure.

## ✅ 3. Completeness ≠ compliance ≠ enforcement coverage

Three genuinely distinct things that I had blurred:

```
Completeness   Did we have the evidence required to make and reconstruct
               the decision?
Compliance     Did the decision satisfy the applicable policy?
Coverage       Was the control actually in the request path at all?
```

An application can be **fully governed and non-compliant** — all evidence
present, decision was to block. It can also be **compliant-looking but
incompletely governed** — a required detector was unavailable. Conflating them
is exactly the sloppiness a compliance-literate judge would catch.

## ✅ 4. Rules must return `insufficient_evidence`, never infer safety from absence

The logical partner to detector status, and I had missed it. A rule whose inputs
are stale or missing returns `unknown` — it does not return "fine." This is the
same discipline as `score=None`, applied one layer up.

## ✅ 5. Shadow mode promotion gates, and careful commercial framing

A shadow policy must not auto-promote. Require: evidence completeness above
threshold · unknown rate below threshold · reproducible evaluations · an agreed
observation window · owner approval · a named rollback version.

And the framing caution is right: shadow mode is **a low-risk assessment and
rollout mechanism, not proof of compliance.** Over-claiming there is exactly the
kind of thing a judge punctures.

---

# PART 3 — Where I hold the line against review 4

## ❌ It has quietly deleted the agentic architecture

Across its two halves the governors become "monitors," the supervisor becomes
"deterministic policy code," and nothing in the system is described as an agent.
That is technically defensible and **strategically wrong for you.** Sir named
architecture as a scoring axis and steered you explicitly toward agentic design.

The resolution is not to add agent labels back. It is to be precise about where
the agency actually lives:

> **The agentic content of this system is that the governors pursue objectives
> that genuinely conflict, can be refused, and can be overruled — and something
> has to referee. The referee is deterministic and its reasoning is signed. You
> cannot write that as a pipeline.**

Three governor agents. One deterministic supervisor. Detectors and monitors are
evidence producers, and calling them agents would be the tell. That is honest
*and* agentic, and I am not moving off it.

## ❌ Three lags is one too many for your architecture

Review 4 wants decision lag, verification lag and remediation lag. But its
`decision_lag = decision_at − change_observed_at` is, for a **synchronous gate**,
the same quantity as decision latency. It is a meaningful metric for a batch
monitoring product; here it is a duplicate under another name.

**Ship two latencies and one lag:** decision latency, verification latency,
remediation lag. Drop decision lag.

## ❌ Seven demo beats, again

Every review has grown the demo. Ten minutes, first-time audience. **Five
beats.** Part 7.

## ⚠️ And a scope warning

Review 4 reintroduces `tenant_id`, data classification, criticality, escalation
contacts, OpenTelemetry and distributed projections. Each is right for
production and wrong for this week. They belong in the "we designed for it"
answer, not in `systems.yaml`.

---

# PART 4 — Three ideas of my own

## 💡 A. Ternary status: Governed · Breaching · **Unknown**

Review 4's "silence is not health" deserves to be the top-level visual, not a
caveat. Every monitoring dashboard in the world is binary — fine or alert — and
that binary is precisely what makes absence of data render as safety.

Make the fleet ternary, and make Unknown **grey, never green**:

```
● GOVERNED     evidence complete, inside limits
● BREACHING    evidence complete, outside limits
◐ UNKNOWN      we cannot currently say
                 no traffic · source stale · detector unavailable
                 · unregistered · verification backlog · excluded by policy
```

> **"The most dangerous colour on an enterprise AI dashboard is green when it
> should be grey. A system that stopped reporting hasn't had a quiet week — it
> may have been moved off governance entirely."**

That is a memorable, original sentence, it packages the single best insight from
four rounds of review, and no competitor's dashboard can say it.

## 💡 B. "Reproduce this decision" — a button, not a claim

You will have: a hash-chained ledger, versioned policy snapshots, and a replay
engine. Those three combine into something none of the reviews noticed.

**On any ledger entry, a button.** It replays that decision under the policy
snapshot that was active at the time and shows the result is bit-identical.

```
Decision 1,842 · 14 Sept · finance-decision-assistant
  recorded:   ESCALATE · price 56 · band 49–63 · policy v18+in
  reproduced: ESCALATE · price 56 · band 49–63 · policy v18+in     ✓ identical
```

**This turns "auditable" from an adjective into an affordance.** It is the
literal answer to the question an auditor actually asks — *"prove this decision
was what you say it was"* — and it costs you almost nothing, because every piece
already exists.

It also silently proves three claims at once: the ledger is intact, policy
snapshots are versioned, and the engine is deterministic.

## 💡 C. Three SLOs instead of sixty metrics

The metric sprawl is the biggest presentation risk in this plan. Collapse it
into three numbers a customer could put in a contract:

```
DECISION SLO       p95 decision latency ≤ the policy's own budget
COMPLETENESS SLO   ≥ 99% of decisions fully governed
FRESHNESS SLO      p95 verification latency ≤ 5 minutes
                   and stale exposure rate ≤ 1%
```

Everything else becomes drill-down beneath one of these three. **This is how
real platform products are sold**, it makes the dashboard legible in five
seconds, and it is the difference between "we measure sixty things" and "we
guarantee three."

> "We don't ask you to trust our detectors. We publish three numbers you could
> put in a contract, and every one of them is reproducible from the ledger."

---

# PART 5 — Locked architecture

```
┌── DATA PLANE · per request · bounded · deterministic ────────────────┐
│ identity → EFFECTIVE capability (registry, not caller)               │
│ → resolved snapshot (base + jurisdiction + control)                  │
│ → provider → inline detectors, DEADLINE ENFORCED                     │
│ → blast-radius pricing → pass/repair/escalate/block                  │
│ → governance status → evidence                                        │
│ ONE authoritative router. The fleet layer changes its INPUTS only.   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
          ┌─────────────────────▼─────────────────────┐
          │   APPEND-ONLY LEDGER  (authoritative)     │
          │   decisions · amendments · arbitrations   │
          └─────────────────────┬─────────────────────┘
                                │  projections are rebuildable caches
┌── CONTROL PLANE · per system · asynchronous ─────────────────────────┐
│ monitors → SAFETY / RESOURCE governors (recommend, may be refused)   │
│ → DETERMINISTIC SUPERVISOR (arbitrates, actuates)                    │
│ → scoped · versioned · expiring · reversible controls                │
│ → effectiveness measurement                                           │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌── IMPROVEMENT ───────────────────────────────────────────────────────┐
│ human verdicts → bounded calibration                                 │
│ REPLAY ENGINE → simulate · reproduce · shadow                        │
└──────────────────────────────────────────────────────────────────────┘
```

**Agents:** Supervisor (deterministic authority) · Safety Governor · Resource
Governor. Assurance folds into Safety — three boxes, not four.

**Evidence producers:** detectors (per response) · monitors (over time). Not
agents.

> **Agents analyse and recommend. Deterministic code arbitrates. Humans approve
> irreversible fleet actions.**

**Resource Governor manages three currencies:** rupees · reviewer-minutes ·
verification capacity. Everyone manages the first. Your own research says the
second is 94.8% of what oversight costs. The third did not exist until you fixed
the async path.

## Arbitration — four rules, strict precedence, no model in the loop

```
1 · HARD GATES ARE NOT TRADEABLE
    unauthorised execution · confirmed PII leakage · missing mandatory approval
    · contradiction of the source of record · a mandatory detector that did not
    complete on an irreversible action

2 · REVERSIBILITY DOMINATES
    on irreversible actions — by EFFECTIVE capability, never declared —
    Safety outranks Resource. Always.

3 · BELOW THAT LINE, PRICE THE TRADE
    Δ(exposure) × blast_radius  vs  Δ(₹) + Δ(reviewer-min) + Δ(verification)

4 · DEGRADE TOWARDS EVIDENCE, NEVER TOWARDS SILENCE
    record the unmet constraint, lower the governance status, show it
```

Rule 2 is **your blast-radius idea promoted from scoring one response to
governing the whole plane.** Every arbitration is ledgered.

---

# PART 6 — Locked contracts

## Detector result

```python
DetectorResult(name, score: float|None, confidence: float|None,
               status: Literal["completed","timed_out","failed","not_configured",
                               "skipped_by_policy","queued_async",
                               "completed_async","stale"],
               execution_mode, started_at, completed_at,
               latency_ms, queue_delay_ms, evidence_refs, error_code)
```

`score=0` may never mean "failed." That is the worst confusion available in the
system, and on a privacy detector it is dangerous.

## Request path

```python
done, pending = wait(inline_futures, timeout=budget_s)     # ENFORCED
results  = [f.result() for f in done]
results += [DetectorResult(n, score=None, status="timed_out") for n in pending]

gov = governance_status(results, policy, effective_action)  # YAML table
decision = route(answer, results, price(...), policy, effective_action)
emit_evidence(...)
return decision                                             # ← returns HERE

# abandoned + async work → DEFERRED pool (separate executor, bounded queue)
```

**Two pools, and this matters more than it looks.** Python cannot kill a running
thread. If abandoned work shares the inline pool, it keeps holding slots, the
pool saturates under load, and the deadline you just enforced becomes
unenforceable again because new requests queue before they can start.

```python
_INLINE_POOL   = ThreadPoolExecutor(max_workers=8)
_DEFERRED_POOL = ThreadPoolExecutor(max_workers=4)
_DEFERRED_Q    = BoundedQueue(maxsize=N)    # saturation is visible, never silent
```

Three invariants, each a test:

1. The deadline is a guarantee, not a measurement.
2. Deferred work amends evidence. It never mutates a returned response.
3. Absence is explicit. A check that did not happen is recorded as such.

## Governance status — YAML-driven, not hardcoded

| Situation | read/draft | advise/decide | execute |
|---|---|---|---|
| advisory detector timed out | release, marked | escalate if relevant | approval or block |
| **mandatory** detector timed out | escalate | block or escalate | **fail closed** |
| advisory detector failed | release, marked | escalate if policy says | approval |
| capability check unavailable | **no execution** | escalate | **block** |

## Effective capability

```yaml
- system_id: it-ops-agent
  owner: Priya Nair
  policy_profile: decision_support
  jurisdiction: in
  budget_inr_month: 20000
  review_minutes_week: 180
  allowed_capabilities: [read, draft, advise]
  allowed_tools:
    - name: restart_service
      effective_action: execute
      reversible: false
      approval_required: true
      allowed_environments: [staging]     # NOT production
```

Ledger records `declared_action_class`, `effective_action_class`,
`capability_mismatch`. Unknown `system_id` → strictest profile, shown as
`unregistered`. **You notice; you do not claim to discover.**

## Recommendation — deterministic, cited, with a lifecycle

```json
{"recommendation_id": "rec-42", "subject": "marketing-copilot",
 "rule_id": "COST.DUPLICATE_PROMPTS", "rule_version": "3",
 "evidence": {"duplicate_share": 0.68, "cache_hit_rate": 0.32, "spend_inr": 18400},
 "derivation": "deterministic", "evidence_refs": ["ledger:1842"],
 "suggested_control": "enable_cache",
 "expected_effect": {"monthly_savings_inr": 6100},
 "status": "open", "valid_until": "..."}
```

Lifecycle: `open → accepted | rejected | waived | resolved | superseded`. A
waiver carries a reason and is itself a governed event.

**A model may phrase a recommendation. It may never derive one, select the rule,
set the severity, compute the saving, or authorise a control.** Missing or stale
inputs produce `insufficient_evidence`, never "fine."

## Controls

```
base + jurisdiction overlay + approved control overlay = resolved snapshot (versioned)
```

which is **the mechanism your EU and India overlays already implement.** Base
policy is never mutated.

Each control: scope · reason · evidence_refs · requested_by · rule_applied ·
approved_by · policy_version · starts_at · **expires_at** · **rollback** ·
expected_effect · observed_effect · status.

| Autonomous | Guarded | Human-approved |
|---|---|---|
| `REQUIRE_HUMAN` · `TIGHTEN_POLICY` · `PROMOTE_INLINE` · `RESTRICT_TOOL` · `ADD_CITATION` · `REDACT_OUTPUT` · `ENABLE_CACHE` · `LOWER_CONTEXT` · `ROUTE_CHEAPER` | `THROTTLE` · `DOWNGRADE_MODEL` · `FREEZE_SESSIONS` | `SUSPEND` · `QUARANTINE` · `RELAX_SAFETY` |

**Suspension stays human** — an autonomous agent that can unilaterally halt
production is a worse risk than the one it prevents. That is the identical
argument your own `router.py` docstring makes about rationing BLOCK. One
principle, two scales; an experienced judge notices.

---

# PART 7 — Build steps

**0 · Baseline.** Snapshot all 31 eval decisions. Define inert fleet mode.
*The gate on everything: inert fleet must reproduce v1 exactly, which is what
lets you say "the per-request decision is provably unchanged."*

**1 · Six failing tests, written first.**
```
slow inline detector      → returns at ~deadline, not after
timed-out detector        → no score, not read as clean
async detector            → does not delay evaluate() at all
mandatory detector fails  → cannot permit irreversible execution
declared=draft + execute tool → effective becomes execute
expired control           → no longer affects resolution
```

**2 · Detector result contract.** 8 statuses, timestamps, error codes.
**3 · Enforce the deadline.** `wait(timeout=budget_s)`.
**4 · Split the pools + bounded deferred queue + saturation visible.**
*3 without 4 is not a real fix.*
**5 · Two clocks.** `decision_latency`, `verification_latency`,
`verification_status: pending|complete`.
**6 · Governance status.** YAML mandatory/advisory per detector per action class.
**7 · Registry + effective capability.** Feed **effective** class to
`blast_radius()`. Record mismatch.
**8 · Replay engine.** *Read-only, zero risk, unlocks simulate + reproduce +
shadow. Build early — it is also your regression net for everything after.*
**9 · Fleet projections.** Rebuilt from ledger. Ternary status. Stale exposure.
**10 · Control objects + resolved snapshot.**
**11 · Monitors.** Pure functions over projections.
**12 · Safety + Resource Governors.** Typed recommendations, no authority.
**13 · Supervisor.** Rules 1–4, control lifecycle, human-approval gating.
**14 · Rule engine.** Rule ids, versions, `insufficient_evidence`, lifecycle.
**15 · Effectiveness evaluator.** Expected vs observed. Labelled *observed
before/after*, not causal.
**16 · UI.** Portfolio (three SLOs + ternary status) → application detail →
existing six tabs underneath. **Nothing deleted.** "Reproduce this decision"
button on every ledger entry.
**17 · Shadow report + promotion gates.**
**18 · Apply the ledger cross-process fix; rebuild clean.**
**19 · Verify the invariant.** Inert fleet ⇒ step 0's 31 decisions identical.
*The gate on shipping.*

Steps 8 and 9 are read-only and parallel with 11–13.

---

# PART 8 — The demo, five beats

**Land on the portfolio.** Five systems. Three SLOs across the top. Ternary
status. Priya's screen.

**1 · Consequence, not frequency.** `order-desk` 40 findings, green.
`finance-assistant` 3 findings, red.
> *"We don't count incidents. We price consequence."*

**2 · The lie.** ⭐ The IT agent calls `restart_service` in production declaring
`action_class: draft`. Effective capability resolves to `execute` from the tool
binding → blast radius 1.00 not 0.35 → hard gate → side effect blocked, safe
text preserved, mismatch recorded, system moves to `tool_restricted`.
> *"Every governance product trusts the application to declare what it's doing.
> We don't. Blast radius is the whole of our idea — if its input can be forged,
> the idea is decorative."*

**3 · Honest degradation, and the grey light.** ⭐ A detector blows the deadline.
Response returns on time; detector `timed_out`; record `partially_governed`;
deferred work completes and amends the ledger. **Both clocks on screen:**
decision 48 ms, record sealed 2.3 s. Then pan to a system sitting **grey**.
> *"Preparing for this we audited our own latency discipline and found we were
> reporting it rather than enforcing it. We fixed it. And the most dangerous
> colour on a dashboard like this is green when it should be grey — a system
> that stopped reporting hasn't had a quiet week."*

**4 · Conflict → arbitration → control.** Safety requests fairness inline
(flip rate rising); Resource vetoes (104% of budget). Effective class `decide` →
**Rule 2** → Safety wins. Signed arbitration record on screen. Then Arun's lens:
inside the money budget, **over** the reviewer-hour budget. He presses
**Suspend**, or raises the budget.

**5 · Prove it, then shadow it.** Click **Reproduce this decision** on a ledger
entry from two weeks ago — replayed under the policy snapshot active at the
time, bit-identical. Then: *"and here are a thousand answers from a system that
has never been governed. Nothing in its request path, no code change. This is
what we'd have caught."*

**Close.** One sentence on extensibility — the detector contract, the diff, the
test. Then stop.

---

# PART 9 — What we deliberately do not build

- **No LLM in enforcement or in deriving recommendations.** It may phrase; never
  derive. Judgement is used exactly where genuinely needed — the rationed judge
  above risk price 60, capped at 90 calls/1,000.
- **No autonomous suspension.**
- **No shadow-AI network discovery.** We flag unregistered traffic.
- **No second router.** The fleet layer changes the engine's *inputs*.
- **No database, multi-tenancy or auth.** JSONL keeps evidence readable with
  ordinary tools; at volume it becomes a real store, and we say so.
- **No causal claims** about control effectiveness — observed before/after.
- **No compliance claims from shadow mode** — it is an assessment and rollout
  mechanism, not proof of compliance.
- **The ledger is "tamper-evident under protected key management."** Hash
  chaining detects tampering and ordering breaks; HMAC authenticates holders of
  the shared secret; independent non-repudiation needs asymmetric signing. Never
  "tamper-proof."

---

# Three decisions, then I start

1. **Do you accept the subtraction?** Five core items, everything else demoted
   to "designed for, deliberately not built." My strong recommendation: yes.
   Four rounds of accumulation need one round of cutting.
2. **Three SLOs on the portfolio page as the primary display?** It is the
   difference between "we measure sixty things" and "we guarantee three."
3. **Who owns the UI?** One person.

---

## The thesis

> ControlPlane is a consequence-aware operating layer for enterprise AI. A
> deterministic gate prices every response and action by what it is about to
> **do** — derived from the tool it can actually call, never from what the
> caller claims — under a deadline it genuinely enforces, and records not just
> whether the answer was safe but whether the checking was complete. Above it, a
> control plane watches every AI system's exposure, spend, reviewer burden and
> verification backlog, and applies scoped, expiring, reversible controls when a
> system drifts; three governor agents pursue genuinely competing objectives and
> a deterministic supervisor arbitrates on reversibility. Every decision — the
> AI's and the control plane's own — is replayable evidence, so any of them can
> be reproduced on demand. And when we cannot say whether a system is safe, we
> say that, instead of showing green.
