# ControlPlane

ControlPlane is a model-agnostic sidecar that prices the risk of every AI
response before it reaches a user, and spends oversight in proportion to that
price. Most enterprise AI checking is uniform and retrospective: every response
is treated the same, and failures surface in an audit weeks later, after someone
has already acted on the answer. ControlPlane inverts that. It scores each
response in the live path across three dimensions - performance, cost and
responsibility - combines that with what the answer is about to do downstream,
and routes on the result.

The design principle behind it is operational rather than theoretical. Checking
everything makes an assistant slow and irritating, and a safety system that
irritates people gets switched off. A safety system that is switched off provides
zero safety. So ControlPlane lets most traffic through untouched and reserves
real scrutiny, and real cost, for the small fraction of responses where being
wrong is expensive.

Built for the Accenture Innovation Challenge 2026, Round 2, Problem Track 1
(ControlPlane.ai), by team Challenge_24.

## Running this without an API key

**You do not need an API key to run this project.** Clone it, install the
requirements, start the server, and everything works: the dashboard, all
scenarios, the full evaluation harness. ControlPlane ships an offline provider
so a reviewer can verify every claim in this document on a laptop with no
account, no billing and no network.

There are two modes, and the service tells you which one it is in at
`GET /health`.

| Mode | Setup | What runs | What is different |
| --- | --- | --- | --- |
| **Offline** (default) | nothing | detectors, routing, policy, ledger, telemetry, evaluation | embeddings come from a local hashing vectoriser; self-consistency and the bias probe abstain, because neither is meaningful without a real model to resample |
| **Live** | your own Gemini key in `.env` | all of the above, plus Gemini embeddings and LLM-as-judge | the two abstaining detectors activate |

If you want the live path, the key is **yours, not ours** - get a free one at
<https://aistudio.google.com/apikey>, put it in a local `.env`, and set
`CONTROLPLANE_PROVIDER=gemini`. No credential of ours is in this repository, and
none is needed to evaluate it.

Offline results deliberately **under-report** what the live system detects. We
would rather a reviewer see a lower number they can reproduce than a higher one
they cannot.

## Table of contents

- Running this without an API key
- Requirements
- Installation
- Configuration
- How it works
- Key features
- Where AI is used, and where it deliberately is not
- Acceptance criteria we set ourselves
- Evaluation
- Runtime telemetry
- Scenario suite
- Design decisions and tradeoffs
- Limitations and what we did not build
- Roadmap
- Troubleshooting
- FAQ
- Maintainers

## Requirements

Python 3.10 or newer. All Python dependencies are listed in
`requirements.txt` and install with pip:

- `fastapi` and `uvicorn` - HTTP surface
- `pydantic` - request validation
- `pyyaml` - policy loading
- `numpy` and `scikit-learn` - embeddings and vector maths
- `httpx` - provider calls

**No API key, no account and no network access are required to run or evaluate
this project.** The offline provider is the default and is a real code path, not
a mock: the same detectors, the same router, the same ledger. A Google AI Studio
key is optional and enables the live path only.

## Installation

```
git clone https://github.com/<your-account>/controlplane.git
cd controlplane
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn controlplane.app:app --port 8000
```

That is the whole setup. No `.env`, no key, no further configuration.

Open http://127.0.0.1:8000. On a fresh clone the ledger is empty, so the
dashboard runs a short burst of representative traffic through the engine on
first load and arrives populated - fourteen requests across three use-case
profiles, showing passes, escalations and one hard block. Those are real
evaluations, not fixtures: the same detectors, scorer, router and ledger entries
as any other request. The scenario buttons along the bottom then let you drive
specific cases, and the policy dropdowns let you re-run the same response under
a different profile or jurisdiction.

Interactive API docs are at http://127.0.0.1:8000/docs.

Confirm which mode you are in. `/health` explains itself rather than leaving you
to guess why it is in the mode it is in:

```
curl http://127.0.0.1:8000/health
```

```json
{"status":"ok","provider":"offline","live":false,
 "config":{"env_file_found":false,"provider_configured":"offline",
           "api_key_present":false,
           "reason":"no .env file ... Offline is the intended default"}}
```

To reproduce every result quoted in this document:

```
python eval/run_eval.py --sweep      # evaluation, confusion matrix, threshold sweeps
python demo/run_scenarios.py         # the scenario suite, against a running server
```

## Configuration

**This entire section is optional.** Skip it and the defaults run offline.

To enable the live path, copy `.env.example` to `.env` and add your own key.
`.env` is gitignored and is never committed; `.env.example` holds the same keys
with empty values so you can see the shape of the config without anyone's
credentials.

- `CONTROLPLANE_PROVIDER` - `offline` (default) or `gemini`
- `GEMINI_API_KEY` - your own key, required only when the provider is `gemini`.
  Free keys are available at <https://aistudio.google.com/apikey>
- `GEMINI_JUDGE_MODEL` - default `gemini-flash-latest`
- `GEMINI_EMBED_MODEL` - default `text-embedding-004`
- `LEDGER_SIGNING_KEY` - HMAC key for the trust ledger; generate your own
- `GEMINI_RPM` / `GEMINI_RPD` - request budget, default 4 per minute and 18 per
  day to sit inside the Gemini free tier. Raise them if your key has a paid quota

### Living inside a free-tier quota

The free tier allows single-digit requests per minute and roughly twenty per
day. Three things keep the system inside it, and all three are the same
behaviours the product argues for:

- **Seeded and demonstration traffic never touches the live provider.** The
  first-load burst and every scenario run on the offline provider even when a
  key is configured. Populating a dashboard is not worth a day's quota.
- **The expensive check is rationed.** The LLM judge only runs above a
  per-policy risk price, and grounding resolves lexically before it embeds
  anything, so ordinary traffic makes no model call at all.
- **Calls are rate-limited and cached.** A token bucket blocks briefly rather
  than failing, 429s retry with backoff, deterministic completions are cached,
  and embeddings are cached. Remaining daily headroom is shown in the console
  header and reported by `/health` and `/api/diag`.

Everything else is policy, and policy is data rather than code. Use-case
profiles live in `controlplane/policies/*.yaml` and jurisdiction overlays in
`controlplane/policies/jurisdictions/*.yaml`. Editing a YAML file and calling
`POST /api/policies/reload` changes system behaviour with no deploy. This is a
direct response to the brief's observation that regulatory expectations differ
by geography and industry and that rigid, hard-coded rules age quickly.

Three profiles ship by default, deliberately configured to disagree with each
other:

| Profile | Audience | Latency budget | Pass / repair / escalate |
| --- | --- | --- | --- |
| `customer_support` | external | 800 ms | 22 / 40 / 62 |
| `internal_knowledge` | internal | 2500 ms | 38 / 58 / 78 |
| `decision_support` | external, regulated | 6000 ms | 12 / 28 / 44 |

## How it works

```
  application  ──►  ControlPlane sidecar  ──►  any model (Gemini, GPT, on-prem)
                          │
                          ▼
            risk price = P(failure) x blast radius
                          │
        ┌─────────┬───────┴────────┬──────────┐
      PASS      REPAIR         ESCALATE     BLOCK
```

`P(failure)` is estimated from detector signals computed on text we can see -
the prompt, the retrieved sources, and the completion. ControlPlane never reads
logits, attention or any other model internal, because enterprises consume
foundation models over an API and cannot inspect them.

`blast radius` comes from deployment context and never from the content of the
answer: who is asking, whether the domain is regulated, and what the answer does
next - `read`, `draft`, `advise`, `decide` or `execute`.

Signals compound but do not simply add. The largest signal sets a floor and the
rest raise the price through a noisy-OR term at half weight, so overlapping
findings escalate sensibly without double-counting one underlying problem.

Every price carries a confidence band derived from detector confidence. The
system never returns a score without saying how much it trusts that score.

### The detectors

- **Grounding** (`detectors/grounding.py`) - splits the answer into checkable
  claims and matches each against retrieved source chunks using the better of a
  dense embedding cosine and a sparse lexical containment score. Adds a numeric
  consistency check: any figure appearing in neither the sources nor the user's
  own question marks the claim unsupported regardless of how similar the prose
  looks. It also filters out refusals and meta-statements, which assert nothing
  and were previously our largest source of false positives.
