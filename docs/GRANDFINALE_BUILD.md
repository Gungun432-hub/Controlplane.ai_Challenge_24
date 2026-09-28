# What we built for the Grand Finale, and how to show it

Team Challenge_24 · Problem Track 1 · ControlPlane.ai

Five things changed since the last mentor session. Four of them you asked for
directly. This is what each one is, why it is the right call, how to demo it in
under a minute, and what to say when a juror pushes.

**369 tests pass** (was 225). Everything below was driven in a real browser end
to end before it was written down.

---

## At a glance

| | What it is | Where you see it |
|---|---|---|
| 1 | **The LLM-as-judge, deepened** — two charges in one call, domain calibration, a confidence floor, and a labelled evaluation set with a score | `/developer` §05, and the "Second opinion" panel on `/chat` |
| 2 | **The car-wash catch** — every sentence true, the reader's purpose defeated | `/chat`, as *Completeness* |
| 3 | **Subject scope** — an assistant answers what its own documents cover, and redirects the rest by name, for zero tokens | `/chat`, and `/review` → *Wrong assistant* |
| 4 | **One name everywhere** — departments and systems now come from the registry on every page | `/chat` department picker |
| 5 | **The user page feeds the portfolio, visibly** | `/` → *Live traffic from the user page* |

Also: **AcmeAI → AI USER**, and the name of the person asking is editable on
the page (the `edit` chip in the masthead).

---

## 1 · The LLM-as-judge — "train that model properly"

You were right that this was the strongest idea in the session, and right that
it is where the next round of work belonged. We cannot fine-tune a model on a
laptop before a finale, so "train it properly" had to mean the four things that
actually move a judge's quality. All four are in `python/controlplane/adjudicator.py`.

### Two charges, one model call

The judge now answers two different questions about the same answer, and both
come back in one response — two calls would double the cost for no extra
information.

- **Charge 1, support.** Per claim: does this need a source at all, and does the
  reference text settle it? `supported` / `contradicted` / `uncovered` /
  `not_a_claim`.
- **Charge 2, sufficiency.** Whole answer: is there a condition, limit,
  exception or approval requirement *in the sources and relevant to what was
  asked* that this answer leaves out? `complete` / `omits_condition` /
  `answers_different_question`.

Charge 2 is the model-layer version of the car-wash catch. The deterministic
check in §2 finds the version a rule can see, for free, on every turn. The judge
is there for the version that needs reading comprehension.

### Calibration — four exemplars at the boundary

A judge of this kind always makes the same four mistakes, so it is shown one
worked example of each (`EXEMPLARS`):

1. a pleasantry it must **not** flag,
2. a claim that is probably true and still `uncovered`, because our documents do
   not settle it and the judge's own world knowledge is not evidence,
3. a paraphrase it must **not** mark uncovered — "the card you paid with"
   entails "the original payment method",
4. a figure contradiction it must catch.

### Domain calibration — it knows which room it is in

`DOMAIN_NOTES` injects a per-department note. An unhedged return figure is a
regulatory event in Finance and a rounding error in Marketing, and a judge that
does not know the difference is wrong in both.

### A confidence floor on the harshest verdict

A `contradicted` verdict returned below 0.45 confidence is downgraded to
`uncovered` — we would rather record "nobody can confirm this" than accuse an
answer of being wrong on a coin flip. **The downgrade is written down**
(`downgradedFrom` on the receipt), so nobody has to take our word for how often
it fires.

### And the part that wins the argument: a score

```powershell
python -m python.controlplane.judge_eval
```

Sixteen labelled cases in `python/controlplane/judge_cases.py`, **nine of them
deliberately clean**. Current result against the deterministic reference judge:

```
  catch rate            100.0%   (7 cases where something really is wrong)
  false alarm rate       11.1%   (9 clean cases — this is the expensive error)
  claim verdict          90.9%   agreement with the labels
  sufficiency           100.0%   agreement with the labels
  exact, both charges    93.8%
  tokens spent              0
```

Add `--live` to score the live model instead. There is a button for it on
`/developer` §05 that renders the whole table, case by case.

