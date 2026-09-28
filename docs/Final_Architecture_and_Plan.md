# ControlPlane v2 — Final Architecture, Reasoning, and Build Plan

Team Challenge_24 · Problem Track 1 · Grand Finale

---

# PART 1 — Two defects in your code, found while reviewing the proposals

Before any architecture discussion. I went back into `engine.py` to check one of
the other AI's claims and found two things that matter more than every
architectural opinion in this conversation combined, because **they contradict
statements you have already made in writing to an Accenture expert.**

## Defect 1 — the latency budget is annotated, not enforced

```python
futures = {_POOL.submit(_run_detector, n, ...): n for n in inline_names}
deadline = time.perf_counter() + budget_s
for fut in as_completed(futures, timeout=None):      # ← waits for ALL of them
    name = futures[fut]
    if time.perf_counter() > deadline:
        demoted.append(name)                          # ← only a label
    sig = fut.result()
    sig.ran_inline = name not in demoted
    signals.append(sig)                               # ← demoted signal still priced
```

`as_completed(..., timeout=None)` blocks until **every** future finishes. So:

- Inline work is **not** bounded by `latency_budget_ms`. A slow detector runs to
  completion and the request waits for it.
- A "demoted" detector's signal is **still appended and still priced**. Demotion
  changes one boolean on the record. It changes no behaviour.

Your `engine.py` docstring says: *"if the budget is exhausted the remaining
inline work is demoted to asynchronous and the response is routed on what we
have."* That is not what the code does.

## Defect 2 — the asynchronous detectors are not asynchronous

```python
decision = route(...)                       # decision is made here — correct

# --- asynchronous detectors: refine the record, never block release -------
for name in async_names:
    sig = _run_detector(name, provider, req, session_prompts)   # ← sequential,
    signals.append(sig)                                          #   in the request path
```

The **routing decision** is genuinely independent of these — that part is true
and well designed. But `evaluate()` does not return until they have all run,
**sequentially**, so the caller waits for them. For `customer_support` the async
set includes uncertainty (three resamples) and bias (up to three probes) — the
two most expensive detectors you have.

And `added_latency_ms = inline_elapsed_ms`, so **the async time is not counted
in the latency you report.** Your published p50 is inline-only.

## Why this is the most important thing in this document

You wrote to Rajesh Katta: *"Async detectors never block release."* And: *"The
inline versus asynchronous detector split is per policy and was one of the
harder things to get right."* He is an expert who has been invited to clone the
repo. `engine.py` is 200 lines and this is in the first half of the main
function.

**Finding this yourself and fixing it is worth more than any feature on any
list here.** It becomes a line you can say with total confidence:

> "While preparing for this we audited our own latency discipline and found we
> were *reporting* it rather than *enforcing* it. We fixed it. Here is the
> before and after."

A jury that hears a team say that believes everything else the team says.

## The fix — and it is small

```python
done, pending = wait(futures, timeout=budget_s)          # ← enforce the deadline
for fut in done:
    signals.append(fut.result())
for fut in pending:
    name = futures[fut]
    demoted.append(name)
    signals.append(Signal(name, score=None, confidence=None, status="timed_out"))
    DEFERRED.submit(name, req, on_complete=amend_ledger)  # truly deferred

# route on completed evidence only
decision = route(...)
return result                                            # ← returns now

# async_names go to the same deferred queue, never to the request path
```

Two consequences, both good:

1. The budget becomes a real guarantee — which is a much stronger claim than
   "we measure our overhead."
2. A timed-out detector becomes **explicitly absent**, not silently zero — which
   is the doorway to the single best idea in the other AI's document, below.

---

# PART 2 — Scoring the other AI's proposals

It did strong work. Here is my honest verdict on each item, with reasoning.

## ✅ ADOPT — five ideas that genuinely improve the system

### 1. The trusted capability model — **the best idea in this entire conversation**

> Don't trust `{"action_class": "draft"}` when the caller can execute a side
> effect. Derive the effective capability from the registered application, the
> tool it is invoking, the argument range, the environment and the identity.

**Why this matters so much for you specifically.** I told you two documents ago
that self-declared action class was your most findable weakness, and that the
best you could do was say *"under-declaration is auditable after the fact but
not preventable at request time."* That was an apology.

This turns the apology into a feature. Blast radius is the load-bearing idea of
your entire product; if the input to it can be forged by the caller, the whole
thing is decorative. Deriving it makes it **enforced** rather than **declared**.

