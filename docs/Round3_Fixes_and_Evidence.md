# Round 3 — every defect fixed, with the evidence

Team Challenge_24 · ControlPlane · Accenture Grand Finale

**Suite: 100 tests, passing. Full browser pass: zero JS errors, zero 4xx/5xx,
zero blocking dialogs.** Everything below was measured, not assumed.

---

## The two P0 defects the audit found

### P0-1 · The console could not drive the server

`dashboard.html` posted to `/api/turn` with `headers:{'content-type':'application/json'}`
while `/api/turn` requires an operator token. Proven before the fix:

```
browser-style POST /api/turn -> HTTP 401
{"detail":"operator token required for mutating routes (header X-ControlPlane-Token)"}
```

Scenario injection and ambient traffic were both dead in the browser. **The core
demo interaction did not work.**

Fixed — both call sites now use `opHeaders()`. Then three things were added so
this class of defect cannot recur:

- **An end-to-end HTTP suite** (`test/test_http_contract.py`) that drives the
  exact request shapes the browser issues: scenario injection, ambient tick,
  control apply, rollback, surge, reset. The old unit tests never sent a header,
  which is precisely why they passed while the demo was broken.
- **A structural test** that parses `dashboard.html` and fails if *any* POST is
  built with a literal header object instead of `opHeaders()`.
- **A test that `actor()` never calls `prompt()`** — the original implementation
  would have opened a modal dialog on the ambient timer, freezing the page before
  anyone clicked anything. The operator name now defaults to `Arun Mehta` and is
  changed from a chip in the masthead.

Ambient traffic is now attributed to `ambient-simulator`, not to the named human,
so the ledger never records machine traffic under a person's name.

### P0-2 · The runtime never applied the policy it published

```python
for name in profile.deferred:
    results.append(DetectorResult(name, status="queued_async",
                                  execution_mode="deferred",
                                  requirement="advisory"))   # hardcoded
```

For `internal_knowledge`, `privacy` is **mandatory and deferred**. It was
labelled advisory, so `governance_status()` returned `fully_governed` where the
truth was `awaiting_verification`. The round-2 fix to `governance_status` was
correct and never fired, because the helper was tested with hand-built inputs.

Fixed — the requirement now comes from `profile.mandatory`. Tests now go through
`plane.turn()`, not through hand-built `DetectorResult`s.

A second bug surfaced in the same block: a detector dropped by a saturated queue
was recorded **twice** — once `failed`/`queue_saturated`, once `queued_async`. A
reader could see the softer record and conclude the work was merely pending. The
duplicate is gone.

---

## Defects found and fixed during verification

### The gate could serve requests with dead detector pools

`gate.shutdown()` shut down module-global executors permanently. The process kept
serving; every detector submission raised. Found by the new HTTP suite, whose
second test created a second app in the same process.

Pools are now created on demand and rebuilt after shutdown, and a refused
submission is recorded as `failed` / `executor_unavailable` — never priced as a
clean zero. *A governance runtime that answers without checking anything is the
exact failure this product exists to prevent.*

### "Reproduce this decision" said IDENTICAL while showing two different bands

On screen, during a demo:

```
IDENTICAL ✓
recorded  ESCALATE · price 80 · band 76–84
replayed  ESCALATE · price 80 · band 75–85
```

Two causes. First, replay re-derived from `record["detectors"]`, which is a
**living list** that deferred verification amends — so it compared a decision
against evidence that did not exist when the decision was taken. Second,
`identical` compared only action and price, so the divergence it was showing the
viewer did not register.

Fixed:
- `detectorsAtDecision` — an immutable snapshot of the evidence as it stood at
  decision time, written once and never rewritten. Replay reads this.
- The comparison is now **eight canonical fields**: action, price, band,
  p_failure, dominant signal, governance status, side-effect state, and a hash of
  the released text. The receipt says how many fields were compared and names any
  that differ.

Verified live in the browser after the fix:

```
IDENTICAL ✓ — 8 fields compared
recorded  BLOCK · price 74 · band 68–80 · fully_governed · withheld
replayed  BLOCK · price 74 · band 68–80 · fully_governed · withheld
```

### A jurisdiction overlay could *loosen* a base profile

`resolve_profile`'s own docstring says "Overlays only ever tighten." It used
`weights.update(j["weights"])`, and India's privacy weight of `1.0` silently
relaxed `decision_support`'s `1.1`.

Fixed to `max(base, overlay)`. A test now proves the guarantee across **every**
profile × jurisdiction combination shipped, plus control overlays.

### The user's own prompt counted as evidence

```python
pool = _words(" ".join(sources) + " " + prompt)
```

A claim could look grounded because the person asking supplied the vocabulary.
That is a laundering hole, not a detector.