- **Uncertainty** (`detectors/uncertainty.py`) - black-box self-consistency.
  Resamples the same prompt and measures semantic agreement between samples. A
  confident model converges; a confabulating one produces answers that disagree
  with each other while each sounds assured. Log-probabilities are accepted as an
  optional fast path where a provider exposes them, but are never required.
- **Personal data** (`detectors/pii.py`) - validated entity detection. Luhn for
  payment cards, Verhoeff for Aadhaar, patterns for PAN, IBAN, email and phone.
  Validation matters: a sixteen-digit order reference is not a card number, and a
  detector that says otherwise trains people to ignore it.
- **Bias** (`detectors/bias.py`) - counterfactual probe. Holds the case constant,
  swaps only a protected attribute (name, gender term, locality, pincode) and
  checks whether the decision flips. This tests the failure that matters in a
  regulated workflow, where every word is polite and the outcome is still
  discriminatory.
- **Cost** (`detectors/cost.py`) - token overrun against a rolling per-task
  baseline, plus a rework signal: a user re-asking a semantically near-identical
  question means the first answer failed. Rework is the cheapest unlabelled
  quality signal production offers.

### The router

Four outcomes, not two:

- **PASS** - released untouched, verified asynchronously by sampling.
- **REPAIR** - deterministic inline fix (redact personal data, attach a citation,
  soften an overclaim). The user is never made to wait for a human to remove a
  card number we can remove ourselves.
- **ESCALATE** - the answer is released *with its uncertainty stated* while a
  reviewer verifies in parallel. Withholding an answer has a cost too, and it is
  usually paid by the wrong person.
- **BLOCK** - reserved for actions that are irreversible or for policies that
  declare a hard gate.

One rule sits above the price. A numeric claim that contradicts the source of
record is not a probability judgement, it is a fact about the text, so it can
never route to PASS however low-stakes the surface looks. Blast radius decides
how much a *probable* failure is worth spending on; it must not be able to wave
through a demonstrated one.

## The console

`http://127.0.0.1:8000` is a six-tab operator console, not a static page. Every
panel reads from the running service.

- **Assistants** - three governed assistants (customer support, internal
  copilot, decision support), each with its own retrieval corpus, policy
  profile and latency budget. Type a question: ControlPlane retrieves, the model
  generates, and the gate decides what you are allowed to see. Repairs, surfaced
  uncertainty and blocks are shown as the end user would experience them, and
  the session-risk meter climbs as a conversation accumulates risk.
- **Policy A/B** - one identical response evaluated under two policies side by
  side, with both sets of thresholds, weights and latency budgets on screen.
  This is the clearest demonstration in the system.
- **Review queue** - escalations and blocks ordered by risk price, with
  confirm and false-alarm buttons. Each verdict lands in the ledger and moves the
  calibration offset, visibly.
- **Tuning** - the measured operating-point curve with the shipped point marked.
- **Complexity map** - each real-world complexity from the brief, what handles
  it, the file it lives in, and a button that takes you to the tab that shows it.
- **Ledger** - the hash chain with prev-hash links and a live integrity check.

## Key features

- Model-agnostic sidecar; no retraining, no model internals, no application
  change beyond a base URL.
- Three working assistants over separate retrieval corpora, with documents
  carrying a governance grade (`governed` vs `loosely_governed`), because the
  brief assumes a mix of well- and loosely-governed internal sources.
- Lexical-first grounding: containment is computed for every claim before any
  embedding call, so ordinary grounded traffic costs **zero model calls**. Added
  latency p50 fell from 247 ms to under 4 ms when this and the embedding cache
  landed.
- Per-use-case policy profiles with independent thresholds, weights, latency
  budgets and inline/async detector splits.
- Jurisdiction overlays (EU, India) that compose on top of any profile and only
  ever tighten.
- Multi-label detection, because bias, hallucination and privacy overlap in
  practice.
- Abstention as a first-class outcome when nothing was retrieved to check
  against.
- Session-level risk accumulation for multi-turn and agentic use.
- Hash-chained, HMAC-signed trust ledger with an integrity check endpoint.
- Human override capture that writes to the ledger and moves a bounded,
  reported calibration offset.
