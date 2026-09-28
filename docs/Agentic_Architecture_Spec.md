# ControlPlane v2 — Agentic Control Architecture

Full architecture specification. Team Challenge_24 · Problem Track 1

---

# 0 · The thesis

Most "agentic" submissions are modules with agent-shaped labels. A judge who
builds systems can tell in ten seconds, and it reads worse than not claiming it.

So the first question has to be: **what makes this genuinely multi-agent rather
than well-named functions?**

The answer is not the number of boxes. It is this:

> **Our agents want different things, and they conflict.**
>
> The cost agent wants to run fewer checks. The safety agent wants to run more.
> The attention agent wants fewer escalations reaching humans. The compliance
> agent wants more evidence collected. Every one of those goals is legitimate,
> and satisfying one degrades another.
>
> A control plane is the thing that arbitrates. That arbitration is our
> architecture, and it is not something you can write as a pipeline.

That is the sentence to open the architecture slide with, and everything below
is built to make it true rather than decorative.

---

# 1 · Three nested control loops

This is the frame that makes the whole system legible in one diagram. Two of
these loops already exist in your code. v2 adds the middle one, which is the
one Sir was reaching for.

```
┌─ LOOP 1 · REFLEX ─────────────────────── milliseconds, per request ─┐
│  sensors → price → route → release                                   │
│  "Is THIS answer safe to release?"                    ← you have this│
└──────────────────────────────────────────────────────────────────────┘
          │ every decision observed by ↓
┌─ LOOP 2 · GOVERNANCE ──────────────── seconds–hours, per system ────┐
│  governors → arbitration → control actions on the system             │
│  "Is THIS SYSTEM behaving, and what do I do about it?"     ← NEW     │
└──────────────────────────────────────────────────────────────────────┘
          │ outcomes reviewed by humans ↓
┌─ LOOP 3 · LEARNING ──────────────────────── days, per policy ───────┐
│  human verdicts → bounded calibration offset → thresholds            │
│  "Were we right to flag it?"                          ← you have this│
└──────────────────────────────────────────────────────────────────────┘
```

Say this out loud in the room:

> "Most governance products have loop one — a filter. Some have loop three — a
> feedback form. The loop nobody closes is the middle one: nothing decides that
> *this system* should be throttled tomorrow because of what it did today.
> That loop is the control plane."

**Why this framing is strong:** it is control theory, not AI fashion. It ages
well, it survives a hostile question, and it makes the three time-scales — and
therefore the need for *persistent per-system state* — obvious. State is what
separates an agent from a function, and this diagram makes the state
self-evidently necessary.

---

# 2 · The agent hierarchy

Three tiers. Sense, govern, act.

```
                        ┌───────────────────────────┐
                        │   CONTROL SUPERVISOR      │   arbitrates conflict,
                        │   (Arbiter / Orchestrator)│   issues control actions,
                        └─────────────┬─────────────┘   owns the fleet verdict
                                      │
        ┌─────────────┬───────────────┼───────────────┬─────────────┐
        ▼             ▼               ▼               ▼             │
  ┌───────────┐ ┌───────────┐  ┌────────────┐  ┌────────────┐      │
  │  SAFETY   │ │   COST    │  │ ATTENTION  │  │ COMPLIANCE │      │
  │ GOVERNOR  │ │ GOVERNOR  │  │  GOVERNOR  │  │  GOVERNOR  │      │
  └─────┬─────┘ └─────┬─────┘  └──────┬─────┘  └──────┬─────┘      │
        │             │               │               │             │
   ┌────┼────┬────┐   ├────┬────┐     ├────┐          ├────┐        │
   ▼    ▼    ▼    ▼   ▼    ▼    ▼     ▼    ▼          ▼    ▼        │
 Ground Unc Priv Fair Bud Effic Model Triage Cap    Policy Evidence  │
  ing  ert  acy  ness get iency Route              Overlay  Chain    │
        └──────── SPECIALIST AGENTS (sense + local memory) ──────────┘
```

**One supervisor. Four governors. Eleven specialists.**

Show the judges the **top two tiers only** — five boxes. Reveal the specialist
layer if someone asks how deep it goes. A five-box diagram that survives
interrogation beats a sixteen-box diagram nobody reads.

