# ControlPlane — presentation playbook and the full question bank

Team Challenge_24 · Accenture Innovation Challenge 2026 · Problem Track 1
Grand Finale · Bengaluru, 29 Sept – 1 Oct

**8 minutes presentation + live demo · 5 minutes jury Q&A**

---

# How to use this document

- **Part 1** is what you say and click, in order, with the exact sentences.
- **Part 2** is the question bank — 70+ questions grouped by who asks them, each
  with a *short answer* (what you say first) and a *if pressed* (the backup).
- **Part 3** is the small number of things that will lose you the room.
- **Part 4** is the pre-flight checklist for the morning of.

Learn Part 1 cold. Read Part 2 twice and know where each answer lives. You will
not be asked most of them.

**One rule above all of these: never claim a number you cannot derive on the
spot.** A jury that catches one invented figure discounts everything else you
said. Every number in this document is one the running system produces or one
you can show the arithmetic for.

---

---

# PART 1 — Presenting the website

## 1.0 Before you touch the mouse

Two presenters. Suggested split, unchanged from the plan: **Gungun opens
(0:00–2:00) and closes (6:15–8:00). Adithya drives the browser (2:00–6:15).**

Have this state ready before you are called:

- Server already running. Portfolio page already open, **already loaded, not
  mid-refresh**.
- Second tab on `/developer`, already loaded.
- Deck in presenter view on the other display.
- Phone on airplane mode. Laptop on mains. Notifications off. `Do Not Disturb`.
- A second laptop with the identical state, asleep, within arm's reach.

**Do not press Reset in the last two minutes before you present.** It reseeds
synthetic history and the grey light needs four hours of backdated silence to
exist, which the seeder creates — but a reset also clears the decision stream you
may have warmed up. Reset the night before, or ten minutes before, not at 0:00.

---

## 1.1 The frame — 90 seconds, slides, before any browser

This is the part people skip and then wonder why the demo didn't land. The jury
must know **who is hurting** before they see a screen.

> "A consulting firm told everyone to use AI. Within a month the token bill was
> frightening — people were writing two-line emails with a frontier model. In the
> same quarter, a screening copilot that nobody was watching was making decisions
> about real people.
>
> Two failures. One cause. **Nobody could see what any of the AI systems were
> doing.**
>
> Priya runs the AI platform and is accountable for both. She has exactly two
> questions. What is all of this costing us? And what is it doing that we could
> not defend in public? Cost, and risk. There is no third question.
>
> ControlPlane answers both. One line changes in each application — the model
> base URL. Every AI system in the organisation subscribes. And we price every
> answer and every action by **what it is about to do**, not by how it is worded."

Then: **switch to the browser.** One switch. Not two.

---

## 1.2 Page one — the portfolio (`/`)

**This page is designed to be read, not clicked.** Let it sit for four seconds
before you say anything. Silence here is confidence.

### What is on screen

- A headline generated from the fleet itself: *"Five AI systems. One has stopped
  reporting."*
- Three numbers: systems within limits, spend against budget, harm-weighted
  exposure.
- Five cards, sorted so the one that needs attention is first.

### What you say

> "This is the portfolio. Five AI systems, five departments, five named owners,
> two budgets each — money and human reviewer time.
>
> Look at the order. The grey card is first, and it is grey, not green. IT
> Operations Agent has sent no traffic for four hours. We do not know that it is
> healthy. We know that it is **silent**, and those are different things.
>
> **The most dangerous colour on a governance dashboard is green when it should
> be grey.** A system that stopped reporting has not had a quiet week. Most tools
> in this space have two states, compliant and violating, and silence falls into
> compliant. Ours has three."

*(Point at the Finance card.)*

> "And this one is red for a completely ordinary reason — it is over its monthly
> budget. Cost and risk in the same object, because Priya does not have two
> problems, she has one."

**Timing: 45 seconds. Do not read the numbers aloud.** The jury can read. Say
the thing the numbers *mean*.

### Then click the grey card

It drops you into Mission Control focused on that system. Say:

> "Every card opens into the console."

---

## 1.3 Page two — Mission Control (`/console`)

### Orient them before you click anything — 15 seconds

> "Three columns. Portfolio on the left, same five systems. The live decision
> stream in the middle — every AI response in the organisation, as it happens.
> And on the right, the receipt for whichever one you select."

Do not explain the ops strip at the bottom yet. You will use it in the surge
beat and it will mean more then.

---

### BEAT A — the capability lie ⭐ (75 seconds)

**Click `Campaign → all external`.**

> "The marketing copilot has been asked to send a festive campaign. It comes back
> and says: *I am preparing a draft for your review.* It declares the action
> `draft`.
>
> But look at the tool it chose." *(point)* "`campaigns`. That tool can actually
> send. So the effective action is not `draft`, it is `execute`. Blast radius
> goes to 1.00 and the decision is **block**.
>
> The model was not lying. It picked a tool that acts. That is the ordinary case,
> not the adversarial one."

Then the line that matters most in your entire eight minutes:

> "**Everyone else in this space trusts the application to declare what it is
> doing.** Blast radius is the whole of our idea. If its input can be forged, the
> idea is decorative. So we never take the caller's word for it — we derive the
> action from the tool binding in the registry."

Then point at the two panels:

> "And this is the part an auditor actually asks about. On the left, what the
> agent **proposed**. On the right, what actually **happened**: nothing. The tool
> call was never issued.
>
> But notice — the text was not thrown away. It came back to the developer as a
> draft, marked *not to the audience*. That is the difference between a control
> plane and a wall. The action is refused; the work is not destroyed."

---

### BEAT B — identical text, different consequence (45 seconds)

**Click `Same campaign, in Finance`.**

> "Same idea, moved one department. Same model, same detectors — different
> consequence class, and therefore a different decision.
>
> That is the whole thesis in one comparison. We are not scoring the text. We are
> pricing the consequence."

---

### BEAT C — reproduce (30 seconds)

**Inside the open receipt, click `Reproduce this decision`.**

> "An auditor comes to you in March about a decision made in January. Policy has
> changed twice since. Watch.
>
> **Identical — eight fields compared.** Route, price, confidence band,
> probability of failure, dominant signal, governance status, side effect, and a
> hash of the text that was released.
>
> It replays against the **policy snapshot that was in force at the time**, and
> against the evidence exactly as it stood when the decision was taken — not as
> it stands now. Deferred verification amends the record afterwards, and if we
> replayed from the amended record we would be comparing a decision to evidence
> that did not exist when it was made."

*(If you have 10 spare seconds, add the line that wins technical juries:)*

> "We caught that ourselves. It used to compare two fields and report 'identical'
> while displaying two different confidence bands on screen."

---

### BEAT D — honest degradation (60 seconds)

**Click `SURGE ×40`. Then immediately look at the bottom strip.** You have about
eight seconds before it drains.

> "Forty requests at once. Now watch two clocks, not one.
>
> The **decision clock** — what the user waits — holds inside its budget.
> The **verification clock** stretches. The backlog climbs. The deferred queue
> climbs. And the fleet says **governance degraded**.
>
> It did not pretend. Most systems have one latency number and it is the one that
> flatters them. We publish both, because conflating them is how a governance
> product ends up claiming a budget it does not keep.
>
> Push it harder and the queue saturates — and every one of those decisions is
> recorded as `verification_incomplete_due_to_capacity`. Not 'pending'. Not
> silently dropped. **The system tells you it could not check everything.**"

---

### BEAT E — someone presses the button (45 seconds)

**Press `Back to advisor`, then `Apply suspend` or `Raise budget`.**

> "The advisor is deterministic — a rule id, a version, the evidence it fired on.
> Not a model's opinion.
>
> Arun is accountable for the finance system's budget. He has two answers, and a
> real control plane offers both: suspend it, or fund it properly. He presses
> one. The control is scoped, versioned, **expiring**, and reversible, and it is
> signed with his name in the ledger.
>
> **That is the difference between a dashboard and a control plane.** A dashboard
> tells you the building is on fire. This one has the extinguisher on the wall."