```
declared_action_class:  "draft"          ← what the caller said
effective_action_class: "execute"        ← what the tool binding proves
                                            → blast radius 1.00, not 0.35
                                            → hard gate applies
                                            → attempt recorded as a downgrade attempt
```

**And it is the best demo beat available to you**, because it is a moment of
visible drama: an application lies about what it is doing and the control plane
catches it. Nothing else on any list is as vivid.

Registry entry becomes the source of truth:

```yaml
- id: it-ops-agent
  allowed_tools:
    - name: restart_service
      effective_action: execute
      reversible: false
      approval_required: true
      environments: [staging]        # not production
    - name: summarise_incident
      effective_action: draft
      reversible: true
```

### 2. Detector status separate from detector score

A failed or timed-out detector currently returns zero score and zero
confidence — which is **indistinguishable from "checked and found nothing."**
That is a correctness bug, not a style preference. A privacy detector that
crashed must not look like a clean privacy check.

```json
{"grounding": {"score": 0.82, "status": "completed"},
 "bias":      {"score": null, "status": "timed_out"},
 "pii":       {"score": null, "status": "failed"}}
```

And it leads to a per-response **governance status**, which is the real prize:

```
fully_governed              all mandatory detectors completed
partially_governed          an advisory detector did not complete
ungoverned_due_to_timeout   a mandatory detector did not complete
ungoverned_due_to_failure   a mandatory detector crashed
```

Policy then declares, per detector, whether it is **mandatory / advisory** and
for which action classes. A low-risk draft releases with a degraded marker. An
`execute` with a mandatory detector missing **fails closed**.

**This is a genuinely novel line for the room:**

> "Every governance product tells you whether the answer was safe. Ours also
> tells you whether the *governance itself* was complete. If we didn't fully
> check something, the record says so, and on an irreversible action we refuse
> rather than guess."

### 3. Controls must be scoped, versioned, expiring and reversible

I under-specified this. A control with no expiry is a production hazard and an
experienced judge will ask about it within thirty seconds.

Every control carries: id · reason · evidence refs · requesting component ·
rule applied · scope · policy version · start · **expiry** · **rollback** ·
expected effect · observed effect · approval state.

**And never mutate the base policy** — compose a scoped overlay. Which, as I
noted before, is exactly the mechanism your EU/India jurisdiction overlays
already implement. So:

```
base profile  +  jurisdiction overlay  +  approved control overlay
                                       =  resolved control snapshot (versioned)
```

The engine consumes the snapshot. One mechanism, three sources, fully
reconstructible from the ledger.

### 4. Policy simulation before activation — **a superb demo beat, and cheap**

Before a policy or control goes live, replay it against the ledger you already
have:

```
Proposed: EU overlay on hr-copilot
  would change    47 of 1,204 historical decisions
  escalation      +3.1 pp
  spend           −₹4,200 / month
  reviewer time   +18 minutes / week
  newly blocked   3 decisions, all action_class=decide
```

**Nobody expects a student prototype to do counterfactual policy analysis**, and
you get it almost free because your ledger already stores every input to the
decision. This is the strongest "wow" per line of code in the entire plan.

### 5. Health states that define capability, not just colour

Better than my traffic light, because a colour is decoration and a state is a
contract.

| State | What the system may do |
|---|---|
| `healthy` | normal traffic, all configured tools |
| `warning` | normal traffic, owner notified |
| `guarded` | stricter thresholds, expensive detectors promoted inline |
| `approval_required` | irreversible actions queue for a human |
| `tool_restricted` | text continues; risky tools disabled |
| `throttled` | rate limited, explicit retry |
| `degraded` | approved fallback model / reduced context |
| `suspended` | new production traffic refused (human-approved only) |
| `recovering` | controls remain until improvement is measured |

## ⚖️ ADAPT — where I disagree with its judgement

### 6. On the number of agents — it over-corrects, but it is directionally right

Its position: *"do not build four governors and eleven specialists; that is
architecture theatre."* Then it proposes a Safety Governor, a Resource Governor,
an Evidence/Compliance Monitor and a Deterministic Supervisor. That is the same
structure with one fewer box. The disagreement is smaller than it presents.

But it is right on the substance that matters: **the eleven specialists should
not be agents.** A thing that produces evidence and cannot be told "no" is a
detector, not an agent. Calling it one is exactly the tell a technical judge
looks for.

**My call:**