## 2.1 Why exactly these four governors

Because each one has a **human counterpart in the customer's organisation**,
and that is the test of whether a governor deserves to exist.

| Governor | Objective it maximises | Its human | What it would say if it could talk |
|---|---|---|---|
| **Safety** | minimise expected harm | Priya — Head of AI Platform | *"treasury-bot's exposure tripled this week"* |
| **Cost** | minimise spend per useful answer | Arun — Finance Ops | *"claims-desk burns 40% of its tokens on duplicates"* |
| **Attention** | protect scarce human review capacity | Ops / review lead | *"we will exhaust reviewer hours by Thursday"* |
| **Compliance** | keep every decision evidenced and retained | Meera — CISO | *"three EU decisions are missing a reviewer id"* |

**This gives you one of the best lines in the deck:**

> "We didn't build a dashboard for four people. We built four agents — one
> working for each of them — and the dashboard is where they report."

The persona switcher in the UI is then not a cosmetic filter. It is **choosing
which agent is speaking to you.** That is a real product idea, and it is the
answer to Sir's "what would a business user want to see versus an IT user."

## 2.2 Why the specialists are agents, not functions

A specialist qualifies as an agent because it does four things a detector
cannot:

1. **Holds memory per system.** `FairnessAgent` knows `hr-copilot` has flipped
   on 4 of its last 60 counterfactual probes — not just this one.
2. **Judges its own reliability.** It reports when its own confidence is
   degrading (few probes, low agreement) rather than emitting a number and
   staying silent.
3. **Bids for resources.** It can *request* to be promoted from asynchronous to
   inline for a specific system, and the Cost Governor can refuse.
4. **Recommends, in a sentence, citing its evidence.**

Point 3 is the important one. **A component that can ask for something and be
told no is an agent. A component that just returns a number is a function.**

---

# 3 · The agent protocol

One protocol, same shape for every agent at every tier. This is what makes the
registry pattern work and the scaling story provable.

```python
# controlplane/agents/base.py
from dataclasses import dataclass, field
from typing import Protocol, Any

@dataclass
class Observation:
    """What a specialist perceived. Bounded, evidenced, no side effects."""
    agent: str
    system_id: str
    score: float                      # 0..1, the agent's own concern level
    confidence: float                 # 0..1, how sure it is of that score
    evidence: dict[str, Any]          # the numbers behind it — always populated
    window: str                       # "request" | "24h" | "7d"

@dataclass
class Request:
    """A specialist bidding for a resource it does not control."""
    kind: str                         # "promote_inline" | "extra_probes" | "judge_call"
    justification: str
    estimated_cost_ms: float = 0.0
    estimated_cost_inr: float = 0.0

@dataclass
class Verdict:
    """What a governor decided. Governors decide; specialists only observe."""
    governor: str
    system_id: str
    status: str                       # "green" | "amber" | "red"
    desired_actions: list["ControlAction"] = field(default_factory=list)
    requests: list[Request] = field(default_factory=list)
    reason: str = ""                  # ONE human sentence, citing a number
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation: str | None = None  # what the owner should do tomorrow

class Agent(Protocol):
    name: str
    tier: str                         # "specialist" | "governor" | "supervisor"
    def observe(self, ctx) -> Observation | Verdict: ...
    def explain(self, system_id: str) -> str: ...
    def health(self) -> dict: ...     # degraded agents are visible, never silent
```

**Design rules, and each one is defensible out loud:**

- **Specialists observe. Governors decide. Only the supervisor acts.** Nothing
  in the middle of the tree can change the world on its own, which is what makes
  the system auditable.
- **Every `Observation` and `Verdict` carries `evidence`.** An agent that cannot
  show its numbers is a broken agent. This is the same principle already running
  through your console — never a number without the limit it is judged against.
- **Every agent has `health()`.** A crashed agent degrades to zero-score,
  zero-confidence and shows on the fleet view as *degraded*. You already do
  exactly this for detectors; v2 promotes it to a first-class property.
  **Graceful degradation is a scoring point and almost nobody builds it.**

---

# 4 · Arbitration — the intellectual centre of the design

