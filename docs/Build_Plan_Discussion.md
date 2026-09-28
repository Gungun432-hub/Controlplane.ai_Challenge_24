# ControlPlane — Finale Build Plan

Discussion document, not a spec. Argue with it before we write code.
Team Challenge_24 · 23 Sept · Finale 29 Sept – 1 Oct · **6 working days**

---

# PART 0 — The finding that changes the estimate

Before anything else, I went and read your own code rather than reasoning about
it. One thing there resets the whole conversation:

**You already have a fleet. You just never drew it.**

`GateRequest` has carried an `app` field since the beginning
(`engine.py:44`), and **every ledger entry already records it**
(`engine.py:178`). Your demo data already contains **eight distinct AI
systems**:

```
hr-copilot · wealth-advisory · claims-desk · tax-helper
treasury-bot · order-desk · shared-answer · surge-test
```

An HR copilot. A regulated wealth advisor. A treasury payments bot. Those are
*literally three of the four examples Sir invented on the call* — resume
screening, regulated advice, a system that moves money. You built the
multi-system data model months ago and then only ever showed one assistant on
screen.

And every ledger entry already carries everything a fleet view needs:

| Already in every ledger record | Gives you |
|---|---|
| `app` | which system |
| `risk.price` | exposure |
| `decision.action` | pass / repair / escalate / block counts |
| `usage.cost_usd`, `usage.prompt_tokens` | spend against budget |
| `signals[].labels` | which risk categories |
| `action_class`, `regulated` | blast radius mix |
| `policy.id` | which profile governs it |

**So the fleet view is not new instrumentation. It is a `groupby` over a file
you are already writing.** The other AI estimated "half a day" for the fleet
tab and was, if anything, pessimistic on the backend. The real work is the UI.

This also means the pivot is *honest*. You are not bolting a portfolio story
onto a single-use-case demo. You are revealing a portfolio that was always in
the data.

---

# PART 1 — My verdict on the other AI's plan

It did good work. The competitive research is real (I verified all three
vendors — see Part 7), the priority ordering is broadly right, and the
differentiation line about security-vs-correctness is genuinely strong. Take
most of it.

But there is one recommendation in there that I think could lose you the
finale, and two smaller things that are wrong.

## ❌ Reject: the Section 4 core refactor

It proposes rewriting `engine.py`, `router.py`, `scoring.py` and `session.py`
into an Agent protocol — "steps 1, 2, 4, 5, 7 ≈ a day combined."

**Do not do this.** Not because the design is bad — the design is fine. Because
of when you are.

- You are **six days** from a finale, with travel eating one of them.
- `evaluate()` is the function every number you have ever published flows
  through. Your precision, your recall, your capacity benchmark, your ledger,
  your operating-point curve. Touch it and every one of those needs re-running
  and re-verifying.
- Refactor estimates are wrong in one direction only. "A day combined" becomes
  two days plus an evening of debugging why the eval now reports 0.94.
- And the payoff is **a story benefit**, not a capability. The jury cannot see
  your class hierarchy.

The other AI even says *"split `evaluate()` into two named functions; it costs
you nothing functionally."* Every change that has ever broken a demo at 2 a.m.
was described that way.

## ✅ Instead: agents as an additive supervisory layer

You can have a **genuinely, defensibly agentic architecture** without touching
one line of the request path. Here is the trick:

> The agents are not *inside* the gate. They *supervise* the gate.

Two new objects, each with real per-system state, each able to act:

- **CostAgent** — owns each system's spend against its budget. Can admit,
  warn, throttle or **suspend** a system.
- **SafetyAgent** — owns each system's standing risk exposure, breach history
  and detector mix. Can admit, watch or **suspend** a system.

`evaluate()` gains exactly **two lines**:

```python
def evaluate(req: GateRequest) -> GateResult:
    standing = FLEET.admit(req.app)          # ← line 1: agents decide before we spend anything
    if standing.refused:
        return _refused(req, standing)        #    a system-level block, recorded to the ledger
    ...
    # ... the entire existing function, completely unchanged ...
    entry = LEDGER.append(record)
    FLEET.observe(record)                     # ← line 2: agents update their standing state
```