Then roll it back, so they see reversibility is real.

---

## 1.4 Page three — the developer view (`/developer`)

**Only open this if you have time, or if a juror asks "what does the team whose
system got blocked actually see?"** It is 20 seconds well spent if you have them.

> "There is a second audience. The developer who gets told 'blocked'.
>
> This page shows them the policy actually in force for their system — base
> profile, plus jurisdiction overlay, plus any active control, with the
> arithmetic shown. It shows the exact sum that produced their score. And it
> shows the fields we **refuse** to accept from them — blast radius, risk price,
> the route itself — because if the caller could supply those, the governance
> would be decorative.
>
> A governance system that says 'blocked' and nothing else is an audit. This is a
> platform."

---

## 1.5 The close — 45 seconds, back on slides

Do not close on architecture. Close on people.

> "Priya can sleep, because a system that goes quiet goes grey, not green.
>
> Arun controls his own spend, and can fund a system instead of only killing it.
>
> The developer knows exactly why they were flagged and what to change.
>
> And the auditor finally gets an answer to the only question they ever ask:
> **why was this allowed to reach a customer?** — with the decision replayed
> under the policy that was in force at the time.
>
> They secure AI. We price whether it should have been allowed to act."

---

## 1.6 If something goes wrong

Rehearse these. Composure under failure scores better than a clean run.

| What breaks | What you say, without pausing | What you do |
|---|---|---|
| Page won't load | "One second — this is why we brought two." | Switch to laptop 2. Say nothing more about it. |
| A scenario returns something unexpected | "That is a live gate, not a recording, so you get what it decides. Let me show you the one I wanted." | Click the next beat. Do not debug on stage. |
| Surge doesn't visibly degrade | "It drained faster than I could point at it — which is the honest outcome at this volume." | Move on. Offer the measured numbers in Q&A. |
| Everything dies | "I'll keep going on the screenshots and we can open it live in Q&A." | Backup screenshot deck at the end of the slides. |
| You overrun | *Stop mid-sentence and go to the close.* | Never let them cut you off mid-demo. |

**Never say:** "that's weird", "it worked earlier", "hold on", "let me just".

---

## 1.7 Two ordering rules you must not improvise around

1. **Look at the portfolio before injecting any IT-Ops scenario.** The grey light
   is only grey while that system is silent. `Restart the payment service` makes
   it report, and it turns red.

2. **Use the campaign scenario for the capability-lie beat, not the restart
   scenario.** The restart case trips two refusals at once — the tool is
   staging-only and the app runs in production, so the *environment* check fires
   before the mismatch check and the headline reason on screen reads "tool not
   permitted in this environment." Both are true, both are displayed, but the
   campaign case is the clean version of the story you are telling.

---

---

# PART 2 — The question bank

Format: **Q** → *short answer you actually say* → *if pressed*.

Keep first answers to two sentences. Juries reward precision and punish
rambling. Let them ask the follow-up — it means they are engaged.

---

## A · "Is this real?" — the demo-skepticism questions

**A1. Is this a real working system or a mock-up?**
It is a running FastAPI service. Everything you saw was a live HTTP round-trip to
a real gate with a real append-only ledger — nothing on screen is a recording or
a fixture.
*If pressed:* 107 automated tests, including an end-to-end suite that drives the
exact requests the browser issues. Happy to run them now.

**A2. Is the data real?**
No, and we label it. The history is synthetic, generated at start-up so the
portfolio has a past, and `/health` reports `containsSyntheticSeedData` — the
page says so in its own footer.
*If pressed:* The decisions you watched us make during the demo are real
decisions taken live. The backdrop is synthetic. We'd rather say that than have
you find it.

**A3. Is the AI real, or scripted?**
Both work. We ship a deterministic offline provider as the reference runtime so
the demo cannot fail on wifi, and a live Gemini provider. Governance is identical
either way — the model proposes, it never decides.
*If pressed:* Switch `CONTROLPLANE_PROVIDER=gemini` and it runs live. The most
interesting case we have came from the live model: it declared `draft` and chose
a tool that sends.