```
AGENTS   (hold state, have an objective, can be refused, can be overruled)
   Supervisor  ·  Safety Governor  ·  Resource Governor  ·  Assurance Governor

EVIDENCE PRODUCERS  (no authority, no autonomy — but they may raise typed requests)
   Detectors  — per response   (grounding, uncertainty, privacy, fairness, cost)
   Monitors   — over time      (exposure, budget, queue, latency, detector health)
```

Four agents. Not sixteen. The agentic claim gets **stronger**, not weaker,
because every box now survives the question *"what makes that an agent?"*

### 7. But I reject folding human attention into "resources" silently

The other AI merges reviewer capacity into a general Resource Governor. That is
tidy, and for most teams it would be right. For **you** it buries your founding
insight — that human attention is 94.8% of what oversight costs — inside a box
everyone expects to contain money.

**My call: keep one Resource Governor, but give it two explicit currencies**,
and surface both on every screen.

> "Our resource governor manages two currencies. Every product in this market
> manages the first one. Nobody manages the second — and our own research says
> it's 94.8% of what oversight actually costs."

Credible box count, and the differentiator lands harder as a surprise *inside*
an expected box than as a fourth box nobody was looking at.

### 8. Its Phase 0–8 plan is right in spirit, over-built for your slot

The acceptance criteria and phasing are enterprise-grade and much of it is
correct. But a chunk of it — multi-tenancy, retention, encryption,
authorisation, external deployment adapters — is production checklist for a
ten-minute finale. Keep the compatibility contract (Phase 0), which is genuinely
essential. Treat the rest as the answer to *"what would production need?"* rather
than as a build list.

## ❌ REJECT — one thing

### 9. "The strongest finale proves one decision correctly, not many agents"

Half right, and the half that is wrong matters. Depth does beat breadth in the
**demo**. But Sir explicitly named architecture as a scoring axis — *"how
advanced, how extensible, can I scale it"* — and agentic architecture is what he
steered you toward.

These are not in tension. **The architecture is agentic; the demo shows one hard
decision made correctly.** Build the first, present the second. That is the
synthesis, and it is what I have designed below.

---

# PART 3 — The final architecture

## 3.1 The three layers

```
┌── LAYER 1 · REFLEX ────────────────────── milliseconds, per request ──┐
│  identity → effective capability → policy snapshot → detectors        │
│  → blast-radius pricing → pass/repair/escalate/block → evidence       │
│  "Can this response proceed?"                                          │
└────────────────────────────────────────────────────────────────────────┘
                              │ evidence
┌── LAYER 2 · FLEET GOVERNANCE ─────────── seconds–hours, per system ───┐
│  monitors → governors → deterministic arbitration → scoped controls    │
│  → effectiveness measurement                                           │
│  "How should this AI system be governed from now on?"          ← NEW   │
└────────────────────────────────────────────────────────────────────────┘
                              │ outcomes
┌── LAYER 3 · LEARNING ────────────────────────── days, per policy ─────┐
│  human verdicts → bounded calibration · policy simulation              │
│  "Were we right, and what would changing the rules do?"                │
└────────────────────────────────────────────────────────────────────────┘
```

Layers 1 and 3 exist. Layer 2 is the addition, and it is the answer to Sir's
*"the name says controls — you should be controlling something."*

## 3.2 The four agents

| Agent | Objective | Two-currency / domain | Its human |
|---|---|---|---|
| **Safety Governor** | minimise expected harm | exposure, hard-gate trips, trend, capability violations | Priya — AI Platform |
| **Resource Governor** | minimise cost per useful answer | **₹ spend** and **reviewer-minutes** | Arun — Finance Ops |
| **Assurance Governor** | keep every decision evidenced | governance completeness, overlays, retention, chain | Meera — CISO |
| **Supervisor** | resolve conflict, actuate | deterministic arbitration, control lifecycle | — |

Line for the architecture slide:

> "We didn't build a dashboard for three people. We built three agents — one
> working for each of them — and a deterministic supervisor that referees when
> they disagree. The dashboard is where they report."

The persona switcher is then not a cosmetic filter: it is **choosing which agent
is speaking to you.**

## 3.3 Why this is genuinely multi-agent

The test is not the box count. It is this:

> **The agents want different things, and they conflict.**

| Situation | Safety wants | Resource wants |
|---|---|---|
| exposure rising on `hr-copilot` | promote fairness + uncertainty inline | those are the two costliest detectors — keep them deferred |
| regulated system near budget | keep the LLM judge available | disable the judge, it is the single costliest call |
| review queue filling | escalate more | escalating spends a *human*, the most expensive outcome there is |