That is the whole integration. Risk of breaking the eval: essentially zero.
And the claim is completely true — two agents with persistent state, their own
decision policies, and the authority to refuse traffic before a single token is
spent.

**And it is a better story than the refactor version**, because the agents
*intercept before the model call*. "Our cost agent refuses the request before we
pay for it" beats "our cost agent scores the response after we paid for it."

## ❌ Reject: auto-suspend firing on its own during the demo

The other AI suggests auto-suspend when a threshold is crossed. In a live demo
that is a loaded gun — a system going red at the wrong moment and you are
explaining a bug instead of a feature.

**Build the rule, but make the *enforcement* an explicit action**: the agent
*recommends* suspension and the light goes red; a human clicks **Suspend**.
That is also better product design — Sir's whole point was that a business owner
holds the remedy. And it is a far better demo beat: *you* press the button.

## ⚠️ Correct: two numbers it got wrong

1. It writes **"95% human-attention / 5% infra / 0.03% model-call."** Your
   verified figures are **94.8% human attention** and **0.03% model API
   calls**. There is no "5% infra" number in your work. Do not let an invented
   third figure into the deck.
2. It cites the MIT NANDA 95% study. You deliberately removed that from the
   mentor email. Keep it out — it is contested, and you do not need it.

## ✅ Take: everything else

Per-system state vs per-response state as the key distinction. Fleet first.
Real control. Insight strings. Don't-build-scale-have-the-answer. The
security-vs-correctness differentiation. All correct.

---

# PART 2 — Three ideas that make this *yours*, not a ServiceNow clone

This is the part neither Sir nor the other AI raised, and it is where the
finale is won. If you build only the fleet view, you have built a worse version
of a product three Fortune 500 companies already ship. You need the fleet view
to show something **none of theirs shows**.

## 💡 Idea 1 — Exposure, not incident count

Every governance dashboard in the world ranks systems by **number of
violations**. That is the obvious metric and it is a bad one, because it treats
a chatbot's typo and a payment bot's wrong figure as one event each.

You already compute something better and you have never aggregated it:

```
exposure = Σ risk_price   over the window, per system
         = Σ P(failure) × blast_radius × 100
```

Exposure is **harm-weighted volume**. It falls straight out of blast radius,
which is your original idea. Consequence:

> `order-desk` had **40 findings** this week. `treasury-bot` had **3**.
> `treasury-bot` is the red one — because its three were on `execute` actions
> and `order-desk`'s forty were on `read`.

**That sentence is your entire differentiation in one line, said over a live
screen.** No competitor's dashboard can produce it, because none of them price
by consequence. Show both **total exposure** and **exposure per 100 requests**
so volume doesn't mask intensity.

This is the single highest-value idea in this document. It costs you a `sum()`.

## 💡 Idea 2 — Human attention as the second budget

Sir reframed you around cost. Your original insight was that **the cost that
matters isn't compute, it's human attention** — 94.8% versus 0.03%. Do not
abandon that to fit his frame. **Fuse them.**

Every system consumes **two budgets**:

| Budget | Unit | Where it comes from |
|---|---|---|
| Money | ₹ / tokens | `usage.cost_usd` — already recorded |
| **Review capacity** | reviewer-minutes | `decision.action` → escalate ≈ 4 min, block ≈ 8 min |

So the fleet card reads:

```
claims-desk        ● AMBER
  Spend            ₹18,400 / ₹25,000      (74%)
  Review capacity  31 / 40 reviewer-hours (78%)   ← nobody else governs this
  Exposure         1,240   (18 per 100 requests)
```

**Nobody in this market treats reviewer capacity as a governed budget.** I
checked. ServiceNow, Palo Alto and IBM all govern machines. You govern the
scarce resource that your own research showed is 94.8% of the real cost.

And it gives you the killer closing line: *"Two of our systems are inside their
money budget and over their human budget. That is the failure mode nobody is
watching, and it is the one that actually stops oversight from happening."*

This is how you keep your core PS insight **and** satisfy Sir's reframe, instead
of choosing.

