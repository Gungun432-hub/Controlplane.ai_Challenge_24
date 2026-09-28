# Audit — `gungun432-hub-controlplane-v2` worktree

Read line by line on your machine. 1,234 lines across 21 files.
Verdict first, evidence after.

---

# VERDICT

**Do not adopt this as the finale prototype.**

It is a clean, well-typed *scaffold*, and two parts of it are genuinely worth
keeping. But as it stands it **reintroduces the exact defect we spent five
rounds eliminating**, computes the headline behaviour and then ignores it, and
discards everything that made the original credible — the five detectors, the
policies, the jurisdiction overlays, the 31-case evaluation, the capacity
benchmark, and the 1,200-line console.

A jury asking "show me" would find the gap in under two minutes.

---

# CRITICAL — these break the core claim

### C1 · Blast radius is supplied by the caller

`python/controlplane/engine.py`:

```python
async def decide(self, application_id, tool_id, input_data,
                 blast_radius: float, detectors, ...):
    if blast_radius < 0:
        raise ValueError("blastRadius must be non-negative")
```

And it is a **public API field**:

```json
POST /evaluate { "applicationId": "...", "blastRadius": 0, ... }
```

This is the defect we fixed. Blast radius must be *derived* from the action
class and the tool binding. Here any caller can pass `blastRadius: 0` and buy
zero consequence.

Worse: `src/scoring.ts` contains a **correct** implementation —

```ts
export function blastRadius(actionClass, audience = "internal", regulated = false) {
  return Math.min(1, ACTION_RADIUS[actionClass] * (audience === "external" ? 1.15 : 1) * (regulated ? 1.2 : 1));
}
```

— and the Python engine, which is what the server and demo actually run, never
calls it. The two halves of the repo disagree with each other.

Also note the scale: the demo prints `"blastRadius": 80` and `"exposure": 150`.
The original model is **0..1**. Nothing reconciles these.

### C2 · Capability mismatch is detected, then ignored

```python
capabilities, mismatch = self.effective_capabilities(application_id, tool_id)
...
outcome = self._resolve_outcome(executions, self._active_overlay(...))
```

`mismatch` is written into the decision dict and an event. It is **never passed
to `_resolve_outcome`**. It cannot change the outcome.

Your own demo output proves it:

```
capability mismatch: { "outcome": "allow", "capabilityMismatch": true }
```

A tool whose capability was misdeclared was **allowed**. This is the single most
important behaviour in the whole plan and it is currently decorative.

### C3 · There is no action-class derivation at all

```python
def effective_capabilities(self, application_id, tool_id):
    trusted = app.trusted_tool_capabilities.get(tool_id, [])
    capabilities = [c for c in tool.capabilities
                    if c in app.declared_capabilities and c in trusted]
```

This is a set intersection over capability *strings*. There is no
`declared_action_class`, no `effective_action_class`, no upgrade of `draft` →
`execute`, no reversibility, no environment check, no transaction limit, no
approval requirement. The demo beat — *"the agent declared draft and called an
execute-capable production tool"* — **cannot be produced by this code.**

### C4 · There are no detectors

```python
@dataclass(frozen=True)
class Detector:
    id: str
    score: float          # ← the caller supplies the score
    status: str = "passed"
    delay_ms: int = 0
```

Grounding, PII, bias, uncertainty, cost — none exist. The caller passes in the
answer. There is no Luhn/Verhoeff check, no counterfactual probe, no
self-consistency resampling, no source verification. The entire detection layer
of the original is gone.

### C5 · The deadline is still not enforced

```python
executions = await asyncio.gather(*(self._execute(d, decision_id) for d in detectors))
```

No timeout. Waits for everything — structurally the same defect as the original.

And "timeout" is *simulated*, not enforced:

```python
if detector.delay_ms > detector.timeout_ms:
    await asyncio.sleep(detector.timeout_ms / 1000)
    result = {..., "status": "timed_out", "latencyMs": detector.timeout_ms}
```

The detector never starts and gets abandoned at a deadline — the code sleeps the
budget and writes the label. A timeout is a scripted outcome, not a guarantee.
Nothing would stop a genuinely slow detector from blocking the request.

### C6 · The completeness formula is invented

```python
return min(1, (verified / len(detectors)) * (1 / (1 + blast_radius / 100)))
```

Agreed formula: `Σ(blast_radius × fully_governed) / Σ(blast_radius)`.

This is fraction-of-detectors multiplied by a decay term in blast radius — which
makes completeness *fall* as consequence rises even when every detector
completed. Completeness is a statement about evidence, not about risk.

And the portfolio rolls it up as a plain mean:

```python
completeness = sum(d["completeness"] for d in decisions) / len(decisions)
```

Unweighted. Consequence-weighting is absent in both places.

### C7 · The 0/0 bug, exactly as predicted

```python
completeness = ... if decisions else 1
```

Your own `/dashboard` response:

```json
{ "decisions": 0, "completeness": 1, "health": "healthy" }
```

Zero traffic reports perfect governance and a green light. This is the specific
thing we said must report `not_available`.

---

# HIGH