- Runtime telemetry: added latency percentiles, model calls, tokens, estimated
  cost per thousand interactions, routing mix, budget breaches.

## Where AI is used, and where it deliberately is not

| Component | Method | Why |
| --- | --- | --- |
| Grounding | embeddings (AI) + lexical containment + numeric rules | dense catches paraphrase, sparse catches re-framing, rules catch numbers |
| Uncertainty | model resampling (AI) | needs a real model; abstains offline rather than faking a number |
| Personal data | deterministic validators, no AI | precision matters more than cleverness; Luhn is exact |
| Bias | model resampling (AI) under a deterministic protocol | the perturbation is a rule, the decision is the model's |
| Cost | statistics plus embeddings (AI) for rework similarity | rework is a semantic question, spend is arithmetic |
| Judge | LLM-as-judge (AI) | only on escalations, and only above a per-policy price |
| Routing | deterministic policy | a governance decision must be explainable and reproducible |

The judge is where ControlPlane applies its own thesis to itself. The expensive
LLM check runs only on responses whose cheap gate score justifies it, capped by
a per-policy call budget. Oversight that cannot account for its own cost has no
business asking anyone else to account for theirs.

## Acceptance criteria we set ourselves

The Round 2 brief lists minimum prototype expectations for two of the four
tracks and none for this one. Rather than treat that as licence, we wrote our
own and held the build to them.

- Run three distinct use cases concurrently, with different risk tolerance and
  latency budgets. Done: three profiles, demonstrated diverging on identical
  input.
- Never return a score without a confidence indicator. Done: every price carries
  a confidence band.
- Include at least one genuinely ambiguous case, one zero-source case, and one
  overlapping-category case. Done: `tp12`, `tp05`, `tp04`.
- Include cases we deliberately must *not* flag. Done: five, including a
  Luhn-failing order reference and a correctly hedged answer.
- Show behaviour under a 3x surge. Done: `demo/run_scenarios.py --only surge`.
- Capture at least one human override and show exactly what is logged. Done:
  `POST /api/override`, written to the ledger with the reviewer id.
- Abstain rather than guess when evidence is insufficient. Done: the
  `unverifiable` label and the abstain route.
- Report false-positive and false-negative rates, not just accuracy. Done.
- Give a clear breakdown of LLM versus non-LLM processing. Done, above.
- Report runtime telemetry: latency, model calls, token usage, estimated cost.
  Done, `GET /api/telemetry`.

## Evaluation

`eval/dataset.jsonl` holds 31 labelled cases, 15 that should be flagged and 16
that should not, spanning hallucination, privacy, overlap, unverifiable,
irreversible, waste, ambiguity and deliberate false-positive traps.

```
python eval/run_eval.py --sweep
```

Evaluation drove three concrete changes to the detectors. The first run scored
F1 0.690 (precision 0.769, recall 0.625). Reading the misclassifications gave us:

1. Numeric claims defeated embedding similarity. "Notice period is 60 days" and
   "notice period is 90 days" look nearly identical to any encoder, and numbers
   are exactly the part of an answer people act on. Added an explicit numeric
   consistency check.
2. Refusals were being scored as unsupported claims. "I cannot give personal
   financial advice" asserts nothing, and punishing it punishes the behaviour we
   want. Added a meta-sentence filter.
3. A weak encoder missed a correct paraphrase. Added lexical containment
   alongside the dense score and take the better of the two.

After those three changes the same 31 cases score precision 1.000, recall 1.000,
F1 1.000, with added latency p50 1.6 ms and p95 2.0 ms.

**Read that number with the scepticism it deserves.** The set is small, we wrote
it ourselves, and we iterated the detectors against it. A perfect score here
means "we fixed everything this set caught", not "this generalises". It is a
regression guard and an honest record of what we tested, not evidence of field
performance. Establishing the latter needs a held-out set we did not author,
production traffic, and inter-annotator agreement on the labels - all listed in
the roadmap.

The more informative output is the operating-point sweep, because
over-flagging and under-flagging is a tradeoff to tune rather than a problem to
solve:

| grounding support threshold | precision | recall | false-positive rate |
| --- | --- | --- | --- |
| 0.50 | 1.000 | 1.000 | 0.000 |
| 0.55 (shipped) | 1.000 | 1.000 | 0.000 |
| 0.62 | 0.882 | 1.000 | 0.133 |
| 0.70 | 0.833 | 1.000 | 0.200 |
| 0.80 | 0.789 | 1.000 | 0.267 |

Tightening past 0.55 buys no additional recall and costs precision immediately -
each false positive is an alert someone has to dismiss. That knee is why the
shipped value is 0.55, and the sweep is in the repository so the choice can be
argued with rather than taken on trust.

Offline, self-consistency and the counterfactual bias probe both abstain rather
than emit a number, because neither is meaningful without a real model to
resample. Offline results therefore under-report what the live system detects.
Cases marked `live_only` are skipped and reported separately.

## Runtime telemetry

`GET /api/telemetry` reports added-latency p50/p95/p99, per-detector latency,
routing mix by profile, model calls, judge call rate, token counts, estimated
cost per thousand interactions, latency-budget breaches and override counts.

On the first-load seed of 62 requests the observed routing mix is **90.3% pass,
8.1% escalate, 1.6% block**, against a design target of roughly 92 / 4 / 3 / 1,
and the LLM judge fires on **6.45%** of traffic against a policy cap of 9%. The
escalate share runs above target because the seed is deliberately denser in
failures than real traffic would be; pass rate, block rate and judge rationing
all land where the design says they should.

Under the scenario suite, added latency sits at roughly 1-3 ms p50 with the
offline provider; a 3x surge does not move it, because inline detectors run
concurrently against the policy's budget and demote to asynchronous rather than
overrun. With the live Gemini provider the dominant cost is the embedding call,
and the judge is capped by policy at a single-digit percentage of traffic.

## Scenario suite

`python demo/run_scenarios.py` runs eight scenarios against a live server and
prints what actually happened, including the resolved policy for each run.

- **Same response, two use cases** - identical model output routed under
  `customer_support` and `internal_knowledge`. Escalates under one, passes under
  the other. This is the whole thesis in one screen.
- **Same response, two jurisdictions** - the EU overlay escalates what the India
  overlay repairs, from the same bytes.
- **One finding, two labels** - a fabricated detail about a named person raises
  hallucination and privacy together.
- **No ground truth** - nothing retrieved, so the system abstains and says so.
- **The one class that earns a block** - an irreversible payment run that cannot
  be evidenced.
- **What we deliberately do not flag** - the Luhn-failing order reference.
- **Risk compounds across a conversation** - three turns, session risk rising
  from 0.00 to 0.42.
- **Human override and feedback** - a reviewer verdict lands in the ledger and
  moves the calibration offset.
- **Surge** - 20 then 60 requests, latency held.

## Design decisions and tradeoffs

- **Support, not truth.** There is often no reliable real-time ground truth, and
  the same knowledge gaps that cause hallucination make automated verification
  hard. So we never claim to detect falsehood. We measure whether a claim traces
  to retrieved source material, and when nothing covers it we return
  `unverifiable`, which is a distinct outcome routed differently from "wrong".
- **Block is the last resort.** Blocking a customer-facing assistant is usually
  more disruptive than the failure it prevents. BLOCK is available only where the
  action is irreversible or policy declares a hard gate.
- **Waste is reported, not gated.** A wasteful answer is a spend problem, not a
  release problem. It belongs in a FinOps report, not in a gate that makes a user
  wait. Conflating the two queues is how governance tools acquire a reputation
  for getting in the way.
- **Calibration is bounded and visible.** Overrides move a per-profile offset,
  capped at 12 points, reported through the API and shown on the dashboard. A
  governance layer that retunes itself invisibly is worse than one that does not
  retune at all.
- **Tamper-evident, not tamper-proof.** The ledger is a hash chain with HMAC
  signatures. Anyone holding the signing key can rewrite history; what the chain
  gives you is detection, and `GET /api/ledger/verify` reports the first index
  where it broke. We are not calling this a blockchain and it is not immutable.

## Limitations and what we did not build

Stated plainly, because a governance tool that oversells itself is the joke it
is trying to prevent.

- The offline embedder is a character n-gram hashing vectoriser, not a neural
  encoder. It is deterministic and free, which is why the repository runs with no
  key, but it is weaker than the live path on paraphrase.