## 💡 Idea 3 — Prove extensibility instead of claiming it

Sir's feature-scalability axis. Every team will *say* "we can add more
detectors." You have something almost nobody has: a registry where it is
genuinely one import and one dict entry (I verified —
`detectors/__init__.py` is exactly that).

So don't say it. **Offer it:**

> *"Adding a new risk category is one import and one line. If any of you want,
> I'll add a sixth detector live, right now, in under a minute."*

Have `detectors/toxicity.py` written, tested, and sitting in the repo
commented out of the registry. If a judge takes the bet, you uncomment one
line, the server reloads, and a new column appears in the console.

If nobody takes the bet, you still said the boldest sentence in the room at
zero risk. **This is the highest impressiveness-per-hour item on the list.**

---

# PART 3 — What we build, ranked

Ranked by marks per hour. Effort is *realistic*, not optimistic.

### Tier 1 — do these or the pivot fails

| # | What | New files | Effort |
|---|---|---|---|
| 1 | **`fleet.py`** — system registry (`systems.yaml`), per-system state, status computation, exposure, review-capacity | `controlplane/fleet.py`, `controlplane/systems.yaml` | 4 h |
| 2 | **`agents/`** — `Agent` protocol + `Verdict`, `SafetyAgent`, `CostAgent`, `AGENTS` registry | `controlplane/agents/*.py` | 4 h |
| 3 | **Two-line engine hook** — `FLEET.admit()` before, `FLEET.observe()` after | `engine.py` (2 lines) | 30 min |
| 4 | **`/api/fleet`, `/api/fleet/{id}/suspend`, `/resume`, `/budget`** | `app.py` | 1.5 h |
| 5 | **Fleet tab as the new landing page** — one card per system, traffic light, two budgets, exposure, click-through to existing tabs | `dashboard.html` | 6 h |
| 6 | **`advisor.py`** — 6–8 evidence-cited recommendation rules | `controlplane/advisor.py` | 2 h |

**Tier 1 total ≈ 18 hours.** Two people, three days, comfortable.

### Tier 2 — do these if Tier 1 lands early

| # | What | Effort |
|---|---|---|
| 7 | Persona switcher (Business / IT / Audit) — *one* page, changes emphasis, not three apps | 3 h |
| 8 | `detectors/toxicity.py` written and dormant, for the live-add moment | 1.5 h |
| 9 | Seed 4–6 more systems so the fleet looks like a real org (12–15 systems) | 1.5 h |
| 10 | Apply the ledger cross-process fix (**still not applied**) + rebuild clean ledger | 1 h |

### Tier 3 — explicitly NOT doing

Say these out loud so nobody drifts into them at midnight on the 27th:

- ❌ No database. JSONL stays.
- ❌ No authentication, no real multi-tenancy.
- ❌ No refactor of `evaluate()`, `scoring.py`, `router.py`, or any detector.
- ❌ No message bus, no separate agent processes, no LLM planning loop.
- ❌ No sixth detector *registered*. Written and dormant only.
- ❌ No new evaluation runs. Your numbers are published; leave them.

---

# PART 4 — How it works, concretely

## 4.1 The registry — `systems.yaml`

This single file is what "divorces the control plane from the use case."

```yaml
systems:
  - id: treasury-bot
    name: Treasury Payment Assistant
    owner: Arun Mehta
    department: Finance Operations
    profile: decision_support
    jurisdiction: in
    budget_inr_month: 40000
    review_hours_week: 12
    status: active

  - id: hr-copilot
    name: Candidate Screening Copilot
    owner: Priya Nair
    department: Human Resources
    profile: decision_support
    jurisdiction: eu
    budget_inr_month: 15000
    review_hours_week: 20
    status: active
  ...
```

A system that is *not* in the registry but appears in traffic shows as
**unregistered** — which is your (honest, small) nod to the shadow-AI discovery
problem all three competitors headline. You are not claiming discovery. You are
claiming you *notice*.

## 4.2 The two agents