Every one of these falls out of numbers you already compute. Something has to
arbitrate, that arbitration has to be principled, and it has to be auditable.
**That is the architecture.**

## 3.4 Arbitration — four rules, strict precedence, no LLM

```
RULE 1 · HARD GATES ARE NOT TRADEABLE
    Confirmed sensitive-data leakage, unauthorised execution, missing mandatory
    approval, contradiction of the source of record, a mandatory detector that
    did not complete on an irreversible action. None of these can be exchanged
    for lower cost or lower latency. Ever.

RULE 2 · REVERSIBILITY DOMINATES
    On irreversible actions (execute, decide) — by EFFECTIVE capability, not
    declared — Safety and Assurance outrank Resource. Always.

RULE 3 · BELOW THAT LINE, PRICE THE TRADE
    Δ(exposure) × blast_radius   vs   Δ(₹) + Δ(reviewer-minutes)
    Both sides in units already computed. Arithmetic, not opinion.

RULE 4 · DEGRADE TOWARDS EVIDENCE, NEVER TOWARDS SILENCE
    When no action satisfies every governor: take the safest permitted action,
    record the unmet constraint, lower the governance status, show it on screen.
    A governance system under pressure must fail loudly.
```

**Rule 2 is your blast-radius idea promoted from scoring a response to governing
the whole plane.** It stops being a heuristic inside one function and becomes the
constitution of the system. Say exactly that.

**Rule 4 is the honesty rule** and it is the one engineers respect. Every other
product, under pressure, quietly does less. Yours records that it wanted to do
more and could not.

## 3.5 Arbitration is ledgered

```json
{ "event": "arbitration",
  "system_id": "hr-copilot",
  "requests": [
    {"from": "safety", "ask": "promote_inline(fairness)",
     "evidence": {"flip_rate": 0.12, "probes": 60, "trend": "rising"},
     "estimated_cost_ms": 340},
    {"from": "resource", "ask": "veto",
     "evidence": {"budget_used_pct": 104, "reviewer_minutes_left": 40}}],
  "effective_action_class": "decide",
  "rule_applied": "RULE_2_REVERSIBILITY",
  "outcome": "granted",
  "control_id": "ctl_8f31", "expires": "2026-10-01T00:00:00Z",
  "unmet": ["resource.budget"] }
```

> "We audit the AI. We also audit the thing that audits the AI. Ours is the only
> one of the two anybody can currently ask questions of."

---

# PART 4 — Component design

## 4.1 Registry — `systems.yaml`, the file that divorces you from one use case

```yaml
- system_id: finance-decision-assistant
  name: Finance Decision Assistant
  owner: Arun Mehta
  department: Finance Operations
  environment: production
  policy_profile: decision_support
  jurisdiction: in
  budget_inr_month: 25000
  review_minutes_week: 240
  allowed_capabilities: [read, advise]
  allowed_tools:
    - name: issue_refund
      effective_action: execute
      reversible: false
      max_amount_inr: 5000
      approval_required: true
  enabled: true
```

Adding an AI system is **one entry. No code.** That is the answer to *"divorce
the control plane from the use case."*

A `system_id` absent from the registry is **`unregistered`** — visible, governed
under the strictest default profile, never silently normal. That is your honest,
minimal answer to the shadow-AI problem all three competitors headline: you
notice, you do not claim to discover.

## 4.2 Effective capability resolution

```python
def resolve_capability(req, registry) -> Capability:
    system = registry.get(req.system_id)          # unregistered → strict default
    tool   = system.tool(req.tool_name) if req.tool_name else None
    if tool is None:
        effective = min(req.declared_action_class, system.max_capability)
    else:
        effective = tool.effective_action          # the binding, not the claim
        if tool.max_amount_inr and req.amount > tool.max_amount_inr:
            effective, approval = "execute", True
    downgrade_attempt = RANK[req.declared_action_class] < RANK[effective]
    return Capability(effective, tool.reversible, approval, downgrade_attempt)
```

`blast_radius()` is then fed the **effective** class. A caller cannot buy cheaper
oversight by lying, and a `downgrade_attempt` is itself a recorded safety event.

## 4.3 Control objects

Nine safe controls, three guarded, three human-approved.