This is the part that makes the architecture worth presenting. Everything above
is scaffolding for this section.

## 4.1 The conflicts are real

| Conflict | Safety wants | Cost wants |
|---|---|---|
| A system's exposure is rising | promote bias + uncertainty to inline | those are the two most expensive detectors; stay async |
| A regulated system is near budget | keep the LLM judge available | disable the judge, it is the single costliest call |
| Queue is filling | escalate more | escalating is the *most* expensive outcome — it spends a human |

| Conflict | Attention wants | Compliance wants |
|---|---|---|
| Reviewer hours nearly exhausted | raise thresholds, escalate less | EU overlay says these decisions **require** a human reviewer id |

These are not hypothetical. Every one of them falls out of numbers your system
already computes.

## 4.2 The arbitration policy

Three rules, in strict precedence. This is the piece of original thinking to
put on the slide.

```
RULE 1 — REVERSIBILITY DOMINATES
  On irreversible actions (execute, decide), Safety and Compliance outrank Cost
  and Attention. Always. No budget argument suspends a hard gate.

RULE 2 — ON REVERSIBLE ACTIONS, PRICE THE TRADE
  Below the irreversibility line, a resource request is granted when
      expected harm avoided  >  cost of granting it
      Δ(exposure) × blast_radius   >   Δ(₹) + Δ(reviewer-minutes)
  Both sides are in units we already compute. The trade is arithmetic,
  not opinion.

RULE 3 — DEGRADE TOWARDS EVIDENCE, NOT TOWARDS SILENCE
  When no action satisfies every governor, the supervisor takes the action that
  preserves the most evidence, and records the unmet constraint in the ledger.
  A governance system under pressure must fail loudly.
```

**Rule 1 is your blast-radius idea promoted from scoring a response to
arbitrating between agents.** That is the strongest possible use of your
original contribution: it is not a heuristic bolted into one function any more,
it is the constitution of the whole control plane. Say exactly that.

**Rule 3 is the honesty rule** and it is the one that wins engineers over.
Every other vendor's system, under load, quietly does less. Yours records that
it wanted to do more and could not.

## 4.3 What arbitration looks like in the ledger

Every arbitration is written to the same hash-chained, HMAC-signed ledger you
already have:

```json
{
  "arbitration": {
    "system_id": "treasury-bot",
    "requests": [
      {"from": "safety.fairness", "kind": "promote_inline",
       "justification": "flip rate 0.12 over 60 probes, rising",
       "estimated_cost_ms": 340},
      {"from": "cost.budget", "kind": "veto",
       "justification": "system at 104% of monthly budget"}
    ],
    "rule_applied": "RULE_1_REVERSIBILITY",
    "outcome": "granted",
    "reason": "action_class=execute is irreversible; safety outranks cost",
    "unmet": ["cost.budget"]
  }
}
```

**This is genuinely novel and I have not seen it in any competitor.** Your
ledger stops being an audit trail *of the AI* and becomes an audit trail **of
the governance system itself**. Meera the CISO can ask: *"On what grounds did
your control plane decide to spend more money on that system?"* — and get a
signed, tamper-evident answer.

Line for the room:

> "We audit the AI. We also audit the thing that audits the AI. Ours is the
> only one of the two that anyone can currently ask questions of."

---

# 5 · The control system

Sir: *"The name says controls. You should be controlling something."*

## 5.1 The actuator

Eight control actions. Every one maps to a mechanism **already in your code** —
nothing here is a stub.

| Action | Issued by | Mechanism that already exists |
|---|---|---|
| `ADMIT` | Supervisor | normal path |
| `THROTTLE` | Cost | rate limit per system before the provider call |
| `DOWNGRADE` | Cost | provider/model selection — `providers/` already abstracts this |
| `PROMOTE_INLINE` | Safety | `Policy.inline_detectors` is a mutable merged dict |
| `TIGHTEN` | Safety / Compliance | `Policy.thresholds` — the jurisdiction overlay already does exactly this |
| `REQUIRE_HUMAN` | Attention / Compliance | force `ESCALATE` in `router.route()` |
| `QUARANTINE` | Compliance | permit only `read` / `draft` action classes |
| `SUSPEND` | Supervisor | refuse at admission, before any spend |