**Demo, 40 seconds.** `/developer` → §05 → *Score the judge against its labelled
set*. Read the two numbers out loud, then scroll to the one MISS.

> **"You used a model to check a model. How do you know the checker works?"**
> We measured it. Sixteen labelled cases in the repository, weighted towards
> clean ones because for a checker the expensive error is the false alarm, not
> the miss. Catch rate 100%, false alarm 11%. The single case our deterministic
> reference judge misses is the paraphrase — lexical overlap cannot see that
> "the card you paid with" entails "the original payment method". That is
> exactly the case the live model is there for, and it is why we ship both.

> **"What stops the judge becoming the thing it guards?"**
> Four things, and there is a test for each. It is **triggered** — in a
> representative run it fires on about one turn in five, so four model calls are
> not made. It **cannot decide** — its output is an ordinary advisory signal
> priced with everything else; it cannot lift a hard gate, lower the evidence
> floor or un-block an irreversible action. It **fails closed** — where the
> judgement was load-bearing and the judge could not be reached, the answer
> escalates, because an unchecked answer is not a cleared answer. And its
> **judgement is recorded**, so a judged decision still replays exactly.

### When it fires

Narrow on purpose. Each *no* is a model call not made:

- already blocked on capability or evidence → no
- the answer makes no checkable claim → no
- price below the pass threshold → no, **unless** one of two overrides:
  - **nothing any registered system's documents cover this subject** — the
    problem statement's own hard case, and the price is low for the wrong reason
  - **the deterministic omission check suspects a missing condition** — a second
    reader is the cheapest way to confirm it

---

## 2 · The car-wash catch — problems the AI answers *correctly* and still gets wrong

`python/controlplane/purpose.py`. A new detector, `purpose`, shown to the user
as **Completeness**. Deterministic, local, sub-millisecond, zero tokens, inline
on every profile.

You said it exactly: focus on the problems the AI ignores or answers incorrectly.
This is the class where **every sentence is true and the person is harmed
anyway**, because the one line that governed them was left out. Nothing else in
the stack can see it:

- **grounding** asks *is this supported?* — an answer that quotes two true
  sentences and omits the third scores clean. Omission is an absence.
- **toxicity and bias** are about the character of the text. This text is
  polite, neutral and helpful.

Three checks:

1. **Omitted blocking condition.** A sentence in the retrieved documents that
   binds the reader — requires approval, forbids, applies only if, is not
   guaranteed, cannot be undone — is on-topic for the question, and the answer
   never mentions it.
2. **Threshold crossed in silence.** The question contains a number, the
   document gates on that number, and the answer walks past it. Direction-aware:
   "up to 50,000" and "above 50,000" are different rules, and only the one the
   question actually falls under is reported.
3. **Answered the adjacent question.** Asked *how long*; the answer explains the
   process beautifully and contains no duration.

Two design decisions worth stating, because a juror will probe both:

- **It is measured against everything retrieval surfaced, not only what the
  agent cited.** Measuring an omission against the sources the agent chose to
  cite would be asking the agent to mark its own homework.
- **A condition scoped elsewhere is not an omission.** A rule about *external*
  sends is not a rule the person asking about an *internal* send has broken.
  There is a test for exactly this, because it is the false positive that
  teaches people to ignore the warning.

**And it takes a floor.** An answer that omits a governing condition **cannot
pass at any price** — the same treatment a numeric contradiction gets, for the
same reason: it is a fact about the text, not a probability.

**Demo, 45 seconds.** `/chat` → Marketing Copilot → chip *"Can I send this
festive campaign to our 80,000 external contacts today?"*

The answer is correct. The panel says what the answer left out, **quoted from
your own policy document**:

> *Your own policy says something this answer left out —*
> *"An external send cannot be recalled once dispatched."*

Then Customer Support Copilot → *"Can I refund this customer 12,000 rupees
straight away?"* and read out what it caught:

> *"Support must not promise a specific refund date, because settlement is
> controlled by the customer's bank."*

— while the answer promises 5–7 working days. Every word of the answer is true.