| Tier | Controls |
|---|---|
| **Safe — supervisor may apply autonomously** | `TIGHTEN_POLICY` · `REQUIRE_HUMAN` · `PROMOTE_DETECTOR_INLINE` · `RESTRICT_TOOL` · `ADD_CITATION_REQUIREMENT` · `REDACT_OUTPUT` · `ENABLE_CACHING` · `LOWER_CONTEXT_LIMIT` · `ROUTE_LOW_RISK_CHEAPER` |
| **Guarded — needs a standing authorisation** | `THROTTLE` · `DOWNGRADE_MODEL` · `FREEZE_NEW_SESSIONS` |
| **Human-approved only** | `SUSPEND` · `QUARANTINE` · `RELAX_SAFETY_BOUNDARY` |

Every control expires. Every control has a rollback. Nothing mutates a base
policy — controls compose as a scoped overlay, the same mechanism as
jurisdictions.

**Why suspension stays human:** an autonomous agent that can unilaterally halt a
production system is a worse risk than the one it prevents. That is the identical
argument your own `router.py` docstring already makes about rationing BLOCK.
**Applying the same principle at both scales is the kind of consistency an
experienced judge notices.**

## 4.4 Closed loop — controls measure themselves

```
control      PROMOTE_INLINE(fairness, hr-copilot)     expires in 7d
expected     unsupported decisions ↓, added latency ↑ (within 6000ms)
observed     exposure −38% · latency +290ms · reviewer-minutes −14/wk
verdict      effective → retain until expiry, then re-evaluate
```

Label it **observed before/after**, not causal proof — you have no control group
and saying so is a credibility gain, not a loss.

An agent that measures whether its own intervention worked is the difference
between a control system and a rules engine. **This is Layer 2 actually
closing**, and it is the exact thing Sir asked for when he said don't just tell
me I crossed the signal, tell me what to do tomorrow.

## 4.5 Fleet metrics

**Exposure** — `Σ risk_price`, and per 100 requests so volume cannot mask
consequence.

> "`order-desk` logged forty findings this week. `treasury-bot` logged three.
> `treasury-bot` is red — its three were payment executions, `order-desk`'s forty
> were reads. We don't count incidents. We price consequence."

**Two currencies** — ₹ spend and reviewer-minutes, side by side, always.

**Review triage** — order the queue by `expected consequence ÷ reviewer effort`,
not FIFO. When attention runs short, reserve reviewers for irreversible actions
and mark the organisation **attention-constrained** on screen.

---

# PART 5 — Build order, with reasoning

Dependency order. Each step is testable before the next.

**0 · Compatibility contract.** Snapshot current per-request decisions for all 31
eval cases. Define inert mode. *Reasoning: this is the gate on everything. If
fleet state is empty, v2 must reduce exactly to v1, which is what lets you say
"the per-request decision is provably unchanged" in Q&A without re-running your
published numbers.*

**1 · Fix Defects 1 and 2.** Enforce the budget with `wait(timeout=…)`; move
deferred work to a real background queue; add `status` to `Signal`. *Reasoning:
it is a correctness fix, it is small, and it unlocks governance status. Do it
first because everything downstream reads detector status.*

**2 · Governance status + mandatory/advisory in policy YAML.** *Reasoning:
depends on step 1; nothing else depends on it, so it can land early and be
demoed on its own.*

**3 · Registry + effective capability.** `systems.yaml`, `resolve_capability()`,
feed effective class to `blast_radius()`, record `downgrade_attempt`. *Reasoning:
this is the single biggest strengthening of your core idea, and it is entirely
inside Layer 1 — no fleet machinery needed yet.*

**4 · Fleet projections.** Rebuild `SystemState` from the ledger. *Reasoning:
read-only, zero risk, and it makes the fleet view possible on its own. Also
proves the "projections are rebuildable from evidence" claim.*

**5 · Control objects + resolved snapshot.** Typed, scoped, expiring, rollback.
Engine consumes `base + jurisdiction + control` snapshot. *Reasoning: reuses the
overlay mechanism you already have, so it is composition rather than new
machinery.*

**6 · Monitors.** Exposure, budget, queue, latency, detector health. *Reasoning:
pure functions over projections — trivially unit-testable with no engine
involvement.*

**7 · Safety and Resource Governors.** Typed recommendations only, no authority.
*Reasoning: testable by feeding them synthetic projections.*

**8 · Supervisor.** Rules 1–4, control lifecycle, human-approval gating.
*Reasoning: the only component with authority, so it lands last among the
agents and gets the most testing.*