**Note what `TIGHTEN` and `PROMOTE_INLINE` really are.** Your jurisdiction
overlay mechanism already takes a policy and returns a tightened policy. A
governor issuing `TIGHTEN` is doing *the same operation your EU overlay does* —
only the trigger is an agent's observation rather than a country. So the
actuator is not new machinery. It is the overlay mechanism, driven dynamically.

That is a genuinely elegant answer to "how did you implement control?" — *"we
already had a mechanism for composing a stricter policy on top of a base one.
The governors drive it."*

## 5.2 Human-in-the-loop, deliberately

Some actions **the supervisor recommends but will not take alone**:

- `SUSPEND` — always requires a human. The agent turns the light red and puts a
  **Suspend** button in front of the owner. Arun presses it, or raises the
  budget instead.
- `QUARANTINE` — same.

Everything else the supervisor executes autonomously and records.

**Two reasons, both worth saying.** Product: Sir's point that the business
owner must hold the remedy. Engineering: an autonomous agent that can
unilaterally halt a production system is a worse risk than the one it prevents —
which is precisely the argument your `router.py` docstring already makes about
why BLOCK is rationed. **Your architecture applies the same principle at both
scales, and that consistency is what an experienced judge will notice.**

## 5.3 Closed loop

Control actions are not fire-and-forget. The supervisor records what it expected
and checks:

```
issue PROMOTE_INLINE(fairness, hr-copilot)
  → expect: flip rate detected earlier, exposure falls within 24h
  → observe: exposure -38%, added latency +290ms (inside the 6000ms budget)
  → verdict: action effective, retain
```

An agent that measures whether its own intervention worked is the difference
between a control system and a rules engine. This is Loop 2 actually closing.

---

# 6 · Fleet state — what the governors actually hold

Per registered system, maintained incrementally as each ledger record lands.

```python
@dataclass
class SystemState:
    system_id: str
    # — Safety Governor —
    exposure_total: float          # Σ risk_price
    exposure_per_100: float        # intensity, so volume can't mask consequence
    route_counts: Counter          # pass/repair/escalate/block
    hard_gate_trips: int
    label_mix: Counter             # hallucination/privacy/bias/waste/unverifiable
    exposure_trend_7d: list[float]
    # — Cost Governor —
    spend_inr: float
    budget_inr: float
    tokens: int
    cache_hit_rate: float
    duplicate_prompt_share: float
    projected_exhaustion: date | None
    # — Attention Governor —
    reviewer_minutes_used: float   # escalate ≈ 4, block ≈ 8
    reviewer_minutes_budget: float
    queue_depth: int
    oldest_unreviewed_age_h: float
    # — Compliance Governor —
    jurisdiction: str
    evidence_complete_share: float
    chain_verified: bool
    # — Supervisor —
    status: str                    # green | amber | red | suspended | degraded
    active_controls: list[ControlAction]
    unregistered: bool             # seen in traffic, absent from the registry
```

## 6.1 Exposure — the metric nobody else has

```
exposure = Σ risk_price = Σ ( P(failure) × blast_radius × 100 )
```

Every competitor ranks systems by **incident count**. That treats a chatbot typo
and a wrong payment figure as one event each. Yours is harm-weighted, and it
falls directly out of blast radius.

> *"`order-desk` logged forty findings this week. `treasury-bot` logged three.
> `treasury-bot` is the red one — its three were on payment executions and
> `order-desk`'s forty were on reads. We don't count incidents. We price
> consequence."*

That is thirty seconds and it is unanswerable by any competing dashboard.

## 6.2 Reviewer capacity — the second budget

Your founding research says human attention is **94.8%** of what oversight
costs, against **0.03%** for model API calls. So govern it like a budget:

```
claims-desk                                  ● AMBER
  Money      ₹18,400 / ₹25,000      (74%)
  Attention  31 / 40 reviewer-hours (78%)   ← nobody else governs this
  Exposure   1,240  (18 per 100 requests)
```

Every competitor governs machines. **You govern the scarce resource your own
research identified as the real constraint.** And it gives the Attention
Governor something genuine to fight for in arbitration — it is not decoration,
it is a constraint that binds.