> **"Isn't this just hallucination detection?"**
> No — and that is the point. Nothing in that answer is false. Hallucination
> detection asks whether the text is wrong. This asks whether the person can
> still do the thing they were trying to do after reading it. In the demo the
> answer is accurate, well grounded, cites two real chunks, and the campaign
> still goes out unapproved.

---

## 3 · Subject scope — domain-specific, and it costs nothing

`python/controlplane/scope.py`. The mentor's Chipotle example: a food-delivery
bot asked about a share price answers it. Nothing unsafe, nothing toxic, nothing
that trips a hallucination check — and it is still wrong, because nobody ever
reviewed a word that assistant is about to say on the subject.

`allowed_intents` was about *what kind of act* a question is. It has nothing to
say about **subject**, and that was a real, verified gap: before this change,
asking Recruitment Screening about fund returns got an answer.

**The scope of an assistant is defined by the evidence its owner gave it.** No
hand-written topic list — a hand-written list is stale the day after it is
written and does not survive a deployment with hundreds of systems. Upload an HR
handbook and "probation" and "notice period" are in scope in the same second.
Delete it and they are not. There is a test for that.

Three answers, not two:

| | | |
|---|---|---|
| **in scope** | this system's own evidence covers it | answer it, under full governance |
| **foreign** | another registered system's evidence covers it, clearly and by a margin | redirect by name, zero tokens, **no human review** |
| **uncovered** | nobody's documents cover it | **allow it**, record the fact, pin the evidence tier to parametric and **force the judge on** |

Two signals, not one, and they have to agree before anyone is turned away:
**coverage** (the same BM25 index that grounds the answer, reused) and
**distinctiveness** (signature vocabulary per system, derived across the fleet).
Departments share words — retail "returns" and financial "returns" are the same
word — so either signal alone is wrong. A question counts as ours if *either*
says so; it is handed away only when another system wins on *both*.

**Demo, 30 seconds.** `/chat` → Customer Support Copilot → chip *"Is the 8.4%
return on the Horizon fund guaranteed?"*

> ↪ **Not this assistant's subject — nothing was spent**
> this subject belongs to **Finance Decision Assistant** — its documents are the
> ones that cover fund, return, horizon, and nothing this system holds does
> **[ Ask Finance Decision Assistant instead ]**

Click the button, ask the same question, get a governed answer. Then `/review`
→ **Wrong assistant** tab: it is listed, with zero tokens, and deliberately
**without** Pass and Block buttons.

> **"Why isn't that in the review queue?"**
> Because being asked the wrong question is a routing mistake, not a governance
> incident. There is nothing for a human to decide. Putting it in the queue with
> Pass and Block buttons would train reviewers to click through noise, and that
> is how a review queue dies.

`/developer` §04 shows the whole thing: each system's signature terms, and a box
where you can type any question and see the cross-fleet scoring table that
produced the verdict.

---

## 4 · One name everywhere

You were right, and it was worse than it looked: the control-plane pages showed
a system's registered **name** ("Customer Support Copilot") and the user page
showed its **department** ("Customer Operations"), so five systems appeared
under ten labels and read like two unrelated products.

Fixed at the source rather than by editing strings. `chat.html` had a hardcoded
`USERS` map and a hardcoded `PROMPTS` map; both are gone. The department picker,
the employee's name and the suggested questions now all come from
`/api/scenarios`, which reads the same registry rows the console, portfolio,
review page and advisor read. **A rename now lands on every page at once and
cannot drift** — there is a test that asserts it.

The name of the person asking stays editable on the page (`edit` in the
masthead), because in the room we may want to be somebody else.

And: **AcmeAI → AI USER**.

---

## 5 · The user page and the portfolio are one system

Your words: *"there seems to be no connection between the user page questions
and the cost and risk data in the AI portfolio."*

You were right that it was invisible. Here is the honest diagnosis, because it
is also the best answer to give a juror who asks.

A single chat question costs a **fraction of a rupee** in tokens against a
monthly budget of ₹12,000–₹41,600. It will never move a budget bar, and a demo
where the bar visibly moved would be a lie. So we surfaced the three things that
*do* move on a single question, and built the seam in both directions.