**9 · Assurance Governor.** Governance completeness, overlays, chain integrity.
*Reasoning: depends on step 2, and it is the least load-bearing of the three.*

**10 · Effectiveness evaluator.** Expected vs observed per control.

**11 · Policy simulation.** Replay the ledger against a candidate snapshot.
*Reasoning: read-only, no engine dependency, and it is the highest wow-per-line
item in the plan. Can be built in parallel with anything after step 4.*

**12 · UI.** Portfolio landing → application detail → existing six tabs
underneath, nothing deleted. Persona lens = which governor speaks.

**13 · Apply the ledger cross-process fix.** Rebuild the ledger clean.

**14 · Verify the invariant.** Inert fleet ⇒ the 31 decisions from step 0 are
bit-identical. *Reasoning: if the numbers move, the wiring is wrong, not the
eval. This is the gate on shipping.*

**15 · Dormant `detectors/toxicity.py`** for the live-add offer.

Steps 1–4 and 11 touch no agent code and can proceed in parallel with 6–8.

---

# PART 6 — The demo

Five beats. Depth, not breadth.

**Land on the portfolio.** Five systems, owners, two budgets, exposure, status.
This is Priya's screen.

**Beat 1 · Consequence, not frequency.** `order-desk` 40 findings, green.
`finance-assistant` 3 findings, red. *"We price consequence."*

**Beat 2 · The lie.** ⭐ The IT operations agent calls `restart_service` in
production while declaring `action_class: draft`. ControlPlane resolves the
effective capability from the tool binding, gets `execute`, applies blast radius
1.00 instead of 0.35, hits the hard gate, blocks the action, preserves the
textual answer, and records a `downgrade_attempt` against the system. Its health
moves to `tool_restricted`.

> *"Every governance product trusts the application to declare what it's doing.
> We don't. Blast radius is the whole of our idea — if the input to it can be
> forged, the idea is decorative."*

**Beat 3 · The conflict.** `hr-copilot` — safety requests fairness inline
(flip rate rising), resource vetoes (104% of budget). Effective class is
`decide`, irreversible, so **Rule 2** applies and safety wins. Show the signed
arbitration record. *"You can ask our control plane why it spent your money."*

**Beat 4 · The second currency.** Arun's lens. `claims-desk` inside its money
budget, over its reviewer-hour budget. *"94.8% of what oversight costs is human
attention. This is the only dashboard that treats it as a budget."* The control
is recommended; **Arun presses Suspend, or raises the budget.**

**Beat 5 · The loop closes.** The control from beat 3, one week on: exposure
−38%, latency +290 ms inside budget, reviewer-minutes −14/week. Verdict:
effective, retained until expiry. Then the simulation panel: *"and here's what
activating the EU overlay would do to 1,204 historical decisions before we
commit to it."*

**The closing offer.** *"Adding a new risk category is one import and one line.
Would anyone like me to add one now?"*

---

# PART 7 — What we deliberately do not build

Saying this is a strength. It separates a team that made choices from a team
that ran out of time.

- **No LLM inside the supervisor.** Enforcement must be deterministic and
  reproducible. A compliance decision that varies run to run is not evidence.
  The model is used exactly where judgement is genuinely needed — the rationed
  judge above risk price 60, capped at 90 calls per thousand.
- **No autonomous suspension.** Recommended by an agent, executed by a human.
- **No shadow-AI network discovery.** We flag unregistered traffic; we do not
  claim to find it on the network.
- **No database, no multi-tenancy, no authentication.** JSONL keeps the evidence
  readable with ordinary tools. At enterprise volume it becomes a real store —
  we know; it is not a surprise.
- **No causal claims about control effectiveness.** Observed before/after, and
  we say so.

---

# The thesis, one paragraph

> ControlPlane is a consequence-aware operating layer for enterprise AI with two
> enforcement tiers. A deterministic per-response gate prices every answer by
> what it is about to **do** — derived from the tool it can actually call, never
> from what the caller claims — and routes it to pass, repair, escalate or block.
> Above that, a fleet controller watches every AI system's exposure, spend,
> reviewer burden and governance completeness, and applies scoped, expiring,
> reversible controls when a system drifts. Three governor agents pursue
> genuinely competing objectives; a deterministic supervisor arbitrates on
> reversibility; humans retain authority over irreversible fleet actions. Every
> response decision and every control decision is recorded as replayable
> evidence — so when a system turns red, you can ask it why, what it did about
> it, and whether that worked.