Support is now measured against the server-resolved corpus alone. Numeric checks
split into three honest categories:

| Case | Before | Now |
|---|---|---|
| Figure in a source | supported | supported |
| Figure in neither source nor question | contradiction | contradiction (unchanged) |
| Figure the **user** supplied, in no source | looked supported | `unverifiable`, recorded as *"figure repeated from the question, confirmed by no source"* |

Measured after the fix:

```
supported            score=0.0  labels=[]
fabricated           score=1.0  labels=['hallucination'] contradiction=True
laundered-by-prompt  score=1.0  labels=['unverifiable']
laundered-hard       score=1.0  labels=['unverifiable']  (figure echoed from the question)
```

### The console showed systems as suspended long after the control expired

`app.state` was an attribute written when a control was applied and never
unwritten. The gate reads the overlay's TTL, so when it expired traffic resumed —
while the console still showed the system suspended and red. **The runtime and
the picture of the runtime disagreed**, which is the one failure mode this
product cannot have.

State is now derived from live overlays on every read (`state_of()`), with a
`recovering` window after a control ends.

### The verification clock read 23 minutes on a freshly booted demo

`Freshness SLO · verification = 1410621 ms p50`

Verification latency was measured from `createdAt`, which seeded history
deliberately backdates so the console has a past. Now measured from
`processedAtEpochS` — the real wall-clock moment the decision was processed.

After the fix, on a fresh boot: `0.2 ms p50`.

### A timezone bug that would only have appeared on the demo laptop

```python
time.mktime(datetime.fromisoformat(...).timetuple())
```

`mktime` reads a UTC timetuple as **local** time. Invisible on a UTC server;
**off by 5 h 30 m in IST**, which is where the demo laptop runs. "Oldest pending"
would have read hours instead of seconds on stage.

Replaced with `.timestamp()` on a tz-aware datetime. A test now scans every
module and fails if `mktime` reappears in code.

### A bias probe the model declined to answer was scored as bias

`decide_probe` can return `"unknown"`. `fairness` treated `approve != unknown`
as a flip — a false positive manufactured out of a model that simply did not
reply. Inconclusive probes are now excluded from the flip rate and recorded; if
every probe is inconclusive the detector reports `failed` /
`probes_inconclusive` rather than a clean zero.

### The cost window was unsynchronised and unexplained

`CostWindow` was mutated from two thread pools at once — a read could sort a list
another thread was truncating. It now holds a lock, and every cost result records
the window it was derived from (`windowSize`, `median`, `keep`), so the number on
a receipt is auditable. On a cold window it now says *"no history yet … so no
comparison is claimed"* instead of implying a ratio of 1.0.

### Budget changes were unvalidated, unattributed and lost on restart

`/api/budget` wrote an attribute. NaN, infinity, zero and negative all accepted —
a zero budget makes every utilisation reading nonsense. Nothing was written to
the ledger, so **an operator action left no evidence** and a restart silently
reverted it.

Now `plane.set_budget()`: validated, attributed to the authenticated actor,
written as a `budget.changed` ledger event, and replayed by `recover()`.

---

## The SURGE beat now actually degrades

It never did. `/api/surge` ran `turns` calls **sequentially in one thread**, so
each turn's deferred work drained while the next was still generating. The queue
never built a backlog and nothing degraded — the beat was theatre.

It now fires the burst concurrently. Measured:

| Load | Wall | Decision p95 | Backlog | Queue depth | Stale exposure | Health |
|---|---|---|---|---|---|---|
| 40 × 16 | 633 ms | 44.8 ms | 33 | 48 | 12.19 | **degraded** |
| 150 × 32 | 2.9 s | 58.6 ms | 162 | 256 | 67.0 | **degraded** |
| 200 × 32 ×3 | 8–25 s | 104 ms | 332 | 503 | 125.7 | **degraded** |

At the third level the queue saturates and the saturation path fires exactly as
documented:

```
droppedVerification: 200   ledgerErrors: 0
verification: {'pending': 200, 'verification_incomplete_due_to_capacity': 200}
governance:   {'fully_governed': 200, 'partially_governed': 200}
```

**This is the two-clocks beat, and it is now real:** the decision clock holds at
104 ms against an 800 ms budget while the verification clock stretches, the fleet
reports `GOVERNANCE DEGRADED`, and not one turn is lost or silently dropped.

The surge also no longer swallows exceptions — failures are counted and sampled
in the response. A surge that quietly drops turns is the same dishonesty the
product exists to remove.

---

## New: proposed → executed, on every receipt

A verdict on text is not the same object as a change to the world, and a receipt
that renders them identically is useless to an auditor. Every decision now
carries an explicit `sideEffect`:

`withheld` · `held_for_human` · `released` · `performed` (and the two
`…_after_repair` variants), each with `changesTheWorld` — so **a blocked draft
and a blocked `execute` are no longer the same event**.

The console shows it as two panels side by side. Live, on the capability lie:

```
THE AGENT PROPOSED              WHAT ACTUALLY HAPPENED
DRAFT · restart_service         NOTHING HAPPENED
"Restarting payment-gateway-    the tool call was not issued
 prod now. Expect a 30 second
 interruption."
```

One behavioural change came out of this. On a capability mismatch the gate used
to discard the text as well as the action. It now **refuses the action and hands
the text back as a draft**, marked *"returned to the developer as a draft, not to
the audience."* That is the difference between a control plane and a wall: the
action is denied, the work is not destroyed, and the audience still never sees
it.

---

## New: `/developer` — "You were flagged. Here is exactly why."

The README promised a developer page; the route existed only in the deleted
scaffold and pointed at a file that was not there. It exists now, and it is the
second audience in the story — the developer who gets told "blocked" and
otherwise nothing.

Four sections:

1. **Integrate** — the one-line `base_url` change, the direct `curl`, and the
   fields that are **refused outright** (`blastRadius`, `riskPrice`,
   `action/route`, `sources` as text, `governanceStatus`) with the reason: if the
   caller could supply them the governance would be decorative.
2. **The policy in force for your system** — a new `GET /api/policy/{system_id}`
   showing base → resolved thresholds and weights with the overlay arithmetic
   spelled out, which detectors are inline vs deferred vs mandatory, the tool
   bindings that determine effective action, active controls with who approved
   them and when they expire, and the citable source IDs (IDs only — handing out
   the corpus text would let a caller reverse-engineer a passing answer).
3. **What we do not claim** — the limits, in the developer's face, before they
   argue with a score.
4. **Probe a decision** — pick a system, a tool and a message, run it through the
   real gate, and read back the full arithmetic: `blast_radius ← ACTION_RADIUS ×
   audience`, `p_failure ← noisy-OR`, `risk_price = p × radius × 100`, the band,
   the thresholds it was measured against, and what to change in your code.

The two views link to each other from the masthead.

---

## Repository housekeeping

- `engine.py`, `server.py`, `seed.py`, `fixtures.py` moved to `legacy/` with a
  README stating exactly why each was replaced. Imported by nothing.
- `__init__.py` rewritten with lazy attribute access, so importing the package
  does not drag in the provider layer and break the offline guarantee.
- **Root `README.md` rewritten.** It previously started a runtime that no longer
  exists.
- `requirements.txt` consolidated; `requirements-v2.txt` gone; unused `numpy`
  dropped.
- `.gitignore` and `.env.example` added. **`.env` is ignored; the key is never
  committed.**
- `smoke.py` no longer hardcodes an absolute path.
- Favicon added — a control plane logging a 404 on every page load is not a good
  look on a projector.
- `CONTROLPLANE_SEED_TURNS` added so a rehearsal reset does not pay for 110 turns.
- FastAPI `on_event` migrated to `lifespan`; the deprecation warnings are gone.
- A malformed CSS line (`:root:not(...) @media ...{}`) removed.

---

## Run sheet notes for the demo

1. **Click beat 1 (portfolio) before any it-ops scenario.** IT Operations Agent
   is grey/`NO SIGNAL` on a fresh boot because it stopped reporting. The moment
   you run the "Restart the payment service" scenario it starts reporting and
   goes red. That ordering is already what the 8-minute script says — just don't
   improvise.
2. **For the capability-lie beat, prefer "Campaign → all external" or "Same
   campaign, in Finance" over "Restart the payment service."** The restart case
   trips *two* refusals at once — the environment check (staging-only tool in
   production) fires before the mismatch, so the headline reason on screen is the
   environment, not the lie. The campaign case is the pure version: declared
   `draft`, binding proves `execute`, radius 1.00, blocked, text returned as a
   draft.
3. **Read the ops strip immediately after SURGE.** The backlog drains in about
   ten seconds. That is the honest behaviour, and it is also the window in which
   the beat is visible.
4. **`Reset demo` archives the old ledger** rather than blending epochs, and
   reseeds in about two seconds. It is safe to press mid-rehearsal.

## Still open — not code

- Email Manjula for the Accenture 16:9 template and to ask what the jury expects.
- Gungun should attend the next mentor call.
- The TypeScript core (if it is still in the repo) diverges from the Python: a
  different completeness formula, and it returns 1 at zero decisions where Python
  correctly returns `not_available`. It is not on the demo path — delete it or
  align it, but do not ship two cores that disagree.
- **Rotate the Gemini API key after submission.** It was pasted in chat and
  appeared in screenshots. Treat it as exposed.