Closing line for this section:

> "Two of our systems are inside their money budget and over their human
> budget. That is the failure mode nobody is watching, and it is the one that
> actually causes oversight to get switched off."

---

# 7 · Module layout

```
controlplane/
  agents/
    base.py            Agent protocol, Observation, Verdict, Request, ControlAction
    registry.py        AGENTS — one dict entry adds an agent, any tier
    supervisor.py      arbitration rules, actuation, closed-loop verification
    governors/
      safety.py        exposure, breach history, detector mix
      cost.py          spend, burn-down, efficiency
      attention.py     reviewer capacity, queue health, triage order
      compliance.py    overlays, evidence completeness, chain integrity
    specialists/
      grounding.py     ┐
      uncertainty.py   │ wrap the existing detectors — detector logic untouched
      privacy.py       │ and add per-system memory + self-assessment + bids
      fairness.py      ┘
      budget.py        efficiency.py   model_routing.py
      triage.py        capacity.py
      policy.py        evidence.py
  fleet.py             registry loading, SystemState store, status computation
  systems.yaml         the inventory — this file is what "divorces" us from one use case
  control.py           ControlAction taxonomy + application to a resolved Policy
  advisor.py           cross-governor recommendations, always citing evidence
```

**Detector files are not moved and not rewritten.** Specialists wrap them. That
is not caution — it is the correct dependency direction: perception logic should
not know it is inside an agent. It also means your published precision and
recall still describe the shipped detectors, because they are the same code.

## 7.1 Two registries, and the scaling story becomes provable

```python
DETECTORS = {"grounding": ..., "uncertainty": ..., "pii": ..., "bias": ..., "cost": ...}
AGENTS    = {"safety": SafetyGovernor(), "cost": CostGovernor(),
             "attention": AttentionGovernor(), "compliance": ComplianceGovernor()}
```

Adding a **risk category** is one import and one dict entry. Adding a whole
**governance domain** — an ESG governor, a sustainability governor, a
data-residency governor — is also one import and one dict entry, because the
protocol is uniform across tiers.

> "Our extensibility isn't a roadmap slide. It's the same one-line pattern at
> two levels of the hierarchy, and I'll add a sixth detector live right now if
> anyone wants to see it."

Have `detectors/toxicity.py` written, tested, and commented out of the registry.
If a judge takes the bet you win the room. If nobody does, you still said the
boldest sentence in it.

---

# 8 · Request flow, end to end

```
inbound request (system_id, prompt, action_class, audience)
   │
   ├─▶ SUPERVISOR · admission
   │     asks every governor: may this system send traffic right now?
   │     • suspended        → refuse before one token is spent, ledger it
   │     • quarantined      → permit only read/draft
   │     • throttled        → 429 with a retry hint
   │     • downgraded       → pin a cheaper model tier
   │     • tightened        → derive a stricter Policy for this system
   │
   ├─▶ LOOP 1 · the existing gate, unchanged
   │     retrieval → provider → specialists (the five detectors, concurrently,
   │     under the policy latency budget) → price → route → release
   │     Identical logic. Identical numbers. Now running under a policy the
   │     governors may have tightened.
   │
   ├─▶ LEDGER · decision record + arbitration record, hash-chained, signed
   │
   └─▶ LOOP 2 · governors observe the record, update per-system state,
         re-arbitrate, actuate, and verify their previous action worked
                                  │
                                  └─▶ fleet view, advisor, review queue
                                        │
                                        └─▶ LOOP 3 · human verdict → calibration
```

## 8.1 One invariant worth designing for deliberately

**With no standing controls and no fleet state, the flow must reduce exactly to
today's behaviour.**

That is why `eval/run_eval.py` runs with the fleet layer inert, and why your
published precision, recall and operating-point curve remain valid without a
re-run. It is not a hedge — it is the clean statement of what v2 adds:

> "The per-request decision is provably unchanged. What we added is governance
> *across* requests. Same reflex, new nervous system."

That sentence is worth more in Q&A than any feature.

---

# 9 · How this adapts to any use case

Sir's real test: *divorce the control plane from the use case.*

