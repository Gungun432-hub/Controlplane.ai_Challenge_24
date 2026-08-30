# Coverage against the Round 2 brief

Sixteen points are named in the Round 2 brief for Problem Track 1: seven
real-world complexities, six solutioning areas, and three reference parameters.
Each is listed below with what implements it, where the code lives, and how to
see it running. Where our coverage is partial we say so rather than claiming the
point.

Legend: **Implemented** — working in the prototype. **Partial** — implemented
with a stated limitation.

---

## Real-world complexities (7)

### 1. Different use cases have different risk tolerance and latency budgets
**Implemented.** Three policy profiles run concurrently, each with independent
thresholds, dimension weights, latency budget, review queue, judge budget and
inline/asynchronous detector split.

| Profile | Audience | Latency budget | pass / repair / escalate |
| --- | --- | --- | --- |
| `customer_support` | external, regulated | 800 ms | 22 / 40 / 62 |
| `internal_knowledge` | internal | 2500 ms | 38 / 58 / 78 |
| `decision_support` | external, regulated | 6000 ms | 12 / 28 / 44 |

Latency budgets are enforced, not documented: inline detectors run concurrently
against the budget and demote to asynchronous rather than overrun, and the
shortfall is recorded on the ledger entry.

*Code:* `controlplane/policies/*.yaml`, `config.py`, `engine.py`
*See it:* Policy A/B tab, scenario 1 — the same answer repairs under
customer-facing policy and passes under internal.

### 2. Bias, hallucination and privacy overlap
**Implemented.** Detectors return a multi-label `Signal`; one finding may raise
several labels. An unsupported claim containing a person entity raises
`hallucination` and `privacy` together, and the risk price compounds overlapping
signals through a noisy-OR term at half weight rather than double-counting one
underlying problem.

*Code:* `detectors/base.py`, `detectors/grounding.py`, `scoring.py`
*See it:* Assistants tab — ask the claims-desk assistant to summarise a claimant;
the reply carries both labels.

### 3. No reliable real-time ground truth
**Implemented.** We never claim to detect falsehood. Grounding measures whether
each claim traces to retrieved source text, using lexical containment first and a
dense embedding only where containment fails. A claim no source covers is
labelled `unverifiable` — a distinct outcome from wrong — and the router
abstains, releasing the answer with the uncertainty stated instead of guessing.

*Code:* `detectors/grounding.py`, `router.py`
*See it:* Assistants tab — "Am I eligible for the 80C tax rebate?" retrieves
nothing authoritative and the assistant says so.

### 4. Over-flagging causes alert fatigue; under-flagging creates liability
**Implemented.** A 31-case labelled evaluation set, roughly half of which must
*not* be flagged, including deliberate false-positive traps: a Luhn-failing
sixteen-digit order reference, a Verhoeff-failing twelve-digit asset tag, a
correctly hedged answer, and a correct refusal. We publish precision, recall,
false-positive and false-negative rates and a sweep of the operating point.

Tightening the grounding threshold past the shipped 0.55 buys no additional
recall and immediately costs precision. That knee is why 0.55 ships, and the
sweep is in the repository so the choice can be argued with.

*Code:* `eval/dataset.jsonl`, `eval/run_eval.py`
*See it:* Tuning tab.

### 5. Multi-turn conversations and agents compound risk
**Implemented.** A session carries a decaying risk accumulator; each turn's price
feeds it and the accumulated value raises the floor of `P(failure)` for later
turns, so the third borderline answer is treated more seriously than the first.
Agentic risk is handled through the action class: blast radius comes from what
the output *does* (`read`, `draft`, `advise`, `decide`, `execute`), and policies
may declare a hard gate on an action class regardless of content.

*Code:* `session.py`, `scoring.py`, `router.py`
*See it:* Assistants tab — the session-risk meter climbs across turns.

### 6. Regulatory expectations differ by geography and industry and evolve
**Implemented.** Policy is data, not code. Use-case profiles and jurisdiction
overlays are YAML, versioned, and hot-reloadable through
`POST /api/policies/reload`; no regulatory logic is compiled into the service.
Overlays compose on top of any profile and only ever tighten. EU (GDPR +
EU AI Act) and India (DPDP 2023) ship, each carrying its own threshold deltas,
weight overrides, required evidence fields and retention period.

*Code:* `policies/jurisdictions/*.yaml`, `config.py`
*See it:* Policy A/B tab, scenario 2 — the EU overlay escalates what the India
overlay repairs, from identical bytes.

### 7. Models are consumed via API; internals cannot be inspected
**Implemented.** Nothing reads logits, attention or any other model internal.
Every signal derives from text we can see: the prompt, the retrieved sources and
one or more sampled completions. Uncertainty is black-box self-consistency —
resample and measure semantic agreement — because most managed APIs do not expose
log-probabilities. Log-probs are accepted as an optional fast path where a
provider offers them but are never required.

Round 1 of this project proposed reading token log-probabilities. That was wrong
for the stated enterprise setting and we changed it.

*Code:* `detectors/uncertainty.py`, `providers/base.py`

---

## Solutioning areas (6)

### 8. Detection techniques
**Implemented**, across all five named approaches.

| Named technique | Implementation |
| --- | --- |
| Rule-based heuristics | numeric consistency, meta-sentence filtering, action-class gates |
| Embedding / statistical anomaly detection | dense cosine grounding, self-consistency agreement, token-overrun statistics against a rolling per-task baseline |
| Secondary "AI-as-judge" | `provider.judge()`, rationed by per-policy price threshold and call budget |
| Retrieval verification against source documents | `detectors/grounding.py`, hybrid lexical + dense with numeric override |
| Dedicated PII / entity detection | `detectors/pii.py`, Luhn for cards, Verhoeff for Aadhaar, patterns for PAN, IBAN, email, phone |