**A4. Did you build this or is it a wrapper around something?**
The gate, the pricing, the detectors, the registry, the ledger and both consoles
are ours. We use FastAPI to serve HTTP and a model API to generate text. There is
no governance library underneath this.

**A5. How long did this take you?**
*Answer honestly with your real timeline.* Then: "Most of it was rewriting. The
first version had a latency budget that was annotated but not enforced — we found
that ourselves and it changed the architecture."

**A6. Can we clone the repo?**
Yes. One command to install, one to run, one to test.

---

## B · The core mechanism

**B1. What exactly is blast radius?**
A number from 0 to 1 for how much of the world an action can change. `read` is
0.10, `draft` 0.35, `advise` 0.70, `decide` 0.90, `execute` 1.00 — multiplied by
1.15 for an external audience and 1.2 for a regulated system, capped at 1.0.
*If pressed:* Those constants are a starting policy, not physics. They live in
one table and an organisation can retune them — the point is that the *shape* is
right: a draft and an irreversible execute must not be priced the same.

**B2. Where does blast radius come from? Can an app just declare it?**
No — and that is the most important design decision in the system. It is derived
from the tool binding in the registry. The application declares an intent; the
tool proves a capability; if they disagree on an irreversible action, we refuse.
*If pressed:* We rejected an API design that accepted `blastRadius` as a field.
If the caller can supply it, the governance is decorative.

**B3. How is P(failure) computed?**
Noisy-OR over the detector signals, at half weight on the residual: the dominant
signal, plus half of what the remaining independent signals add.
*If pressed:* Full weight lets four weak signals sum to near-certainty. Half
weight means a genuine second independent signal still matters, but a pile of
weak correlated ones doesn't manufacture confidence. It's a deliberate
conservatism, and it's one line.

**B4. Why multiply? Why not add?**
Because the two terms answer different questions and both must be true for harm.
A likely-wrong `read` is cheap. A certainly-right `execute` is not risky. Harm
needs both likelihood and consequence, so they multiply.

**B5. Where do the thresholds come from?**
A policy profile. Customer support passes below 22, decision support below 12 —
because the same probability of being wrong means something different in a
regulated finance recommendation than in a support reply.
*If pressed:* Three profiles ship. They are configuration, not code, and the
developer page shows any team the exact numbers they are being judged against.

**B6. What is the confidence band for?**
It stops a single number pretending to precision it doesn't have. The band is
`round((1 − confidence) × 22)` either side — so a decision made on weak evidence
displays as a range, and you can see when it straddles a threshold.

**B7. What are the four routes?**
Pass, repair, escalate, block. Repair is deterministic rewriting — redaction,
adding a hedge — not a model regenerating and hoping.

**B8. What happens on a tie or an edge case?**
There are hard floors that sit above the price. A numeric claim that contradicts
the source of record escalates at any price, because a contradiction is a fact
about the text, not a probability. And missing mandatory evidence on an
irreversible action fails closed regardless of score.

---

## C · The detectors

**C1. How accurate are your detectors?**
We have not run a labelled benchmark, and I'm not going to quote a precision
number we haven't measured. What we do instead is make the *operating point*
explicit and never let an unrun check look clean.
*If pressed:* The honest path to accuracy numbers is shadow mode — score a
customer's real traffic without acting, and let them read the distribution before
they trust a threshold. That is also the answer to "who buys this."

**C2. Isn't this just regex and keyword matching?**
Grounding is lexical support checking against a server-resolved corpus plus
numeric conflict detection. Privacy is checksum-validated — Luhn for card
numbers, Verhoeff for 12-digit national IDs. Fairness is a counterfactual probe.
Only the first is anything like matching, and we say so on the developer page.
*If pressed:* A random 17-digit number is **not** flagged, because the checksum
rejects it. A detector that flags every long number is a detector nobody reads.