```python
# agents/base.py
@dataclass
class Verdict:
    agent: str                 # "cost" | "safety"
    status: str                # "green" | "amber" | "red"
    admit: bool                # may this system send traffic right now?
    reason: str                # one human sentence, citing a number
    evidence: dict             # the numbers behind it
    recommendation: str | None # what to do about it
```

**CostAgent** watches, per system: spend vs `budget_inr_month`, reviewer-minutes
vs `review_hours_week`, cache hit rate, token-per-request trend.
Turns red above 100% of either budget. Recommends: enable caching, downgrade
model tier, tighten the profile.

**SafetyAgent** watches, per system: exposure, exposure per 100 requests, block
and escalate counts, hard-gate trips, detector label mix, calibration drift.
Turns red on any hard-gate trip or block; amber on rising exposure intensity.
Recommends: redact at source, raise grounding threshold, move bias inline.

**The coordinator** (`fleet.py`) asks both, takes the worse light, and admits or
refuses. That is your architecture slide and it is true.

## 4.3 Status rules — keep them boringly explainable

A judge will ask "why is that one amber?" You need an answer in five words.

```
Cost light:    green < 70%   amber 70–100%   red > 100%   (of either budget)
Safety light:  red    — any block, or any hard-gate trip, in the window
               amber  — exposure/100req above the profile's own escalate threshold
               green  — otherwise
System light:  the worse of the two
```

No magic. Every threshold visible on screen next to the number it judges — the
same principle you already applied everywhere else in the console.

## 4.4 The advisor — always cite the number

Hardcoded rules are fine. What makes them credible is that each one names the
evidence that produced it.

```
❌ "Enable caching to reduce costs."
✅ "68% of this system's prompts are near-duplicates (cache hit rate 0.32).
    Enabling the embedding cache would cut roughly ₹6,100/month."
```

Six to eight rules is plenty. Duplicate prompts → cache. PII findings on
input → redact at source. High escalate rate with low block rate → thresholds
too tight. Bias flips on `decide` actions → move bias inline. Token overrun vs
task-class median → prompt is bloated. Budget pace → project the overrun date.

## 4.5 Information architecture — what Sir actually asked for

```
LANDING (new)     Fleet.  15 systems, traffic lights, two budgets, exposure.
                  One screen. No scrolling. This is "page 1, keep it simple."

CLICK A SYSTEM →  That system's detail: its recent decisions, its agent
                  verdicts, its recommendations, its policy, its ledger slice.

THE SIX TABS →    Unchanged, one level deeper, now scoped by system.
                  Nothing is deleted. Ever.
```

Keep the **Complexity Map** tab prominent in the drill-down. It is your literal
proof that you answered the exam question, which Sir named as requirement one.

---

# PART 5 — Scalability: the three rehearsed answers

Sir was explicit that you should not build this. Memorise these instead. Each
is 25–30 seconds.

**Performance — "5 systems today, 500 tomorrow?"**
> "Measured, not estimated. `eval/capacity.py` runs the real gate under
> concurrency: about 330 gated requests per second on a single process, p50
> 48 ms end to end. The gate is stateless per request, so it scales
> horizontally behind a load balancer — the only component that changes shape
> is the ledger, which moves from append-only JSONL to an append-only store or
> Postgres. Nothing else in the architecture changes. And you can re-run that
> benchmark on this laptop right now if you'd like."

**Features — "what about toxicity, propaganda, ESG?"**
> "Detectors are a registry — one import, one dictionary entry, and the scoring
> layer doesn't know or care which detector produced a signal. Adding a risk
> category needs no change to any existing file. I'll add one live in under a
> minute if you want to see it."

**Personas — "what about the CISO, procurement, audit?"**
> "Every persona is a filtered view over the same ledger and the same agent
> state — not a new backend. Today we ship business and IT. The audit view is
> the ledger plus policy overlays, which already exist; it's a view, not a
> build."

---

# PART 6 — Robustness: surviving the room

A demo that breaks costs more than a feature that's missing. Non-negotiables:

1. **Apply the ledger cross-process fix.** It is still sitting unapplied in
   `out/fixes/ledger.py`. If the chain shows broken on stage while you're
   saying "tamper-evident," that is the worst possible moment.