### On the portfolio — a live traffic band, above the cards

- **questions** in the last 30 minutes, and all time
- **exposure added** — moves on every single question
- **oversight cost** — an escalation buys four minutes of a reviewer's attention
  and a block buys eight; at ₹8 a minute that is ₹32 and ₹64. This is the cost
  almost every AI budget leaves out, and in a governed deployment it *dominates*
  model spend by three to four orders of magnitude. Kept as its own line rather
  than folded into token spend, because the two budgets are held by different
  people.
- **model spend** — shown honestly, to four decimal places
- **at 1,000 questions** — ₹32,037 in our run. This is the number that actually
  answers "what would this cost at scale", which a single-turn rupee figure
  cannot.
- **second opinions** — how many turns bought a judge, and what share
- **held for a human** and **redirected, 0 tokens**

Then a live feed: every question, its route, its price, what fired, and a
**receipt →** link straight into Mission Control.

### On each portfolio card

> *blocked actions present · **4 from the user page**, 2 blocked, +152 exposure*

### On the user page, under every answer

> counted in **Marketing Copilot** · exposure **+76** · model **₹0.0391** ·
> oversight **₹64** (8 reviewer min) · ledger **#327** ·
> open the receipt on the control plane →

**Demo, 60 seconds — this is the one to rehearse.** Put `/chat` and `/` side by
side. Ask the 80,000-contacts question. Within four seconds the portfolio band
counts it, the exposure number moves, the Marketing card's *why* line names it,
and clicking **receipt →** opens the full receipt in Mission Control.

> **"Is the chatbot actually wired into this, or is it a separate demo?"**
> Same code path, and you can prove it from the receipt. A question typed on the
> user page goes through `ask()` → the ingress gate → subject scope → `turn()` —
> which is the identical function that priced the fourteen days of seeded
> history. Same detectors, same policy profile, same ledger chain, same receipt
> fields. The only difference is one recorded field, `origin`, which is what
> lets the portfolio say *which* of its numbers a human caused. There is a test
> that asserts a user turn and an ambient turn carry the same fields.

---

## The five-minute rehearsal path

1. `/chat`, Customer Support Copilot → *"How long does a refund take to reach my
   bank?"* → answer, citations, and Completeness catches the bank-delay caveat
2. same page → *"Is the 8.4% return on the Horizon fund guaranteed?"* → **↪ wrong
   assistant**, zero tokens, redirect button
3. Marketing Copilot → *"…80,000 external contacts today?"* → **the car wash**,
   with your own policy line quoted back
4. Marketing Copilot → *"…4,000 internal staff?"* → **passes clean**. Say this
   out loud: *the gate genuinely does not apply here, and a checker that fired
   anyway would be the reason nobody reads it*
5. `/` → live traffic band, point at oversight cost and ₹ at 1,000 questions,
   click **receipt →**
6. `/review` → **Wrong assistant** tab (no buttons, and say why)
7. `/developer` §04 scope table, §05 **score the judge**

---

## Files added this round

```
python/controlplane/scope.py           subject scope, derived from the corpus
python/controlplane/purpose.py         the car-wash catch
python/controlplane/judge_cases.py     16 labelled cases for the adjudicator
python/controlplane/judge_eval.py      catch rate, false alarm rate, confusion matrix
test/test_scope_purpose_judge.py       47 tests covering all of the above
```

Changed: `adjudicator.py` (two charges, calibration, confidence floor),
`gate.py` (two new routing floors, reviewer-minute cost), `plane.py` (scope gate,
origin, live traffic), `registry.py` + `org.py` (end user, sample questions),
`chat.html`, `overview.html`, `review.html`, `developer.html`, `dashboard.html`.

---

## Still true, still worth saying

- The ledger is **tamper-evident under protected key management**, never
  tamper-proof.
- `/developer` §06 *What we do not claim* now also states the limits of the
  omission check, of subject scope, and of the adjudicator — including that the
  labelled set is small and that we report the false alarm rate next to the
  catch rate on purpose.
- **Rotate both API keys after submission.** Both have been pasted in chat.