| # | Finding |
|---|---|
| **H1** | Four routes reduced to three: `allow / review / deny`. No **repair**, no hard gate on execute, no contradiction floor, no irreversibility rule. `_resolve_outcome` allows only if *every* detector scores ≥ 0.8 — a blunt AND, not risk pricing. |
| **H2** | Deferred work is not deferred. `drain_deferred()` only runs on `POST /deferred/drain`. Nothing executes in the background, so `verificationLatencyMs` measures how long a human waited to click a button. |
| **H3** | Recommendations have no `rule_version`, no numeric evidence, no expected effect, no ledger references (citations are literal strings like `"governance.completeness"`), no `insufficient_evidence`, no lifecycle. **The README documents `COST.DUPLICATE_PROMPTS` with `expected_savings_inr: 6100` — that rule does not exist in the code.** |
| **H4** | `"spend": exposure` — spend is literally the same variable as exposure. No cost model, no tokens, no rupees. `reviewerCapacity = 100 - backlog*10` and `verificationCapacity = 100 - len(deferred)*10` are arbitrary arithmetic, not budgets. |
| **H5** | `JsonlLedger.append()` calls `self.read()`, which defaults to `limit=100`. So `"index": len(entries)` **caps at 100 and then repeats forever.** Past 100 entries every record claims index 100. |
| **H6** | `append()` has no cross-process lock. Two processes writing the same file interleave — **the exact chain-break bug from the original repo is reproducible here.** |
| **H7** | Two parallel event stores: `self.events` (in memory, `_append`) and `JsonlLedger` (on disk). They are not the same log. |

---

# MEDIUM

- **M1 · `dashboard.html` is 40 lines.** Six stat cards and two `<pre>` blocks of raw `JSON.stringify`. No per-application table, no owner, no traffic light, no budgets, no exposure trend, no drill-down. It is a debug page, not a portfolio.
- **M2 · Two disjoint implementations.** TypeScript `src/` (306+48+34+32 lines) and Python `python/controlplane/` are separate codebases with different models. The tests you ran (`7 passing`) test the TypeScript; the server and demo run the Python.
- **M3 · Nothing from the original survives.** No `policies/*.yaml`, no EU/India jurisdiction overlays, no knowledge corpora, no 31-case evaluation, no `capacity.py`, no calibration/feedback loop, no session accumulator, no Gemini provider, no operating-point curve. **Every published number you have — precision, recall, throughput — is unreproducible in this repo.**

---

# WHY THE WEBSITE 404'd

Your log shows `GET / → 404`. The root route exists at `server.py:60`:

```python
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
```

That route was added **after** the run you logged — it is in commit `774f9bd`,
and you were running the earlier build. Check out `774f9bd` and `/` will serve.

But serving it only gets you the 40-line JSON viewer described in M1. It is not
a prototype you can demo for 4½ minutes.

---

# WHAT IS GENUINELY GOOD AND SHOULD BE KEPT

Not everything here is wasted. Three things are worth porting **into the
original repo**:

1. **`src/scoring.ts`** is a faithful, correct port — `ACTION_RADIUS` values
   exact, ×1.15 external, ×1.2 regulated, noisy-OR at half weight, band
   `(1−confidence)×22`. Whoever wrote it read the original carefully.
2. **The overlay model** (`Overlay` + `add_overlay` + `rollback_overlay` +
   `_active_overlay`) is genuinely good: versioned, scoped, expiring,
   reversible, priority-ordered, with an expiry guard
   (`if overlay.expires_at <= overlay.starts_at: raise`). This is the control
   design we specified, implemented cleanly. **Port it.**
3. **Event stream + rebuildable projection** is the right shape and the right
   separation.

---

# RECOMMENDATION

**Build v2 into `Controlplane.ai_Challenge_24`, not on top of this.**

The original already has: five real detectors, noisy-OR scoring, four-route
routing with the contradiction floor and hard gates, three policy profiles, EU
and India overlays, a hash-chained ledger, the calibration loop, the session
accumulator, a 31-case evaluation with a published operating-point curve, a
measured capacity benchmark, and a 1,200-line console that already looks like a
product.

This repo has an architecture sketch with none of that, plus a defect in the one
idea the whole submission rests on.

The right move is to take the **two good pieces above**, port them into the
original, and then add the v2 layer there in the order we agreed:

```
0  baseline snapshot of the 31 decisions
1  the four failing execution-contract tests
2  Signal.status (8 states) + two clocks
3  wait(timeout=budget_s) — real deadline
4  split pools + bounded deferred queue
5  systems.yaml + tool bindings + effective capability  ← derived, never declared
6  governance completeness, blast-radius weighted, not_available at 0/0
7  fleet projections from the ledger
8  overlays (ported from this repo) + supervisor
9  portfolio page on the existing 1,200-line console
```

Steps 0–6 are Stop A. Step 7 is Stop B — the floor. Step 8 gives you beat 4.

---

## The one thing to take from this exercise

The scaffold documented `COST.DUPLICATE_PROMPTS` with `expected_savings_inr:
6100` in its README while no such rule exists in the code. That is precisely the
failure mode we agreed to avoid — **a claim the implementation does not
support** — and it is the thing a five-minute Q&A is designed to find.

Everything we ship from here should pass one test: *can I run it on this laptop,
right now, in front of the person asking?*