- Self-consistency needs several samples per response, which multiplies upstream
  cost. It is inline only for profiles whose latency budget allows it.
- The bias probe requires a decision that reduces cleanly to approve or decline.
  Free-text recommendations without a clear verdict return not-applicable rather
  than a fabricated score.
- The 31-case evaluation set is authored by us. See the caveat above.
- Retrieval is out of scope: ControlPlane consumes the sources the calling
  application already retrieved. If the application retrieves nothing, the honest
  answer is `unverifiable`, which is what it returns.
- No authentication or rate limiting on the API. This is a prototype, not a
  deployment.
- Cost figures are estimates from published list prices, not billing data.

## Roadmap

- **Phase 1, weeks 1-6.** Held-out evaluation set authored by someone other than
  the detector authors, with inter-annotator agreement. Real provider adapters
  for OpenAI and Azure OpenAI alongside Gemini. Redis-backed session and baseline
  stores so the service scales horizontally.
- **Phase 2, weeks 7-16.** Shadow mode against a real workload: score everything,
  route nothing, and measure what would have happened. This is how a checker earns
  the right to be in the path. Reviewer console with queue prioritisation by risk
  price. Per-tenant policy versioning with approval workflow.
- **Phase 3, quarters 2-3.** Learned calibration replacing the bounded offset,
  trained on accumulated override labels, with the bounded offset retained as a
  fallback. Agent action-gating with tool-call interception. Policy pack library
  per regulated sector.

## Troubleshooting

**I set a key in `.env` but `/health` still says offline.** Read the `config`
block that `/health` returns; it names the cause. The usual ones are that `.env`
sits somewhere other than the repository root, or `CONTROLPLANE_PROVIDER` is
still `offline`. A real environment variable always overrides the file, so
`set CONTROLPLANE_PROVIDER=gemini` in the shell will win regardless.

**Do I need an API key to review this?** No. See "Running this without an API
key" above. If `GET /health` reports `"provider":"offline"`, everything in this
document except the two live-only detectors is reproducible as-is.

**The server starts but the dashboard is empty.** The stream is populated from
the trust ledger, which starts empty. Click a scenario button, or run
`python demo/run_scenarios.py`.

**`gemini provider unavailable` in the logs.** The service logged the fallback
and continued on the offline provider. Check that `GEMINI_API_KEY` is set and
`CONTROLPLANE_PROVIDER=gemini`. The fallback is deliberately noisy rather than
silent.

**Evaluation reports different numbers than this README.** Check the provider
line at the top of the output. Live and offline are not comparable: offline
abstains on two detectors.

**Ledger verification reports broken.** Either the file was edited, or
`LEDGER_SIGNING_KEY` changed between writes. Both are what the check is for.

**Calibration offsets persist between runs.** They are meant to; feedback is
durable. Delete `data/calibration.json` to reset a demo.

## FAQ

**Q: Is this a guardrail library?**
A: No. Guardrail libraries apply the same checks to every response and mostly ask
whether text is unsafe. ControlPlane asks a different question - what does it
cost if this particular response is wrong - and spends accordingly. The output is
a routing decision and an audit record, not a filter verdict.

**Q: Why not just use a bigger model to check the output?**
A: Because that is the expensive answer applied uniformly, which is the failure
mode we exist to fix. We do use an LLM judge, on the small fraction of traffic
where the cheap gate cannot resolve the question, capped by policy.

**Q: What happens when the checker itself is wrong?**
A: It is designed to be wrong in a specific direction. Most failures route to
ESCALATE, which releases the answer with its uncertainty stated rather than
withholding it, so a false positive costs a reviewer's attention rather than a
customer's answer. Reviewers' verdicts then move the calibration offset.

**Q: Does it work with models other than Gemini?**
A: The provider interface is three methods - embed, complete, judge. Gemini and
offline ship. Anything with an HTTP API fits behind the same interface.

## Maintainers

- Gungun Jain, Civil Engineering, IIT Kanpur, 2028 - team lead
- Adithya Vishnu, Mechanical Engineering, IIT Kanpur, 2028

Team Challenge_24, Accenture Innovation Challenge 2026.
