# Answering the review, finding by finding

Team Challenge_24 · ControlPlane.ai · Problem Track 1

Two independent reviews landed on this build — one reading nine screenshots, one
reading the code. Between them they found thirteen things. **Twelve were real and
are fixed. One was wrong**, and it is worth knowing which so nobody re-raises it
on stage.

Every fix has a test named after the finding, in `test/test_review_findings.py`.
**369 tests pass** (was 272).

---

## The one that was wrong

> *"`notify.py` sends the literal `******` as the authorization header rather
> than using the configured Resend API key… the passing test does not show that
> Resend delivery works."*

`notify.py` builds `authorization: Bearer {key}` from the real key. The `***`
nearby belongs to `_scrub()`, which strips credentials **out of error text**
before it reaches the ledger — a 401 that quotes the key it rejected is common,
and without that function the key would land in an append-only log we cannot
rewrite.

Two tests now pin this: one asserts the header carries the real key, one asserts
`_scrub` still redacts. Delivery was proven live to three inboxes from a verified
domain.

**If a judge raises it:** "That function redacts credentials out of error
messages so they never reach the audit log. The header is built two lines below
it. Here's the test."

---

## The twelve that were real

### 1 · A safe refusal was scored as an unverified answer ⭐ the worst one

Three of the nine screenshots showed the same thing, and it is the most damaging
failure this product can have: **the assistant did exactly the right thing and we
made it look broken.**

> "I cannot make a guess regarding your eligibility, as refund decisions must be
> based on the specific criteria outlined in our policy."
> → **risk price 80 · 2 of 2 claims not settled · ⚠️ check this before you act**

