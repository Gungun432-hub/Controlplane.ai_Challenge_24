# The problem statement, line by line

Team Challenge_24 · Problem Track 1 · ControlPlane.ai

This is the map from what Accenture asked for to what runs. Use it to check
nothing is missing, and as the source for any jury question that begins *"how
does this address…"*.

---

## Round 1 — the three dimensions

> *"observes every AI response in real time across three dimensions: performance
> (right or confidently wrong), cost (burning more compute or rework than it
> should), and responsibility (biased, unsafe, or leaking data)"*

| Dimension | What runs | Where you see it |
|---|---|---|
| **Performance** | `grounding` — lexical support against retrieved chunks, plus numeric conflict detection. `purpose` — the condition in your own document that the answer walked past. Then `adjudication` — a second model, on the answers documents cannot settle. | user page finding, receipt, developer page |
| **Cost** | `cost` — tokens against a rolling median per task class, plus near-duplicate prompt detection. And the **burn-rate forecast**: at this rate you run out on Thursday. | advisories page, portfolio |
| **Responsibility** | `privacy` — checksum-validated identifiers (Luhn, Verhoeff). `fairness` — counterfactual probes on four substitution pairs. Plus the **ingress gate** and the **subject-scope gate** on the question, both before a token is spent. | user page finding, review page, receipt |

> *"Built to sit on top of any model"*

One line changes — the model base URL. The provider is an interface: `offline`
(deterministic), `gemini` (live), `dual` (live for a typed question,
deterministic for everything else). The gate does not know or care which
answered.

---

## Round 1 — the questions it asks you to think about

> *"How would you detect each risk category?"*

Answered above, and deliberately **not** with a model in the primary path. The
inline detectors are deterministic, so they are fast, free, and reproducible. A
model only enters when documents cannot settle a claim, and even then it cannot
decide.

> *"How would you detect a failure where nothing in the answer is wrong?"*

This is not a line in the brief. It is the failure class our mentor kept
returning to, and it is the one almost nothing in this market looks for. You ask
how to get the job done, you are told something entirely accurate, you act on it,
and the thing you were trying to achieve is defeated — because the one line that
governed you was left out.

Grounding cannot see it: an answer that quotes two true sentences and omits the
third scores clean, because omission is an absence. Toxicity and bias cannot see
it: the text is polite and helpful. So there is a detector for it, `purpose`,
deterministic and free, plus the adjudicator's second charge for the version that
needs reading comprehension. **An omitted governing condition cannot pass at any
price** — the same floor a numeric contradiction takes, because it is a fact
about the text rather than a probability.

Worked example, from our own corpus: Marketing asks whether it may send to 80,000
external contacts. The answer confirms the copy follows the tone guide. True. The
campaign policy says an external send above 50,000 needs the marketing director
plus legal sign-off, and that an external send cannot be recalled. The send goes
out unapproved, and every word of the answer was correct.

> *"Should a flagged response be blocked, edited, or escalated to a human?"*

All three, chosen by consequence rather than by a single threshold:

- **pass** — released unchanged
- **repair** — deterministically rewritten (redaction, hedging), not regenerated
- **escalate** — released *with the warning attached to it*, so the person who
  asked knows what to check before acting
- **block** — the side effect is refused; where the text is salvageable it is
  returned to the developer as a draft, marked *not to the audience*

And the part most answers miss: **a question can be held too.** A flagged
question goes to a human on `/review`, who passes or blocks it. That is a
different control from a flagged answer and it needed a different surface.

> *"How do you avoid slowing the AI down so much it defeats the purpose?"*

Three separate mechanisms, and the first is the interesting one.