2. **Rebuild the ledger clean** with no server running, then never run the eval
   and the server together again.
3. **Offline provider as the fallback.** Venue wifi will be bad. Rehearse the
   entire demo in `CONTROLPLANE_PROVIDER=offline` so you can switch in one
   environment variable and lose nothing but generated text.
4. **Warm the embedding cache** before you present — run Policy A/B once. Your
   own notes recorded 569 ms on an 800 ms budget with a cold cache.
5. **A "reset demo" button** that reseeds to a known state in two seconds. If
   anything drifts mid-demo you recover instead of apologising.
6. **Freeze code on the evening of 27 Sept.** The 28th is rehearsal only. No
   exceptions, no "just one small fix."
7. **Screenshot fallback deck.** Every demo beat as a still image, in order, in
   case the laptop dies. You will almost certainly not use it. Build it anyway.
8. **Run the whole thing from a clean clone** once, on the other laptop, before
   you fly. Anything that needs a file only on Adithya's machine is a bug.

---

# PART 7 — Competitive position (verified, not assumed)

I checked all three vendors the other AI cited, because a wrong claim in front
of an Accenture jury is worse than no claim. All three check out — and the
picture is more serious than it suggested.

- **ServiceNow AI Control Tower** genuinely ships agent **kill switches** and a
  discover / observe / govern / secure / measure model across any enterprise
  system.
- **Palo Alto** literally titles its AI Gateway page *"The AI Control Plane for
  the Enterprise."*
- **IBM** now markets an **"Agentic Control Plane"** with agent governance,
  evaluation and lifecycle.

**Read that again: your product name is the exact category label three Fortune
500 vendors converged on in 2026.** That is enormous market validation — and it
means somebody in that room may well ask "isn't this Prisma AIRS?" You need the
answer before they ask it, not after.

### The answer — and I think it's genuinely strong

> "All three of those are **security and compliance** products. They answer: is
> this traffic malicious, is this agent authorised, are we compliant with the EU
> AI Act. Those are real problems and they solve them well.
>
> None of them answer ours. Given an answer that is **well-formed, polite,
> authorised and fully compliant** — is it *correct enough to act on*, and how
> much of our scarce human review capacity does it deserve?
>
> A prompt-injection filter cannot catch a confident, fluent, wrong number. And
> none of them weight that risk by what the answer is about to **do**. We price
> a wrong sentence in a draft at 0.35 and the same sentence executing a payment
> at 1.00. That is the piece that doesn't exist yet."

Then the honest close, which is what actually wins engineers over:

> "We'd sit behind one of those gateways, not instead of one."

And the one gap to own before it's found: **you do not do shadow-AI
discovery.** All three headline it. Your answer: *"We flag unregistered systems
that appear in traffic, but we don't discover them on the network. That's a
v2 item and we'd rather show you what we built than claim what we didn't."*

---

# PART 8 — The story

Ten minutes. Sir's structure: *who is the stakeholder, what is the problem,
whose problem, how, why, what benefit, would they be happy.*

Give the personas names. People remember names and forget architectures.

- **Priya Nair** — Head of AI Platform. Owns the fleet. Gets called when
  something goes wrong. *(IT persona)*
- **Arun Mehta** — Head of Finance Operations. Owns a budget and a team.
  *(Business persona)*
- **Meera** — CISO. Turns up once a quarter and asks for evidence.
  *(The scale persona — mentioned, not demoed)*

**0:00–1:00 — Once upon a time.**
Last year a large consulting firm told every employee to use AI. Within a month
the token bill was frightening — people were using a frontier model to write
two-line emails. In the same quarter, in a different building, a candidate
screening copilot nobody was monitoring had been quietly making decisions about
real people. *(This is Sir's own true story about Accenture. Use it. It is
about the company judging you.)*

**1:00–2:00 — Priya's problem.**
Priya runs the AI platform. She is accountable for both of those failures and
she cannot see either of them. Two questions she cannot answer on any Monday
morning: *what is all of this costing us,* and *what is it doing that we could
not defend in public?* Cost and risk. There is no third question.