Adding an AI system to the fleet is **one entry in `systems.yaml`**:

```yaml
- id: forecast-agent
  name: Demand Forecasting Agent
  owner: Kavita Rao
  department: Supply Chain
  profile: decision_support          # which policy governs it
  jurisdiction: in
  budget_inr_month: 30000
  review_hours_week: 8
  action_classes: [advise, decide]   # its blast-radius envelope
  status: active
```

No code. No new detector. No new agent. The governors are **use-case agnostic
by construction** because they read policy and blast radius, never content. A
resume screener, a forecasting model and a payments bot are all just different
`action_class` envelopes with different budgets.

**And a system in traffic but absent from the registry shows as
`unregistered`.** That is your honest, minimal answer to the shadow-AI problem
all three competitors headline — you notice, you do not claim to discover.

**Deployability:** the gate remains stateless per request; only fleet state is
shared, and it is derived from the ledger, so it can be rebuilt from the
evidence store at any time. Horizontal scaling changes exactly one component —
the ledger backend. Nothing in the agent hierarchy changes shape.

---

# 10 · The three scaling answers, now much stronger

**Performance.** *"Measured, not estimated — `eval/capacity.py` runs the real
gate under concurrency: ~330 gated requests/second on one process, p50 48 ms.
The gate is stateless per request, so it scales horizontally. Fleet state is a
projection of the ledger, so it rebuilds from evidence rather than needing
replication. The only component that changes shape at scale is the ledger
backend."*

**Features.** *"Two registries, one pattern. A new risk category is one line. A
new governance domain — ESG, residency, sustainability — is also one line,
because governors and specialists share a protocol. I'll add one live."*

**Personas.** *"Each persona already has an agent working for them. Adding the
CISO view didn't mean a new backend; it meant surfacing what the compliance
governor was already computing. The dashboard is a view onto agents, not a
report over a database."*

---

# 11 · The demo, rebuilt around the architecture

**Land on the fleet.** Fifteen systems, four green-amber-red columns — one per
governor. This is Priya's screen.

**Beat 1 — exposure.** `order-desk` 40 findings, green. `treasury-bot` 3
findings, red. *"We price consequence, not incidents."*

**Beat 2 — an agent conflict, live.** Open `hr-copilot`. The fairness specialist
is **requesting** promotion to inline — flip rate rising. The budget specialist
is **vetoing** — 104% of budget. Show the arbitration record. `action_class` is
`decide`, which is irreversible, so **Rule 1** applies and safety wins over cost.
*"That decision was made by the supervisor, recorded in a signed ledger, and you
can ask it why."*

**Beat 3 — the second budget.** Switch to Arun's view. `claims-desk` inside its
money budget, over its human budget. *"94.8% of what oversight costs is human
attention. This is the only dashboard that treats it as a budget."*

**Beat 4 — control.** The cost agent recommends suspension. Arun clicks
**Suspend** — or raises the budget. The light changes. *"That is the difference
between a dashboard and a control plane."*

**Beat 5 — the advice.** *"68% of this system's prompts are near-duplicates.
Enable caching, save ₹6,100 a month."* *"We don't stop you at the signal. We
tell you what to do tomorrow."*

**Beat 6 — the closed loop.** The promotion issued in beat 2, 24 hours on:
exposure down 38%, latency up 290 ms, inside budget. *"The agent checked whether
its own intervention worked."*

**Beat 7 — the offer.** *"Adding a sixth risk category is one line. Would anyone
like me to add one now?"*

---

# 12 · Anticipated hostile questions

**"Isn't this just modules you've called agents?"**
> "Fair challenge — that's usually true. Here's our test: our agents want
> different things and they conflict. The cost agent vetoes the fairness agent's
> request for more compute. Something has to arbitrate, and that arbitration is
> recorded and signed. You can't write that as a pipeline, and you can't audit a
> pipeline's reasoning."

**"Why not one agent with a big prompt?"**
> "Because three of our four governors need to be deterministic. A compliance
> decision that varies run to run isn't evidence. We use a model exactly where
> judgement is genuinely needed — a rationed judge above risk price 60, capped
> at 90 calls per thousand requests — and nowhere else."