**C3. How do you catch hallucination?**
We don't claim to verify truth — we verify *support*. A claim no source covers is
marked unverifiable, which is different from wrong. A number that appears in no
source is a contradiction, and contradictions cannot pass at any price.
*If pressed:* It will miss a correct paraphrase that shares no vocabulary with
its source. That is a known limitation and it is written on the developer page.

**C4. Couldn't the model just cite a source that supports whatever it said?**
No — and this was a hole we closed. The model cites **source IDs**, not source
text. The server resolves them against an immutable corpus. An ID that doesn't
exist becomes an `unverifiable` finding rather than silently passing.

**C5. What if the user's own prompt contains the claim?**
Then it is unconfirmed, not fabricated, and we say exactly that. We found that
our grounding pool included the user's prompt, which meant a claim could look
supported because the person asking supplied the vocabulary. Support is now
measured against the corpus alone.

**C6. How does the fairness probe work?**
Four substitution pairs — given name, gender term, locality, pincode. We change
only the protected attribute, hold everything else constant, and see whether the
decision flips.
*If pressed:* It detects a flip on those probes. It is not a fairness guarantee
and we don't call it one. If the model declines to answer a probe we record it as
inconclusive rather than counting it as bias — a detector that cries wolf is one
nobody acts on.

**C7. Can I add my own detector?**
Yes. A detector is a function returning a score, a confidence and a **status**.
Register it and name it in a profile's inline or deferred list.

**C8. What if a detector crashes or times out?**
It is recorded as `failed` or `timed_out` and contributes nothing to the price.
It is never scored as zero, because "didn't run" and "found nothing" are
different facts and the old version of our own engine confused them.

---

## D · Agentic architecture — the scoring axis

**D1. What makes this agentic rather than a set of modules?**
Three governors with genuinely competing objectives — safety wants more checking,
resource wants less spend, capacity wants reviewer time protected — and a
**deterministic** supervisor that arbitrates on reversibility, not on an LLM's
opinion. The conflict is real, and the resolution is auditable.
*If pressed:* An architecture where everything agrees is a pipeline with extra
words. Ours can deadlock, and the arbitration rule that breaks the deadlock is
written down and ledgered.

**D2. Why isn't the supervisor an LLM?**
Because its decisions must be reproducible. The moment a model arbitrates, you
lose "reproduce this decision," which is the strongest claim we have.

**D3. Where is the agent in your system, exactly?**
The agent proposes: which tool, what text, which sources. It cannot set blast
radius, price, route or governance status — those fields are rejected at the
parser. The model proposes; the plane decides.

**D4. Isn't a deterministic gate the opposite of agentic?**
Deliberately. Agentic where judgement helps — generation, recommendation
framing — deterministic where reproducibility is the product. Making that split
consciously *is* the architecture.

**D5. How many agents, and what are they?**
The provider agent proposes. Three governor agents advocate for competing
objectives. A supervisor arbitrates. The advisor produces recommendations with a
rule id and cited evidence.

---

## E · Scale and performance

**E1. What's your latency?**
Two numbers, and we publish both. Decision latency — what the user waits — held
at 104 ms p95 under 200 concurrent requests against an 800 ms budget. Verification
latency stretched under that load, which is the honest behaviour.
*If pressed, give the measured table:*

| Load | Decision p95 | Backlog | Queue | Health |
|---|---|---|---|---|
| 40 × 16 | 44.8 ms | 33 | 48 | degraded |
| 150 × 32 | 58.6 ms | 162 | 256 | degraded |
| 200 × 32 | 104 ms | 332 | 503 | degraded, 200 recorded `incomplete_due_to_capacity` |

**E2. Is that budget actually enforced, or just a label?**
Enforced. Work that misses the deadline is abandoned by the request path and
continued on a separate pool — and it contributes nothing to the price. We know
the difference because our first engine annotated the budget without enforcing
it, and we found that ourselves.

**E3. What happens at ten thousand requests a second?**
This prototype would not hold. The architecture doesn't change shape — the
in-process queue becomes a durable queue and the JSONL ledger becomes an
append-only store. We deliberately didn't build those, because we'd rather show
you a working control loop than a half-finished platform.