Plus one the brief does not name: a **counterfactual bias probe** that holds the
case constant, swaps only a protected attribute, and checks whether the decision
flips.

### 9. Decision logic
**Implemented.** Confidence scoring: every risk price carries a confidence band
derived from detector confidence, and no interface renders a bare verdict. Tiered
responses: `pass` / `repair` / `escalate` / `block`. Clear rules for pulling in a
human: escalation above a per-policy threshold, or any hard-gated action class,
routed to a named review queue.

One rule sits above the price. A numeric claim contradicting the source of record
is a fact about the text, not a probability judgement, so it can never route to
pass however low-stakes the surface looks.

*Code:* `scoring.py`, `router.py`

### 10. Architecture
**Implemented**, in all three positions the brief names.

- **Pre-response gate** — `POST /v1/gate` scores a completion before release.
- **Inline middleware** — `POST /v1/proxy/chat` and `POST /v1/chat` sit in the
  call path; adoption is one base-URL change.
- **Post-hoc audit** — asynchronous detectors refine the record after release,
  and the trust ledger is the audit surface.

Checks run in parallel to protect latency: inline detectors execute concurrently
in a thread pool against the policy's budget and demote to asynchronous rather
than overrun. Grounding resolves lexically before embedding, so ordinary grounded
traffic makes no model call at all.

*Code:* `engine.py`, `app.py`

### 11. Governance
**Implemented.** A configurable policy layer varying by use case, geography and
risk appetite, plus an audit trail behind every decision. The trust ledger is
append-only, hash-chained and HMAC-signed; each entry records the prompt and
answer previews, every detector signal, the price and its band, the decision and
its reason, the policy id and version, the jurisdiction and regime, the
calibration offset in force, latency against budget, and any human override with
the reviewer's id.

Stated honestly: this is tamper-**evident**, not tamper-proof. Anyone holding the
signing key can rewrite history; the chain gives detection, and
`GET /api/ledger/verify` reports the first index that fails.

*Code:* `ledger.py`, `policies/`
*See it:* Ledger tab.

### 12. Feedback loops
**Implemented.** A reviewer marks an escalation `confirmed` or `false_alarm`. The
verdict is written to the ledger as a first-class entry with the reviewer id, and
moves a per-profile calibration offset: confirmed flags lower thresholds, false
alarms raise them. The offset is bounded at ±12 points, stepped 1.5 per verdict,
and reported through the API and on the dashboard.

Deliberately not online gradient training. At the volume a reviewer queue
realistically produces, a bounded bias term you can explain to an auditor beats a
model nobody can account for.

*Code:* `feedback.py`, `app.py:/api/override`
*See it:* Review Queue tab — mark one and watch the offset move.

### 13. Metrics and monitoring
**Implemented.** False-positive and false-negative rates, precision, recall and
F1 on a labelled set, with per-category breakdown and two operating-point sweeps.
Runtime telemetry reports added-latency p50/p95/p99, per-detector latency,
routing mix by profile, model calls, judge call rate, token counts, estimated
cost per thousand interactions, latency-budget breaches, and override counts.

On reporting trustworthiness to a sceptical stakeholder, the honest position is
in the README: our evaluation set was authored by us and the detectors were
iterated against it, so a perfect score is a regression guard, not evidence of
generalisation. Phase 1 of the roadmap is an independently authored held-out set.

*Code:* `telemetry.py`, `eval/run_eval.py`

---

## Reference parameters (3)

### 14. An enterprise operating multiple AI use cases at once, each with different latency and risk tolerance
**Implemented.** The three profiles are exactly the brief's examples — a customer
support assistant, an internal knowledge assistant and a decision-support tool —
running concurrently over separate retrieval corpora, and demonstrably disagreeing
with each other on identical input.

### 15. Tens of thousands of interactions per week combined
**Implemented and measured.** `python eval/capacity.py` runs the real gate under
concurrency and reports sustained throughput.

Measured on one process: **303 gated requests per second**, end-to-end p50 39 ms
and p95 55 ms under a concurrency of 12. That is roughly **183 million
interactions per week**, against the 50,000 per week used in the business case —
about 3,600x headroom on a single process, before any horizontal scaling.

This measures the governance layer's own cost. Live embedding and judge calls add
provider latency on the small fraction of traffic that needs them, which is the
point of rationing them.

### 16. A mix of well-governed and loosely governed internal data sources
**Implemented.** Every document in every corpus carries a governance grade and an
owner. The grade is not decorative: loosely-governed sources reduce the
confidence of the grounding verdict and raise the residual risk, because a claim
supported only by an unowned wiki page is supported more weakly than one traced
to an owned, versioned document. The grade is shown against each retrieved source
in the assistant reply.

*Code:* `knowledge.py`, `detectors/grounding.py`
*See it:* Assistants tab — the internal copilot's expenses question retrieves an
unreviewed wiki page and is scored accordingly.

---

## What we did not claim

- The evaluation set is ours, and the detectors were tuned against it.
- The offline embedder is a character n-gram hashing vectoriser, not a neural
  encoder; it is deterministic and free, which is why the repository runs with no
  key, but it is weaker on paraphrase than the live path.
- The bias probe requires a decision that reduces cleanly to approve or decline;
  free-text recommendations return not-applicable rather than a fabricated score.
- The ledger is tamper-evident, not immutable.
- Cost figures are estimates from published list prices, not billing data.