**"Isn't this ServiceNow AI Control Tower / Prisma AIRS / watsonx.governance?"**
> "Those are security and compliance products, and good ones. They answer: is
> this traffic malicious, is this agent authorised, are we compliant. None of
> them answer ours — given an answer that is well-formed, polite, authorised and
> fully compliant, is it *correct enough to act on*, and how much of our scarce
> human review capacity does it deserve? A prompt-injection filter can't catch a
> confident, fluent, wrong number. We'd sit behind one of those gateways, not
> instead of one."

**"What happens when an agent fails?"**
> "It degrades to zero score, zero confidence, and shows as degraded on the
> fleet view — never silently absent. Same discipline we already apply to a
> detector that throws. A governance system that hides its own failures is worse
> than none."

**"Why should I trust the agents' decisions?"**
> "You shouldn't have to. Every one is in the same hash-chained, HMAC-signed
> ledger as the AI decisions, with the rule applied, the evidence, and any
> constraint we couldn't satisfy. We audit the AI, and we audit the thing that
> audits the AI."

**"Can an agent shut down my production system on its own?"**
> "No — deliberately. Suspension is recommended by an agent and executed by a
> human, because an autonomous agent that can unilaterally halt production is a
> worse risk than the one it prevents. That's the same reasoning that makes us
> ration BLOCK at the request level."

---

# 13 · Build order

Dependency order, not calendar.

1. `agents/base.py` — protocol, `Observation`, `Verdict`, `Request`, `ControlAction`
2. `fleet.py` + `systems.yaml` — registry and `SystemState`, projected from the ledger
3. `control.py` — action taxonomy and application to a resolved `Policy`
4. Four governors, each reading only ledger-derived state (independently testable)
5. Specialists wrapping the five existing detectors, adding memory and bids
6. `supervisor.py` — arbitration rules, actuation, closed-loop verification
7. Two engine hooks — admission before, observation after
8. `/api/fleet`, `/api/fleet/{id}/control`, `/api/arbitration`
9. Fleet view as the landing page; persona switcher = which governor speaks
10. `advisor.py` — cross-governor recommendations, evidence-cited
11. Remaining specialists (budget, triage, capacity, policy, evidence)
12. Dormant `detectors/toxicity.py` for the live-add
13. Apply the ledger cross-process fix, rebuild the ledger clean
14. Verify the invariant: fleet inert ⇒ eval numbers bit-identical

Steps 1–4 are independently testable before anything touches `engine.py`. Step
14 is the gate on the whole thing — if the numbers move, something is wrong in
the wiring, not in the eval.

---

# 14 · What we deliberately do not build

Saying this in the room is a strength, not a weakness. It is the thing that
separates a team that made choices from a team that ran out of time.

- **No LLM planning loop inside the governors.** Compliance and cost decisions
  must be deterministic and reproducible. Non-determinism where judgement is
  genuinely needed only — the rationed judge.
- **No message bus, no separate agent processes.** In-process agents with
  explicit state, because we can show you every transition. Distribution is a
  deployment concern, not an architecture one.
- **No autonomous suspension.** Recommended by an agent, executed by a human.
- **No shadow-AI network discovery.** We flag unregistered systems that appear
  in traffic; we do not claim to find them on the network.
- **No database.** Append-only JSONL, so the evidence store stays readable with
  ordinary tools. At enterprise volume it becomes a real store — we know that;
  it is not a surprise.

---

## The one-paragraph version

> ControlPlane is a hierarchical control system for enterprise AI. Every AI
> system in the organisation subscribes by changing one line. Four governor
> agents — safety, cost, attention and compliance — each own an objective, hold
> persistent state per system, and coordinate specialist agents beneath them.
> They conflict, because their objectives genuinely trade against each other,
> and a supervisor arbitrates using one rule: reversibility dominates. Below the
> irreversibility line the trade is priced in units we already compute; above
> it, safety wins. Every decision — the AI's and the control plane's own — is
> hash-chained and signed. And because we price risk by what an answer *does*
> rather than how it is worded, we can tell a customer which of their fifteen AI
> systems is actually dangerous, rather than which one is noisiest.