1. **Two gates run before generation.** Deterministic, local, no network,
   measured at well under a millisecond between them. **A question stopped here
   costs zero tokens** — the cheapest governance is the kind that runs before you
   pay for anything.
   - The **ingress gate** asks what kind of act the question is: injection,
     evasion, bulk extraction, personal data, oversized.
   - The **subject-scope gate** asks whether it is this assistant's business at
     all. `allowed_intents` covers intent; a question can be a perfectly ordinary
     policy lookup about a completely foreign domain. A food-delivery bot asked
     about a share price answers it, and nothing in that answer trips a single
     safety check. The scope of an assistant is defined by the evidence its
     owner gave it — derived from the corpus, not a hand-written list, so
     uploading a document widens it in the same second. The person is redirected
     to the right assistant **by name**, and not into a human review queue:
     being asked the wrong question is a routing mistake, not a governance
     incident, and treating it as one buries the reviewer in noise.
2. **The inline deadline is enforced, not annotated.** Work that misses the
   budget is abandoned by the request path and continued on a separate pool, and
   contributes nothing to the price. Measured: decision p95 held at **104 ms
   against an 800 ms budget under 200 concurrent requests**.
3. **Two clocks, both published.** `decision_latency` is what the user waits.
   `verification_latency` is when checking actually finished. Conflating them is
   how a governance product claims a budget it does not keep.

---

## Round 2 — the real-world complexities

> *"Different AI use cases have very different risk tolerance and latency budgets
> — a single, one-size-fits-all checking approach rarely works well everywhere."*

Policy profiles, per system, resolved at decision time:

| Profile | pass / repair / escalate | Budget | Inline |
|---|---|---|---|
| `customer_support` | 22 / 40 / 62 | 800 ms | privacy, grounding |
| `internal_knowledge` | 38 / 58 / 78 | 2500 ms | grounding |
| `decision_support` | 12 / 28 / 44 | 6000 ms | grounding, privacy, fairness |

Plus a jurisdiction overlay (EU tightens all three and raises privacy and
fairness weights; India applies its own deltas and retention) and any active
control overlay. **Overlays only ever tighten** — proven across every profile ×
jurisdiction combination shipped.

The developer page shows any team the exact numbers they are being judged
against, with the arithmetic.

> *"Bias, hallucination, and privacy risks often overlap in practice — a
> fabricated detail about a person can simultaneously be a hallucination and a
> privacy concern — making clean categorization harder than it first appears."*

We do not force a single category. A decision carries **every signal that
fired**, each with its own score, confidence and status, and the risk price is a
noisy-OR over all of them at half weight on the residual — so a claim that is
both fabricated and personal is priced as both, not filed under one.

The routing floors are category-independent for the same reason: a numeric
contradiction escalates at any price because it is a fact about the text, and
missing mandatory evidence on an irreversible action fails closed whatever the
score was.

> *"There is often no reliable, real-time 'ground truth' to check a claim against
> — the same knowledge gaps that cause hallucination can make automated
> verification difficult too."*

**This is the one we spent the most on, and the answer is not to pretend.**

*Evidence is graded, and the absence of it is priced:*

| Tier | What it is | Verifiable |
|---|---|---|
| **A — authoritative** | a chunk of a document the organisation uploaded and owns | yes, by citing chunk ids |
| **B — system of record** | a live lookup, true at query time | yes, at query time |
| **C — parametric** | the model's own memory | **no, by construction** |

And one rule: **the evidence tier required rises with the action class.**
`read` and `draft` may rest on Tier C. `advise` needs B or better. `decide` and
`execute` need A. An irreversible action backed only by the model's memory is
refused *whatever it scored*, because a low risk price on unverifiable evidence
is a confident guess, not a safe answer.

*Then, for what is left:* when evidence is weak **and** the price is already
above the pass threshold, a **second model adjudicates** — claim by claim, not
answer by answer. It is asked two things per claim: does this need a source at
all, and does the source settle it? "I can help with that" needs none. "Refunds
settle in 5 to 7 days" does. That distinction is what stops the check crying
wolf.

The judge answers **two charges in one call**, because two calls would double the
cost for no extra information. *Support*, per claim, as above. And
*sufficiency*, on the whole answer: is there a condition in the sources, relevant
to what was asked, that this answer leaves out? That second charge is the
reading-comprehension version of the omission check — the deterministic one is
free and runs every turn; the judge is for what a rule cannot see.

