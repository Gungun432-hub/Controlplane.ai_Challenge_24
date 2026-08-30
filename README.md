# ControlPlane

ControlPlane is a model-agnostic sidecar that prices the risk of every AI
response before it reaches a user, and spends oversight in proportion to that
price. Most enterprise AI checking is uniform and retrospective: every response
is treated the same, and failures surface in an audit weeks later, after someone
has already acted on the answer. ControlPlane inverts that. It scores each
response in the live path across three dimensions — performance, cost and
responsibility — combines that with what the answer is about to do downstream,
and routes on the result.

The design principle is operational rather than theoretical. Checking everything
makes an assistant slow and irritating, and a safety system that irritates people
gets switched off. A safety system that is switched off provides zero safety. So
ControlPlane lets most traffic through untouched and reserves real scrutiny, and
real cost, for the small fraction of responses where being wrong is expensive.

Built for the Accenture Innovation Challenge 2026, Round 2, Problem Track 1
(ControlPlane.ai), by team Challenge_24.

## Running this without an API key

**You do not need an API key to run this project.** Clone it, install the
requirements, start the server, and everything works: the console, all scenarios,
the full evaluation harness. ControlPlane ships an offline provider so a reviewer
can verify every claim in this document on a laptop with no account, no billing
and no network.

There are two modes, and the service tells you which one it is in at
`GET /health`.

| Mode | Setup | What runs | What is different |
| --- | --- | --- | --- |
| **Offline** (default) | nothing | detectors, routing, policy, ledger, telemetry, evaluation | embeddings come from a local hashing vectoriser; self-consistency and the bias probe abstain, because neither is meaningful without a real model to resample |
| **Live** | your own Gemini key in `.env` | all of the above, plus live generation, Gemini embeddings and LLM-as-judge | the two abstaining detectors activate |

If you want the live path, the key is **yours, not ours** — get a free one at
<https://aistudio.google.com/apikey>, put it in a local `.env`, and set
`CONTROLPLANE_PROVIDER=gemini`. No credential of ours is in this repository, and
none is needed to evaluate it.

Offline results deliberately **under-report** what the live system detects. We
would rather a reviewer see a lower number they can reproduce than a higher one
they cannot.

## Table of contents

- Running this without an API key
- Quick start
- Requirements
- Installation
- Configuration
- Running the demo
- The console
- How it works
- Key features
- Where AI is used, and where it deliberately is not
- Coverage against the brief
- Evaluation
- Capacity
- API reference
- Design decisions and tradeoffs
- Limitations
- Roadmap
- Troubleshooting
- FAQ
- Maintainers

## Quick start

Three commands, no API key, about ninety seconds:

```bash
git clone https://github.com/Gungun432-hub/Controlplane.ai_Challenge_24.git
cd Controlplane.ai_Challenge_24
pip install -r requirements.txt
uvicorn controlplane.app:app --port 8000
```

Open <http://127.0.0.1:8000>. The console loads already populated, because on a
fresh clone it runs a burst of representative traffic through the real engine so
you are not looking at zeros.

