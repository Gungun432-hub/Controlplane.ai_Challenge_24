# Build to stop points, not to the end of the roadmap

The blueprint's roadmap is a **dependency order** — what must exist before what.
That is correct and I would not change it.

But a dependency order is not a **priority order**, and the difference decides
what your demo looks like if you don't reach the end. Wherever you actually
stop, you want to be standing somewhere coherent.

These are the five coherent stopping points. Each one is a complete, defensible
product. Between them are incoherent states — a rule engine with no portfolio to
run it on, controls with nowhere to display them.

---

## ▸ STOP A — A truthful gate

**Contains:** enforced deadline · deferred queue · detector status · two clocks
· governance completeness · application + tool registry · effective capability

**Demo you can give:** identical text under `draft` and `execute` → two prices,
two decisions. The capability lie caught. Honest degradation with both clocks on
screen.

**What you can claim:** "We price by consequence, we derive consequence from the
tool rather than the caller's word, and we tell you whether the checking was
actually complete."

**What you cannot claim:** anything about a portfolio. This is still one gate.

**Verdict:** strong, novel, defensible — but it does **not** answer Sir's
reframe. It is a better version of what you already had.

---

## ▸ STOP B — A control plane *(the minimum viable finale)*

**Adds:** fleet projections · exposure and exposure/100 · two budgets ·
stale exposure · health states · ternary status (governed / breaching /
**unknown**) · portfolio landing page

**Demo adds:** the portfolio. Five systems, owners, budgets. The consequence
comparison across systems. The grey light.

**What changes:** the product stops being a checker and becomes a control plane.
This is the point at which you have answered *"divorce the control plane from the
use case."*

**Verdict: this is the floor.** Everything before B is preparation; everything
after B is upside. **Get here first, by whatever route.** If you are behind
schedule, cut *depth* anywhere else before you cut your way to B.

---

## ▸ STOP C — Control, not just monitoring

**Adds:** control objects (scoped, versioned, expiring, rollback) · resolved
snapshot composition · Safety + Resource Governors · deterministic supervisor ·
arbitration ledger · human approval gate

**Demo adds:** the conflict — Safety requests fairness inline, Resource vetoes,
Rule 2 decides because the effective class is irreversible. The signed
arbitration record. Arun presses Suspend or raises the budget.

**What changes:** the word "control" in your product name becomes true, and the
architecture reads as genuinely agentic rather than as modules.

**Verdict:** this is where the agentic scoring axis is earned. High value.

---

## ▸ STOP D — Evidence you can hand someone

**Adds:** replay engine → policy simulation · "reproduce this decision" ·
shadow mode + promotion gates

**Demo adds:** reproduce a two-week-old decision under the policy snapshot that
was active at the time, bit-identical. Then a thousand ungoverned answers scored
in shadow.

**What changes:** you acquire a commercial answer to *"who buys this and why."*
The buyer takes no risk and has to trust none of your thresholds.

**Verdict:** highest wow-per-line in the plan, and it is read-only, so it is the
safest thing on the list to build. If you find yourself with a spare evening at
any point, build this rather than polishing C.

---

## ▸ STOP E — Closed loop

**Adds:** deterministic rule engine (rule id, version, cited evidence,
`insufficient_evidence`, lifecycle) · control effectiveness (expected vs
observed) · recommendation cards

**Demo adds:** the numerical recommendation with its rule id, and the control
from beat 4 measured a week later.

**Verdict:** completes the story. Desirable, not load-bearing.

---

# Three amendments to the blueprint

### 1. Cut "Enterprise readiness" from the build list entirely

OIDC/OAuth2 · multi-tenant authorization · Redis · durable queue · key
management · data residency · retention · OpenTelemetry · provider adapters ·
gateway/sidecar integration.

Every one is correct for production and wrong for this. They are the **answer to
a question**, not tasks:

> "In production this becomes a durable queue, a real append-only store,
> per-tenant authorization and OIDC service identity. The architecture doesn't
> change shape — only the storage and identity adapters do. We deliberately
> didn't build them, because we'd rather show you a working control loop than a
> half-finished platform."

That sentence scores. Building them badly does not.

### 2. Drop the "Policy Simulation Agent"

The blueprint says an agent "may help organize replay scenarios." Don't. Replay
must be deterministic end to end, and introducing an agent anywhere near it
weakens the strongest claim you have — that governance decisions are
reproducible — for no gain at all.

### 3. Keep `capability_snapshot_hash`

Small addition, quietly important: it lets a replayed decision prove it used the
same capability bindings, not just the same policy. Without it, "reproduce this
decision" is only half a proof.

---

# One thing the blueprint gets better than I did

> *"Scene 2 — Same answer, different consequence. Use identical content under
> two action classes: draft, execute. Show different risk prices and routes."*

This is a **better opening mechanism than comparing two systems' finding
counts**, which is what I proposed. Identical bytes removes every confound: the
text is the same, the model is the same, the detectors are the same, and the
decision is different. There is nothing left to argue with.

Recommended beat order:

1. **Portfolio** — context. *"We're not checking one chatbot."* (30 s)
2. **Identical text, two action classes** — the mechanism, with nothing to
   confound it. (60 s)
3. **The capability lie** — and now the mechanism has teeth, because consequence
   is derived, not declared. (90 s)
4. **Honest degradation + the grey light** — both clocks, `partially_governed`,
   a system that is grey rather than green. (90 s)
5. **Conflict → arbitration → control** — someone presses the button. (2 min)
6. **Reproduce + shadow** — proof, then the commercial ask. (2 min)

Beats 2 and 3 together are the strongest two minutes available to you, and they
are both inside **Stop A**.