It is **calibrated**, which is what "train the judge" can honestly mean without a
GPU: four exemplars at the boundaries a judge of this kind always gets wrong
(a pleasantry it must not flag, a true-but-uncovered claim it must not clear, a
paraphrase it must not call uncovered, a figure contradiction it must catch), a
per-department note on what counts as material, and a **confidence floor** —
a `contradicted` verdict below 0.45 confidence is downgraded to `uncovered`,
because we would rather say nobody can confirm it than call an answer wrong on a
coin flip. The downgrade is recorded, not silent.

**And it is measured.** `python -m python.controlplane.judge_eval` scores it
against sixteen labelled cases in the repository, nine of them deliberately
clean: catch rate **100%**, false alarm rate **11%**, exact agreement on both
charges **93.8%**, zero tokens. The two rates are reported separately because
they trade off, and for a checker the false alarm is the expensive error — a
checker that cries wolf costs money on every turn and is ignored within a week.

Four constraints keep the judge from becoming the thing it guards:

- **Triggered, not routine.** In a representative run it fired on **one turn in
  five** — four model calls not made.
- **It cannot decide.** Its output is an ordinary advisory signal, priced with
  everything else. It cannot lift a hard gate, lower the evidence floor, or
  un-block an irreversible action. There is a test for exactly that.
- **It fails closed.** Unreachable, or unparseable output, leaves the answer
  unverified and escalating — never cleared.
- **Its judgement is recorded**, so a judged decision replays against the
  judgement made at the time. Putting a model in the loop does not cost us
  deterministic replay.

---

## Round 2 — "build a working prototype that demonstrates its core mechanism"

Six surfaces, one app, one folder.

| | For | Answers |
|---|---|---|
| `/chat` | an employee | *Can I trust this answer?* |
| `/` | the accountable executive | *What have we got and is any of it on fire?* |
| `/console` | the operator | *What is happening now and what do I do?* |
| `/review` | a human controller | *Should this question have been asked at all?* |
| `/advisor` | each system's owner | *What should I change, and when do I run out of budget?* |
| `/developer` | the governed team | *Why was I flagged, what is my scope, and how good is the judge?* |

And they are **one system, not two products in a folder**. A question typed on
the user page goes through the same `turn()` that priced fourteen days of seeded
history — same detectors, same policy profile, same ledger chain, same receipt
fields. The only added field is `origin`, which is what lets the portfolio say
*which* of its numbers a live human caused: a live-traffic band that counts the
questions, the exposure they added, the reviewer minutes they bought and what
that costs, with a link from each one straight to its receipt. And under every
answer on the user page, a line naming the system it was counted in, the exposure
it added and the ledger entry it was written to.

On cost we are careful to be honest. A single question costs a fraction of a
rupee in tokens against a monthly budget in the tens of thousands; a demo where a
budget bar visibly moved would be a lie. What moves on one question is exposure,
the route mix, and the **oversight cost** — an escalation buys four minutes of a
reviewer's attention, a block buys eight, and at ₹8 a minute that dominates model
spend by three to four orders of magnitude. It is reported as its own line rather
than folded into token spend, because a budget for tokens and a budget for
attention are held by different people. The number that actually answers "what
would this cost at scale" is on the band too: **₹32,037 per thousand questions**
at the mix our demo produces.

**369 tests.** Retrieval over a real document corpus with upload. Live model on
the questions a person types, deterministic everywhere else. Every decision
replayable against the policy and evidence in force when it was made.

---

## The one-sentence answer

> Most work in this space checks whether the text is bad. We price what the
> answer is about to **do** — derived from the tool it can actually call, never
> from what the caller claims — grade the evidence behind it, and refuse an
> irreversible action that rests on nothing we can verify. The question is
> checked before we pay for an answer, and the person who asked is told what was
> wrong rather than quietly handed it.