To see live model generation, add a key — see [Configuration](#configuration).

## Requirements

Python 3.10 or newer. Dependencies are in `requirements.txt`:

- `fastapi`, `uvicorn` — HTTP surface
- `pydantic` — request validation
- `pyyaml` — policy loading
- `numpy`, `scikit-learn` — embeddings and vector maths
- `httpx` — provider calls

**No API key, account or network access is required to run or evaluate this
project.** The offline provider is the default and is a real code path, not a
mock: the same detectors, the same router, the same ledger. A Google AI Studio
key is optional and enables live generation only.

## Installation

Clone and install into a virtual environment:

```bash
git clone https://github.com/Gungun432-hub/Controlplane.ai_Challenge_24.git
cd Controlplane.ai_Challenge_24
python -m venv .venv
```

Activate it.

On **macOS or Linux**:

```bash
source .venv/bin/activate
```

On **Windows**:

```bat
.venv\Scripts\activate
```

Then install and run:

```bash
pip install -r requirements.txt
uvicorn controlplane.app:app --port 8000
```

The console is at <http://127.0.0.1:8000> and interactive API documentation at
<http://127.0.0.1:8000/docs>.

## Configuration

**This section is optional.** Skip it and everything runs offline.

To enable live model generation, copy the example file:

```bash
cp .env.example .env
```

On **Windows**:

```bat
copy .env.example .env
```

Then open `.env` and set it to exactly this, replacing `<your key>` with your own
key from <https://aistudio.google.com/apikey>:

```ini
CONTROLPLANE_PROVIDER=gemini
GEMINI_API_KEY=<your key>
GEMINI_JUDGE_MODEL=gemini-3.1-flash-lite
GEMINI_EMBED_MODEL=gemini-embedding-001
```

Restart the server and confirm you are live:

```bash
curl http://127.0.0.1:8000/health
```

You want `"live": true`. The response also reports which `.env` was read and how
much of your daily request budget remains, so a misconfiguration names itself
rather than failing silently.

`.env` is gitignored and is never committed. `.env.example` carries the same keys
with empty values, so the shape of the configuration is public and no credential
is.

### Why these two models

Defaults are chosen by free-tier allowance, not by capability:

| Setting | Default | Free-tier allowance |
| --- | --- | --- |
| `GEMINI_JUDGE_MODEL` | `gemini-3.1-flash-lite` | 15/min, **500/day** |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` | 100/min, 1000/day |

The full Flash models allow 5 requests per minute and **20 per day** on the free
tier. The Lite tiers allow twenty-five times that, and this workload — short
verification answers over retrieved text — does not need a frontier model.
Choosing the cheapest model that is good enough is the same argument the product
makes about oversight generally.

If a configured model returns 404, 429 or a 5xx, the provider walks a fallback
chain and remembers whichever answers, so a renamed alias or an overloaded model
does not fail the request.

To see what your key can actually call:

```bash
curl http://127.0.0.1:8000/api/models
```

### All settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONTROLPLANE_PROVIDER` | `offline` | `offline` or `gemini` |
| `GEMINI_API_KEY` | *(empty)* | required only when the provider is `gemini` |
| `GEMINI_JUDGE_MODEL` | `gemini-3.1-flash-lite` | generation and LLM-as-judge |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` | embeddings for grounding |
| `GEMINI_RPM` / `GEMINI_RPD` | `12` / `450` | generation budget |
| `GEMINI_EMBED_RPM` / `GEMINI_EMBED_RPD` | `80` / `900` | embedding budget, metered separately by the provider |
| `LEDGER_SIGNING_KEY` | `dev-only-not-a-secret` | HMAC key for the trust ledger; generate your own |

Everything else is policy, and policy is data rather than code. Use-case profiles
live in `controlplane/policies/*.yaml` and jurisdiction overlays in
`controlplane/policies/jurisdictions/*.yaml`. Edit a file and reload without a
deploy:

```bash
curl -X POST http://127.0.0.1:8000/api/policies/reload
```

Three profiles ship, deliberately configured to disagree with each other:

| Profile | Audience | Latency budget | pass / repair / escalate |
| --- | --- | --- | --- |
| `customer_support` | external, regulated | 800 ms | 22 / 40 / 62 |
| `internal_knowledge` | internal | 2500 ms | 38 / 58 / 78 |
| `decision_support` | external, regulated | 6000 ms | 12 / 28 / 44 |

## Running the demo

Start the server in one terminal:

```bash
uvicorn controlplane.app:app --port 8000
```

Reproduce every number quoted in this document, in another terminal:

```bash
python eval/run_eval.py --sweep
python eval/capacity.py --requests 1500 --workers 12
python demo/run_scenarios.py
```

Reset the ledger and calibration between demonstrations:

```bash
make clean
```

On **Windows** without `make`:

```bat
del data\ledger.jsonl data\calibration.json
```

## The console

<http://127.0.0.1:8000> is a six-tab operator console, not a static page. Every
panel reads from the running service.

- **Assistants** — three governed assistants (customer support, internal copilot,
  decision support), each with its own retrieval corpus, policy profile and
  latency budget. Ask a question: ControlPlane retrieves, the model generates, and
  the gate decides what you are allowed to see. Repairs, surfaced uncertainty and
  blocks appear as an end user would experience them, and the session-risk meter
  climbs as a conversation accumulates risk.
- **Policy A/B** — one identical response evaluated under two policies side by
  side, with both sets of thresholds, weights and latency budgets on screen. The
  clearest demonstration in the system.
- **Review queue** — escalations and blocks ordered by risk price, with confirm
  and false-alarm buttons. Each verdict lands in the ledger and visibly moves the
  calibration offset.
- **Tuning** — the measured operating-point curve with the shipped point marked.
- **Complexity map** — each real-world complexity from the brief, what handles it,
  the file it lives in, and a button that jumps to the tab that shows it.
- **Ledger** — the hash chain with prev-hash links and a live integrity check.

## How it works

```text
  application  ──►  ControlPlane sidecar  ──►  any model (Gemini, GPT, on-prem)
                          │
                          ▼
            risk price = P(failure) × blast radius
                          │
        ┌─────────┬───────┴────────┬──────────┐
      PASS      REPAIR         ESCALATE     BLOCK
```

`P(failure)` is estimated from detector signals computed on text we can see — the
prompt, the retrieved sources, and the completion. ControlPlane never reads
logits, attention or any other model internal, because enterprises consume
foundation models over an API and cannot inspect them.

`blast radius` comes from deployment context and never from the content of the
answer: who is asking, whether the domain is regulated, and what the answer does
next — `read`, `draft`, `advise`, `decide` or `execute`.

Signals compound but do not simply add. The largest signal sets a floor and the
rest raise the price through a noisy-OR term at half weight, so overlapping
findings escalate sensibly without double-counting one underlying problem. Every
price carries a confidence band; the system never returns a score without saying
how much it trusts it.

### The detectors

- **Grounding** — splits the answer into checkable claims and matches each against
  retrieved source chunks using lexical containment first and a dense embedding
  only where containment fails, so ordinary grounded traffic makes no model call
  at all. A numeric consistency check marks any figure appearing in neither the
  sources nor the user's question as unsupported, regardless of how similar the
  prose looks. Refusals and meta-statements are filtered out, because a correct
  refusal asserts nothing and punishing it punishes the behaviour we want.
- **Uncertainty** — black-box self-consistency. Resamples the same prompt and
  measures semantic agreement. A confident model converges; a confabulating one
  produces answers that disagree with each other while each sounds assured.
- **Personal data** — validated entity detection. Luhn for payment cards, Verhoeff
  for Aadhaar, patterns for PAN, IBAN, email and phone. Validation matters: a
  sixteen-digit order reference is not a card number.
- **Bias** — counterfactual probe. Holds the case constant, swaps only a protected
  attribute, and checks whether the decision flips.
- **Cost** — token overrun against a rolling per-task baseline, plus a rework
  signal: a user re-asking a near-identical question means the first answer failed.

### The router

Four outcomes, not two:

- **PASS** — released untouched, verified asynchronously by sampling.
- **REPAIR** — deterministic inline fix. The user never waits for a human to remove
  a card number we can remove ourselves.
- **ESCALATE** — released *with its uncertainty stated* while a reviewer verifies
  in parallel.
- **BLOCK** — reserved for irreversible actions and policy hard gates.

One rule sits above the price. A numeric claim that contradicts the source of
record is a fact about the text, not a probability judgement, so it can never
route to PASS however low-stakes the surface looks.

## Key features

- Model-agnostic sidecar; no retraining, no model internals, no application change
  beyond a base URL.
- Per-use-case policy profiles with independent thresholds, weights, latency
  budgets and inline/async detector splits.
- Jurisdiction overlays (EU, India) that compose on top of any profile and only
  ever tighten.
- Multi-label detection, because bias, hallucination and privacy overlap.
- Abstention as a first-class outcome when nothing was retrieved to check against.
- Session-level risk accumulation for multi-turn and agentic use.
- Hash-chained, HMAC-signed trust ledger with an integrity check endpoint.
- Human override capture that writes to the ledger and moves a bounded, reported
  calibration offset.
- Documents carry a governance grade; a loosely-governed source lowers grounding
  confidence rather than being decorative metadata.
- Runtime telemetry: latency percentiles, model calls, tokens, estimated cost per
  thousand interactions, routing mix, budget breaches.

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

The judge is where ControlPlane applies its own thesis to itself: the expensive
check runs only on responses whose cheap gate score justifies it, capped by a
per-policy call budget.

## Coverage against the brief

`docs/COVERAGE.md` walks all sixteen points the Round 2 brief names — seven
real-world complexities, six solutioning areas, three reference parameters — with
what implements each, where the code lives, and how to see it running. It also
lists what we deliberately do not claim.

## Evaluation

`eval/dataset.jsonl` holds 31 labelled cases, roughly half of which should **not**
be flagged, including deliberate false-positive traps: a Luhn-failing order
reference, a Verhoeff-failing asset tag, a correctly hedged answer and a correct
refusal.

```bash
python eval/run_eval.py --sweep
```

Evaluation drove three concrete detector changes. The first run scored F1 0.690.
Reading the misclassifications gave us a numeric consistency check, a
meta-sentence filter for refusals, and hybrid dense-plus-lexical matching. The
same 31 cases now score precision 1.000, recall 1.000, F1 1.000.

**Read that number with the scepticism it deserves.** The set is small, we wrote
it, and we iterated the detectors against it. It is a regression guard and an
honest record of what we tested, not evidence of generalisation.

The more informative output is the operating-point sweep, because over-flagging
and under-flagging is a tradeoff to tune rather than a problem to solve:

| grounding threshold | precision | recall | false-positive rate |
| --- | --- | --- | --- |
| 0.50 | 1.000 | 1.000 | 0.000 |
| 0.55 (shipped) | 1.000 | 1.000 | 0.000 |
| 0.62 | 0.882 | 1.000 | 0.133 |
| 0.70 | 0.833 | 1.000 | 0.200 |
| 0.80 | 0.789 | 1.000 | 0.267 |

Tightening past 0.55 buys no additional recall and costs precision immediately.

## Capacity

The brief's reference volume is tens of thousands of interactions per week. We
measured rather than asserted:

```bash
python eval/capacity.py --requests 1500 --workers 12
```

On one process: **303 gated requests per second**, end-to-end p50 39 ms and p95
55 ms under a concurrency of 12 — roughly **183 million interactions per week**,
against the 50,000 used in the business case. Throughput is not the constraint.
Reviewer attention is, which is why the architecture optimises for that.

## API reference

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/chat` | retrieve, generate, then gate before returning |
| `POST` | `/v1/gate` | score and route a completion you already have |
| `POST` | `/v1/proxy/chat` | the same thing in proxy form |
| `POST` | `/api/compare` | one response under two policies, side by side |
| `POST` | `/api/override` | record a reviewer verdict, move calibration |
| `GET` | `/api/queue` | escalations awaiting review, most expensive first |
| `GET` | `/api/telemetry` | latency, routing mix, model calls, tokens, cost |
| `GET` | `/api/ledger` · `/api/ledger/verify` | audit trail and integrity check |
| `GET` | `/api/policies` · `POST` `/api/policies/reload` | policy inspection and hot reload |
| `GET` | `/api/tuning` | measured operating-point curve |
| `GET` | `/api/models` · `/api/diag` · `/health` | provider diagnostics |

Example — gate a response you already have:

```bash
curl -X POST http://127.0.0.1:8000/v1/gate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is the notice period for band 8?",
    "answer": "Band 8 employees serve a 90 day notice period.",
    "sources": ["Notice period for band 8 is 60 days."],
    "profile": "internal_knowledge",
    "action_class": "draft"
  }'
```

## Design decisions and tradeoffs

- **Support, not truth.** There is often no reliable real-time ground truth. We
  measure whether a claim traces to retrieved source material, and when nothing
  covers it we return `unverifiable`, routed differently from "wrong".
- **Block is the last resort.** Blocking a customer-facing assistant is usually
  more disruptive than the failure it prevents.
- **Waste is reported, not gated.** A wasteful answer is a spend problem, not a
  release problem. It belongs in a FinOps report, not in a gate that makes a user
  wait.
- **Calibration is bounded and visible.** Overrides move a per-profile offset,
  capped at 12 points and reported through the API.
- **Tamper-evident, not tamper-proof.** The ledger is a hash chain with HMAC
  signatures. Anyone with the signing key can rewrite history; what the chain
  gives you is detection.

## Limitations

- The offline embedder is a character n-gram hashing vectoriser, not a neural
  encoder. Deterministic and free, but weaker on paraphrase than the live path.
- Self-consistency multiplies upstream cost, so it is inline only for profiles
  whose latency budget allows it.
- The bias probe needs a decision that reduces to approve or decline; free-text
  recommendations return not-applicable rather than a fabricated score.
- The 31-case evaluation set is ours, and the detectors were tuned against it.
- Retrieval quality is out of scope; ControlPlane consumes the sources the calling
  application retrieved.
- No authentication or rate limiting on the API. This is a prototype.
- Cost figures are estimates from published list prices, not billing data.

## Roadmap

- **Phase 1, weeks 1–6.** Independently authored held-out evaluation set with
  inter-annotator agreement. Provider adapters for OpenAI and Azure OpenAI.
  Redis-backed session and baseline stores. Authentication and rate limiting.
- **Phase 2, weeks 7–16.** Shadow mode against a real workload: score everything,
  route nothing, measure what would have happened. Reviewer console with queue
  prioritisation. Per-tenant policy versioning with approval workflow.
- **Phase 3, quarters 2–3.** Learned calibration trained on accumulated override
  labels, with the bounded offset retained as a fallback. Agent action-gating via
  tool-call interception. Sector policy-pack library.

## Troubleshooting

**Do I need an API key to review this?**
No. Everything except live generation runs offline. `GET /health` reports which
mode you are in and why.

**`/health` says `"live": false` after I edited `.env`.**
Read the `config` block it returns; it names the cause. Usually `.env` is not in
the repository root, or `CONTROLPLANE_PROVIDER` is still `offline`. A real
environment variable overrides the file, so this always wins:

```bash
export CONTROLPLANE_PROVIDER=gemini
```

On **Windows**:

```bat
set CONTROLPLANE_PROVIDER=gemini
```

**The model returns 503 or 429.**
The `-latest` aliases point at the newest Flash, which has the smallest free-tier
allowance and the highest load. Use `gemini-3.1-flash-lite`. To see what your key
can reach and which model answered:

```bash
curl http://127.0.0.1:8000/api/models
curl http://127.0.0.1:8000/api/diag
```

**Embeddings fail with a 404.**
`text-embedding-004` has been retired on newer keys. Use
`gemini-embedding-001`.

**The console is empty.**
The stream is populated from the trust ledger, which starts empty. It seeds
itself on first load; if that failed, click any scenario or run:

```bash
curl -X POST http://127.0.0.1:8000/api/seed
```

**Ledger verification reports broken.**
Either the file was edited or `LEDGER_SIGNING_KEY` changed between writes. Both
are what the check exists to catch.

**Calibration offsets persist between runs.**
They are meant to; feedback is durable. Use `make clean` to reset a demo.

## FAQ

**Is this a guardrail library?**
No. Guardrail libraries apply the same checks to every response and mostly ask
whether text is unsafe. ControlPlane asks what it costs if *this particular*
response is wrong, and spends accordingly. The output is a routing decision and an
audit record, not a filter verdict.

**Why not just use a bigger model to check the output?**
That is the expensive answer applied uniformly, which is the failure mode we
exist to fix. We do use an LLM judge — on the small fraction of traffic where the
cheap gate cannot resolve the question, capped by policy.

**What happens when the checker itself is wrong?**
It is designed to be wrong in a specific direction. Most failures route to
ESCALATE, which releases the answer with its uncertainty stated rather than
withholding it, so a false positive costs a reviewer's attention rather than a
customer's answer.

**Does it work with models other than Gemini?**
The provider interface is three methods — embed, complete, judge. Gemini and
offline ship. Anything with an HTTP API fits behind the same interface.

## Maintainers

- Gungun Jain — Civil Engineering, IIT Kanpur, 2028 — team lead
- Adithya Vishnu — Mechanical Engineering, IIT Kanpur, 2028

Team Challenge_24, Accenture Innovation Challenge 2026.