**2:00–2:30 — The subscription.**
Any AI system in the organisation subscribes by changing one line — its model
base URL. From that moment two agents stand between it and its users: a cost
agent and a safety agent. Nothing reaches a user without passing both.

**2:30–7:00 — LIVE. This is most of your time.**
- Land on Priya's fleet. Fifteen systems. Eleven green, three amber, one red.
- **The red one is `treasury-bot`** — and here is the sentence: *"`order-desk`
  had forty findings this week. `treasury-bot` had three. `treasury-bot` is the
  red one, because its three were on payment executions and `order-desk`'s forty
  were on reads. We don't count incidents. We price consequence."*
- Click in. Show the actual flagged output, the evidence, the blast radius.
- Switch to **Arun's view**. `claims-desk` is amber — 74% of budget in week two.
  **And 78% of its human review hours.** *"That second number is the one nobody
  else in this market is watching, and our own research says it's 94.8% of what
  oversight actually costs."*
- **Now control it.** The cost agent recommends suspension. Arun clicks
  **Suspend** — or raises the budget. Watch the light change. *"That is the
  difference between a dashboard and a control plane."*
- The recommendation: *"68% of this system's prompts are near-duplicates.
  Enable caching, save ₹6,100 a month."* *"We don't just stop you at the signal.
  We tell you what to do tomorrow."*
- One last beat: the same output judged under two policies, two different
  decisions. *"Governance isn't a property of the text. It's a property of the
  context."*

**7:00–8:00 — Why anyone pays.**
Exhaustive human review of this workload is about ₹20.8 crore a year. Under
ControlPlane, about ₹1.01 crore. But the money isn't the pitch — the pitch is
that oversight becomes cheap enough to leave switched on, and that for the first
time there is a signed, per-decision record to hand Meera when she asks.

**8:00–9:00 — Scale.** The three rehearsed answers from Part 5. Offer the live
detector.

**9:00–10:00 — Close on the people.**
Priya sleeps. Arun controls his own spend without filing a ticket. The developer
knows exactly why they were flagged and how to go green. And Meera, for the
first time, gets an answer to *"why was this allowed to reach a customer?"*

---

# PART 9 — Six days

| Day | Work | Owner |
|---|---|---|
| **Tue 23** | `fleet.py` + `systems.yaml` + `agents/` skeleton. Apply ledger fix. | Both |
| **Wed 24** | Finish agents + `/api/fleet`. **Mentor call 1:30 — show the fleet view even if rough.** Gungun must be on this call. | Both |
| **Thu 25** | Fleet tab UI. Landing page change. `advisor.py`. | Adithya UI / Gungun advisor |
| **Fri 26** | Persona switcher. Seed more systems. Suspend/resume flow end to end. | Both |
| **Sat 27** | Story written. Dormant toxicity detector. Screenshot deck. **Code freeze 8 pm.** | Both |
| **Sun 28** | Rehearse ×5, full run, both laptops, offline mode. Nothing else. | Both |
| **Mon 29** | Travel. Do not open the laptop. | — |

---

# The three questions to answer before we write any code

1. **Do you agree we skip the core refactor?** My position is that the
   supervisory-layer approach gives you 95% of the story for 5% of the risk. If
   you disagree, say so now, not on Saturday.

2. **Is human-attention-as-a-budget in or out?** I think it is the single thing
   that keeps ControlPlane *yours* rather than a student ServiceNow. It costs
   about two hours. But it is the one idea here that is mine rather than Sir's,
   so it deserves an explicit yes.

3. **Who owns the UI?** The fleet tab is ~6 hours of careful frontend work in a
   file that is already 1,200 lines and that you have both been burned by
   before. It needs one owner, not two.

---

**A last thing.** Nothing in this plan throws away what you built. Blast radius
survives — it becomes exposure, and exposure is what makes your fleet view
different from everyone else's. The human-attention insight survives — it
becomes the second budget, which nobody else governs. The detectors, the
ledger, the policies, the evaluation, all untouched.

You are not rebuilding. You are finally showing the thing from the altitude it
was always designed for.