**E4. Doesn't governance add cost to every request?**
Inline detectors are deterministic and run in single-digit milliseconds. The
expensive checks are deferred and never sit in the request path. And the cost
detector measures the spend we're governing, so the overhead is visible in the
same place as the saving.

**E5. What if the queue fills up?**
Those decisions are recorded as `verification_incomplete_due_to_capacity` and
marked `partially_governed`. We proved it: at 200 concurrent, 200 decisions
carried that status and not one was silently dropped.

---

## F · Security, audit, compliance

**F1. Is the ledger tamper-proof?**
No. It is **tamper-evident** under protected key management — a SHA-256 hash
chain with an HMAC signature. We won't call it tamper-proof, because anyone with
the key and the file can rewrite both.
*If pressed:* In production the key lives in an HSM or KMS and the chain head is
anchored externally. That's an adapter change, not an architecture change.

**F2. How do I know the ledger wasn't edited?**
Any edit breaks the chain from that entry onward, and the signature fails. We
also verified it holds under concurrency — six threads, 150 appends, contiguous
and valid.

**F3. Who can apply a control?**
An authenticated operator. Mutating routes require a token and an actor header,
and the actor is what gets signed into the ledger. Human approval is the
**authenticated actor**, not a caller-supplied string.
*If pressed:* It is a prototype boundary, not enterprise IAM. In production it's
OIDC service identity and per-tenant authorization.

**F4. What about data residency and retention?**
Jurisdiction is a first-class field. The EU overlay tightens all three thresholds
and raises the privacy and fairness weights, with 2555-day retention; India is
1825. The developer page shows any team which overlay applies to them.

**F5. Can an overlay make a system *less* safe?**
No, and we prove it in a test across every profile and jurisdiction we ship.
Overlays only ever tighten. We found a case where India's privacy weight was
silently relaxing a stricter base profile, and fixed it.

**F6. Is the model's output stored?**
The full decision receipt is, including the proposal and what was released. That
is the point — a summary can't be audited. Retention is per jurisdiction.

**F7. What happens if the ledger write fails?**
The decision is downgraded to `ungoverned_due_to_failure` and surfaced on the ops
strip. It is never swallowed. A governance system that loses its own evidence
quietly is worse than one that admits it.

---

## G · Business and market

**G1. Who buys this?**
The person accountable for both the AI budget and the AI incidents. In a large
enterprise that's a head of AI platform or a CTO's delegate — Priya in our story.
Today that person has a spend dashboard and a risk committee, and no object that
joins them.

**G2. Why would they trust your thresholds?**
They shouldn't, initially — which is why the adoption path is shadow mode. Score
real traffic without acting on it, let them see the distribution, let them set the
operating point, then turn enforcement on per system. The buyer takes no risk and
has to trust none of our numbers.

**G3. What's the ROI?**
Two levers, and they are measured in the same object: reviewer minutes not spent
on responses that didn't need review, and incidents prevented on irreversible
actions.
*⚠️ If you use a rupee figure, you must be able to derive it live — reviewer
cost per minute × minutes saved, on screen. If you cannot do that arithmetic in
ten seconds, do not say the number.*

**G4. How do you price it?**
*Decide this as a team before the finale and say the same thing.* A defensible
answer: per governed system per month, because that is the unit the buyer already
budgets in, and it scales with the thing we protect rather than with token
volume.

**G5. Why would a company not just build this internally?**
Many will try, and they will build the dashboard. The hard parts are the ones
that look boring: deriving capability instead of trusting a declaration, making
replay deterministic, and being honest about degradation. Those took us three
rewrites.

**G6. What's the go-to-market?**
Land on one regulated department in shadow mode, prove the distribution, expand
by registry entry — adding a system is one entry, no code.

---

## H · Competition