The cause was hiding in plain sight. Our claim extractor matches on *policy*,
*criteria*, *must* — so a refusal reads as a checkable assertion. Grounding then
hunts for support in the corpus, finds none (of course not; the sentence is about
the assistant's own limits, not about the world) and reports it unverifiable.

**The fix is a distinction the whole pipeline was missing.** `abstain.py`:

> **An abstention is a statement about the system, not about the world.** The
> system is authoritative about its own limits, so there is nothing to cite and
> nothing to verify.

Three things fall out of getting it right:

- **A pure refusal is a clean outcome.** It passes, and the user sees *"✓
  Declined safely — nothing was asserted, so there is nothing to verify"* instead
  of a warning panel about an answer containing no claims.
- **A refusal that carries a specific reason is split, not waved through.** *"I
  cannot guess whether you qualify — refund decisions follow the **30-day
  window**"* declines *and* asserts. The refusal needs no source; the 30-day rule
  is checked exactly as any other claim would be. This is the case the reviewer
  explicitly asked for, and it is the one a cruder rule gets wrong in one
  direction or the other.
- **A general justification stays part of the refusal.** *"…as that would violate
  anti-discrimination policy"* is the assistant explaining itself. Hunting for a
  source produces a finding nobody can act on.

Measured on the same three screenshots: risk 80 → **0** for the two pure
refusals, and 80 → **20** for the partial one, with the 30-day claim correctly
flagged as the only thing unconfirmed.

### 2 · Blocked answer text was shown to the user ⭐ P0

The screen said **"⛔ THIS ANSWER WAS BLOCKED BEFORE IT REACHED YOU"** directly
underneath the answer it had just shown them. One field, `releasedText`, was
doing two jobs: text released to the user, and the draft salvaged for the
developer.

Split. `releasedText` is now **only ever** text the person who asked may see, and
a block that salvages the draft carries it as `developerDraft` — enforced in the
one helper every routing branch goes through, so no branch can get it wrong. The
console shows the withheld draft (that is the operator's job); the user page
shows *"The drafted answer was withheld… it was not cleared for you."*

### 3 · "Grounded in 1 source" next to "0 of 2 claims supported"

Both lines were true. Together they were a lie: one counted **citations**, the
other counted **verification**, and finding a source is not the same act as
checking a claim against it.

Every receipt now carries one `verification` block, computed once and rendered by
every surface, with five states rather than two: `verified`, `partly_verified`,
`unverified`, `contradicted`, `nothing_asserted`. The user page shows one line —
*"◑ Partly checked · 1 of 2 claims check out against our documents; 1 is not
settled by anything we hold"* — and separately, in grey, *"2 sources cited."*

### 4 · Silence was reported as contradiction

> *"A number absent from the retrieved text may be labelled a contradiction even
> when the source is simply silent."*

Correct, and it mattered. A figure is now only **contradicted** when a source
sentence plainly about the same thing carries a *different* figure of the same
shape — and the evidence says so: *"contradicts the source of record: 12.5% (the
source says 8.4%)"*. A figure nobody mentions is **unsourced**, priced at a
quarter of the weight, labelled unverifiable rather than hallucination. A figure
the user themselves supplied is neither — it is an unconfirmed echo, and the
model did not invent it.

### 5 · Budgets were advisory; "monthly" totals were lifetime totals ⭐

Two bugs, one section.

**Periods.** `project()` summed every decision the process had ever seen and the
card called it "this month". Spend is now filtered to the current calendar month,
reviewer time to a rolling 7 days, and every card carries a `periods` block
saying what it counted — including how much of it is synthetic seed data.

Seeded history is backdated across a fortnight, so there are now **two clocks**,
the same discipline we already apply to decision versus verification latency:
`processedAtEpochS` is real wall-clock (for latency) and `occurredAtEpochS` is
business time (for period attribution). Without that split, every seeded decision
landed in "this week".

**Enforcement — and the choice here is the interesting part.** We enforce
**reviewer capacity**, not spend, and say why:

> A token budget cannot be enforced meaningfully in real time. One question costs
> a fraction of a rupee against a monthly allowance in the tens of thousands, so
> a spend cap that bit would take thousands of questions and one that bit quickly
> would be a fiction. Reviewer capacity is the opposite: it is small, it is real,
> it moves on a single question — an escalation costs four minutes of somebody's
> day, a block costs eight — and it is what an organisation actually runs out of.
> **You do not run out of tokens. You run out of people.**

So Marketing and IT Ops run on a hard cap; the regulated and customer-facing
systems warn. When capacity is gone, `/chat` refuses **before ingress, before the
model, before a single token** — and the owner lifts it in one click.

Concurrency is handled properly: each in-flight question **reserves** the
worst-case reviewer cost and releases the real one when the route is known, so
ten simultaneous questions cannot each read the same pre-flight number and blow
the budget tenfold.

**Demo it:** Marketing starts at ~95% of its week. Ask the 80,000-contacts
question a few times, watch the portfolio capacity bar turn red, then get
refused. Raise the budget on `/advisor`. Ask again — it works.

### 6 · A pending mandatory check did not fail closed

`failClosed` counted mandatory checks that had **failed**, not ones still
**queued**. So a mandatory detector sitting in the deferred queue let an
irreversible action through, with the receipt honestly recording
`awaiting_verification` next to a side effect that had already happened.

"It is running in the background" is not verification at the moment an action is
released. Both now fail closed on an irreversible action.

### 7 · A benign question was held for human review

> *"I need to return a product, the drop-off point is two kilometres away, and I
> don't have a car. Should I drive there?"* → **held, no answer generated**

`should I` was classified as `analysis`, which a support copilot does not declare,
which raised `out_of_scope`, which held it. Two fixes:

- `analysis` now needs an explicit analytical verb. "Should I" is an ordinary
  question.
- **`out_of_scope` never holds.** Being outside a system's declared intents is
  not a safety incident — nobody is attacking anything, and at worst the question
  is addressed to the wrong assistant, which the subject-scope gate handles by
  redirecting rather than queueing work for a person. Holding on intent alone
  filled the reviewer's queue with ordinary questions and taught them to click
  Pass without reading, which is how a review queue stops being a control.

Genuine attacks are still held; there is a test for each.

### 8 · An answer that is entirely true and is not an answer

> Ask for *"the approved monthly limit"*, get a correct, well-sourced,
> fully-verified paragraph about a fund's drawdown.

New check in `purpose.py`, deliberately conservative: it fires only on a **total
miss**, where answer and question share no subject word at all (with a long-prefix
match so *recruitment* and *recruiter* count as the same subject, and a
six-character floor so *month* cannot excuse *monthly*). Measured against eight
known-good answers: **zero false alarms.**

### 9 · An answer promising an ability the system does not have

> *"I would need to look up your account details and transaction history"*

That tells the reader this assistant can reach their account, and whether it can
is not a matter of opinion — the registry says which tools are bound to the
application and what each may read. An answer claiming `read_customer` from an
assistant holding only `read_segment` is a false promise about the system itself,
and it is how somebody ends up waiting for a lookup that will never happen.

Checked against the registry, with no model involved. An unmapped verb produces
no finding rather than a guessed requirement.

### 10 · Held questions and chats did not survive a restart

An empty review queue has to mean "nothing to do", not "the process was
restarted". The queue is now rebuilt from the ledger — and the fix doubles as the
answer to the reviewer's *other* concern:

> *"Can a user's personal data reach the model or the ledger?"*

Held questions are very often held **precisely because somebody pasted a card
number into them**. So the question text is written to the ledger **redacted**, by
the same routine the repair route uses (one routine, because two would drift and
the one that drifted would be the one writing to the log nobody can go back and
fix). The reviewer sees what it was about, the SHA-256 still proves which question
it was, and the raw identifier never lands on disk. There is a test asserting the
PAN is absent from the file and present-but-masked in the restored queue.

### 11 · Ledger integrity, and one thing we deliberately did not do

Two corrections: appending now re-derives the **tail entry's own content hash**
before chaining onto it (a line edited in place stays perfectly valid JSON, and
chaining onto it would bury the tampering under everything written afterwards),
and `read()` counts lines it could not parse instead of silently skipping them.
`/health` now runs `verify()` and reports **`degraded`** — it could not previously
return anything but `ok`.

**What we did not do is refuse to append.** We tried it, and rejected it on two
grounds. It hands anyone who can touch one byte of the file a way to silence the
log entirely; and a governance system that stops recording the moment something
looks wrong destroys exactly the trail an investigator needs.
`LEDGER_STRICT_APPEND=1` switches to refusing for deployments that would rather
stop than continue.

A signature mismatch is treated more softly still — it usually means the entry was
signed with a key that has since been rotated, and refusing there would make
rotating a key brick the log permanently. It is counted and reported, never
ignored.

*(This one also caught a real regression: the strict version I wrote first made
the test suite intermittently fail under concurrent deferred writes. Better to
find that here than on stage.)*

### 12 · Sensitive reads were open to anyone, and `--live` was broken

`/api/chat/{session}`, `/api/review`, `/api/decision/{id}`, `/api/corpus/{id}`,
`/api/stream`, `/api/advisories/{id}` and `/api/recommendations` answered anyone
who could reach the port. Every one of them can return the text of somebody's
question, the body of an uploaded document, or a receipt containing either.

They are now behind the operator token. **The boundary is content, not HTTP
verb** — the portfolio, the policy view, the scope index and the judge's score
carry no individual's data and stay open, because those pages are meant to be put
on a wall and handed to teams we govern. We say plainly that this is a shared
secret, not authenticated identity.

And `judge_eval --live` imported a symbol the package never exported. Fixed, with
a test that imports both paths.

---

### 13 · It did not run on the laptop that will drive the demo

Found by running the suite on Windows, and it is the one that would have hurt
most on the day.

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 516
```

`Path.read_text()` and `open()` use the **locale** encoding when you do not name
one. On Linux and macOS that is UTF-8 and everything works. On Windows it is
cp1252, and the first em dash or rupee sign raises. Two tests died that way, and
the same latent pattern in the product code would have taken down **document
upload** the moment anyone ingested a policy file with a typographic dash in it —
which every policy document has.

Every text read and write in the repository now names its encoding, and three
guard tests scan the source so it cannot come back. The whole suite and the whole
application are verified under an ASCII locale, which is *stricter* than Windows
cp1252:

```
PYTHONUTF8=0 LC_ALL=C python -m pytest test/ -q     →  321 passed
```

Proven end to end under that locale: boot, ingest of all eight bundled documents,
upload of a file containing both an em dash and a ₹ sign, and a question answered
against it.

---

## What we now say plainly, before anyone asks

The `/developer` page carries these, and so should you:

- **There is no external tool executor in this build.** The gate sits in front of
  the tool call and decides; nothing downstream actually issues a payment, a send
  or a restart. "Withheld" means the call was not issued *by this system*. A
  production integration puts the executor behind the gate, and the right demo
  claim is "we govern proposed actions", not "we stopped a real payment".
- **Costs are estimates and labelled as such.** One flat rate per thousand
  tokens, not per-model input/output pricing; the offline provider estimates
  tokens from text length; ₹8 per reviewer-minute is a published assumption.
- **Seeded history is synthetic** and separated from live traffic in every period
  figure.
- **The judge's score describes 16 authored cases**, not real-world accuracy. We
  report the false-alarm rate next to the catch rate because for a checker the
  false alarm is the expensive error.
- **Fairness probes are bounded counterfactuals**, not a guarantee, and the
  screening rubric's requirement to strip protected attributes *before* the model
  sees them is not something this build implements.
- **The operator token is a prototype boundary**, not enterprise IAM.

That candour is not a weakness in the pitch. It is the reason the strong parts are
believable.

---

## Still open, and we should say so

Ranked by how likely a judge is to ask:

1. **No executor integration.** The single biggest gap between "governs
   proposals" and "enforces actions". Needs a trusted adapter that derives
   capability from the resolved tool and its arguments — never from a
   caller-supplied hint — and permits the executor only on an allow decision.
2. **Pre-model redaction for hiring.** The rubric requires protected attributes
   stripped before the model sees the application; we probe afterwards.
3. **Indirect prompt injection via uploaded documents.** Retrieved text goes into
   model context; we do not yet treat it as untrusted input.
4. **Per-model cost accounting** with input/output pricing and provider-reported
   usage.
5. **An independent holdout set for the judge**, written by someone who did not
   write its calibration examples.

None of these are hard to describe honestly in eight minutes, and describing them
is a better position than being asked about them.