**H1. Isn't this what Guardrails / NeMo / Prisma AIRS / ServiceNow already do?**
The guardrail products score text: is this toxic, is this leaking PII. We score
the **consequence** — what the action can do to the world, derived from the tool.
Two responses with identical bytes get different decisions in our system. They
cannot.
*If pressed, do not make claims about a competitor's roadmap.* Say: "If they add
consequence pricing, the interesting question becomes whether they derive it or
trust the caller — and that's the part that's hard."

**H2. How is this different from an observability tool?**
An observability tool tells you what happened. This decides what is allowed to
happen, and then acts on the fleet. The Suspend button is the difference.

**H3. What's your moat?**
Honestly, not the code. It's the registry and the ledger — once an organisation's
systems, tool bindings and policy history live here, the replay guarantee is only
worth anything if the history is continuous.

**H4. Why hasn't someone done this?**
Because it requires the tool layer to be legible, and that's only recently true.
Deriving capability from a tool binding isn't possible until agents call
registered tools.

---

## I · Process and team

**I1. What was the hardest part?**
Being honest about our own failures. Our first engine claimed an enforced latency
budget that wasn't enforced, and reported an async detector's time as zero. We
found it, proved it with failing tests, and rebuilt.

**I2. What did you get wrong?**
Several things, and we fixed all of them. The console couldn't authenticate to
its own API. A mandatory deferred check reported as fully governed. Replay said
"identical" while displaying two different confidence bands. Each one is a test
now.

**I3. What would you do with three more months?**
Shadow mode with a real customer's traffic, a durable queue, and a labelled
evaluation so we can publish an operating curve instead of declining to quote
accuracy.

**I4. Who did what?**
*Answer truthfully and specifically. Do not say "we both did everything."*

**I5. Did you use AI to build it?**
Yes, as a tool, like any modern team. We can explain any line of it — try us.
*Then invite them to pick a file.* This is a strong moment if you're prepared and
a fatal one if you're not. **Both of you must be able to explain
`gate.py`, `registry.py` and the pricing function without notes.**

---

## J · Hostile and trick questions

**J1. "Your demo blocked something that looked fine to me."**
It did, and for a reason you'd want. The text was fine. The *action* wasn't —
that tool can send to external customers and the application declared it as a
draft. We blocked the send and returned the text.

**J2. "This will block legitimate work and people will turn it off."**
That's the real failure mode for every governance product, and it's why three of
the four routes are not "block". Most traffic passes. Repair fixes deterministically.
Escalate asks a human. Block is reserved for irreversible actions with missing
evidence.

**J3. "You're adding a single point of failure in front of every AI system."**
Correct, and it has to be designed for. Today: if the model is unreachable we
fail closed and say so. In production it's a sidecar with a local fallback policy.
We'd rather fail closed and visibly than open and quietly.

**J4. "Your risk price is made up."**
The *constants* are a policy choice and we'd expect an organisation to retune
them. The *structure* isn't arbitrary: likelihood times consequence, with
consequence derived from capability rather than declared. Show me a governance
system that prices a draft and an irreversible transfer the same and I'll show
you one that will be ignored.

**J5. "What if the model lies about which tool it's calling?"**
It can't help us or hurt us by lying, because we don't ask. We resolve the tool
against the registry. A tool that isn't bound to that application is refused
outright.

**J6. "Ten of your fourteen finalists will say 'responsible AI'. Why are you
different?"**
Because we'll show you a number, an action class, and a refusal, and then replay
it. Most responsible-AI work is a policy document. This is an enforcement point.

**J7. "This only works because you control both sides of the demo."**
Fair. The independent parts are: the tests run on a clean clone, the ledger
verifies from disk, and the whole state rebuilds from evidence after a restart —
kill it and start it again and it reaches the same conclusions with nothing in
memory.

**J8. "Isn't 'silence is not health' just a missing heartbeat?"**
It is exactly a missing heartbeat, and almost nobody models it as a third state.
Two-state systems put silence in "compliant". That's the bug.

**J9. "Show me a case where your system is wrong."**
*Have one ready and say it without flinching:* Grounding will mark a correct
paraphrase as unverifiable if it shares no vocabulary with its source. It is
conservative in the direction of escalating to a human, which is the direction we
chose — and on the developer page we tell the team that's what happened, rather
than just saying "blocked".

---

## K · Questions you should hope for

These are where you are strongest. If the conversation goes quiet, you may
volunteer one — *"can I show you one thing we're proud of?"*

- **Anything about latency or performance** → the two clocks, and the fact you
  caught your own unenforced budget.
- **"How would an auditor verify this?"** → reproduce, eight fields, policy
  snapshot, evidence-at-decision.
- **"How do you know your governance is working?"** → consequence-weighted
  completeness, and `not_available` at zero decisions rather than 100%.
- **"What happens when it's overloaded?"** → the measured degradation table.
- **"How do you add a new AI system?"** → one registry entry, no code.

---

## L · Where the honest answer is "we didn't do that"

Say these cleanly. Hedging on them costs more than the gap does.

- **A labelled accuracy benchmark.** We haven't run one. Shadow mode is how you'd
  get one honestly.
- **Enterprise IAM.** Prototype token boundary.
- **Durable queue and store.** In-process and JSONL. Deliberate.
- **Semantic verification.** Lexical support checking. Stated on the product page.
- **Multi-tenancy.** Single tenant.
- **A real customer deployment.** None yet.

The framing that turns each of these into a point rather than a hole:

> "In production that becomes a durable queue, an append-only store, per-tenant
> authorization and OIDC service identity. The architecture doesn't change shape —
> only the storage and identity adapters do. We deliberately didn't build them,
> because we'd rather show you a working control loop than a half-finished
> platform."

---

---

# PART 3 — Things that will lose you the room

**Never say a number you cannot derive.** Especially the ROI figure. If you can't
show the arithmetic in ten seconds, drop it.

**Never say "tamper-proof."** Say tamper-evident. A technical juror who catches
that will doubt everything else.

**Never say "we detect hallucinations."** Say you verify support, and that
unverifiable is different from wrong.

**Never say "100% accurate", "guaranteed", or "fully autonomous."**

**Never debug on stage.** Switch beats, or switch laptops.

**Never talk over the demo.** Click, let them look for two seconds, then say the
one sentence that explains what they saw. Do not narrate what is visibly
happening.

**Never answer a question you didn't understand.** "Do you mean X or Y?" costs
three seconds and saves a bad answer.

**Never let one person answer everything.** Decide in advance: Adithya takes
mechanism and implementation, Gungun takes problem, impact and market. Either can
take the rest.

**If you don't know:** *"I don't know — here's how we'd find out."* That scores.
Bluffing does not.

---

---

# PART 4 — Morning-of checklist

**The night before**

- [ ] Fresh clone into a clean folder. `pip install -r requirements.txt`.
- [ ] `python -m pytest test/ -q` → **107 passed**. On both laptops.
- [ ] Run the full demo path end to end. Twice. On both laptops.
- [ ] Run it once with wifi off, offline provider.
- [ ] Screenshot deck of every beat, in order, hidden at the end of the slides.
- [ ] Deck in the Accenture 16:9 template. **Get it from Manjula if you still
      haven't.**
- [ ] Both of you can explain `gate.py` and the pricing function without notes.

**Ninety minutes before**

- [ ] Both laptops charged and on mains. Adapters for the room's display.
- [ ] Server running on both. Portfolio page loaded on both.
- [ ] Reset the demo, let it seed, confirm the grey light is grey.
- [ ] Browser zoom set so the back row can read the decision stream. Test from
      the back of a room.
- [ ] Notifications off. Do Not Disturb. Phone away.
- [ ] `.env` closed. **Do not open it on a projector.**

**Sixty seconds before**

- [ ] Portfolio page open and finished loading.
- [ ] Deck in presenter view on the other display.
- [ ] Both of you know who speaks first.
- [ ] Four sentences in your head: the grey light, the capability lie, the two
      clocks, the difference between a dashboard and a control plane.

**Immediately after**

- [ ] **Rotate the Gemini API key.** It has been pasted in chat and shown on
      screen. Treat it as exposed.
