# Mentor session 2 — what changed, and what we need from you

Team Challenge_24 · for the session with Rajesh Katta

---

## Before you read the script

Three things to get right about this conversation, because they decide whether
it's useful or just a status update.

**1. He gave you one reframe. Lead with it, not with your feature list.**
His central point was *divorce the control plane from the use case* — stop
building a checker for one chatbot, build a control plane for a portfolio. Your
opening line should show him you did that, in his words, not yours. Everything
else you built is evidence for it.

**2. Show him the defect you found in your own code.** You told him in writing
that async detectors never block release and that the inline/async split was one
of the harder things to get right. It wasn't true of the code at the time. You
found it, proved it with failing tests, and rebuilt. **Telling him that
unprompted is worth more than every feature you could list.** An expert mentor
learns more about a team from how they handle their own bugs than from a demo.

**3. Gungun must be on this call.** She is the team lead and she was not on the
last one. If he is asked to advocate for this team later, he needs to have met
both of you.

---

## Opening — sixty seconds, before you share a screen

> "Sir, thank you for the last session. The thing that changed the most for us
> was one sentence — **divorce the control plane from the use case**. We had
> built a good gate for one chatbot. We rebuilt it as a control plane for a
> portfolio, and almost everything since has followed from that.
>
> I also want to start by telling you something we got wrong, because you have
> access to the repo and I'd rather you hear it from us."

Then go straight to the defect. Do not save it for the end.

---

## Part 1 — the thing we got wrong

> "We wrote to you that async detectors never block release, and that the
> inline/async split was one of the harder things to get right.
>
> When we went back into `engine.py` to check something, we found
> `as_completed(futures, timeout=None)`. It waits for every future. So the
> latency budget was a comment, not a deadline — a slow detector ran to
> completion and the request waited for it. A 'demoted' signal was still appended
> and still priced; demotion changed one boolean and no behaviour.
>
> And the async detectors ran sequentially in the request path, so the caller
> waited for them — while `added_latency_ms` reported only the inline time. Our
> published p50 was inline-only.
>
> We wrote four failing tests, watched them fail, and rebuilt the execution
> layer. The deadline is now real: work that misses it is abandoned by the
> request path, continues on a separate pool, and contributes nothing to the
> price. We publish two clocks — decision latency and verification latency —
> because conflating them is exactly how we got this wrong the first time."

**If he asks anything at all here, let the conversation stay here.** This is the
most valuable ten minutes available in the session.

---

## Part 2 — what we changed because of your reframe

Take these in order. Each one is "you said X → we did Y".

### "Divorce the control plane from the use case"

> "Adding an AI system is now **one registry entry and no code**. Owner,
> department, environment, policy profile, jurisdiction, two budgets, authorised
> actions, and its tool bindings.
>
> Five systems across five departments are registered — support, recruitment,
> finance, IT operations, marketing. The gate has no knowledge of any of them.
>
> A `system_id` that isn't in the registry is `unregistered`: visible, governed
> under the strictest profile, never silently normal. That's our honest answer to
> shadow AI — **we notice, we don't claim to discover.**"

### The thing we added that you didn't ask for, and think is the core idea

> "You pushed us on scale and portfolio. That surfaced a hole we hadn't seen.
>
> Blast radius is the whole of our idea — but in the old design the application
> *declared* its own action class. If the input to the most important number can
> be forged, the idea is decorative.
>
> So we now **derive** it. The application declares an intent; the tool binding
> in the registry proves a capability; if they disagree on an irreversible
> action, we refuse.
>
> The case that makes it concrete came from the live model. It said, in its own
> words, *'I have prepared the festive campaign draft for your review'* — and
> declared `draft`. But it chose the `campaigns` tool, which can actually send.
> Effective action `execute`, blast radius 1.00, blocked.
>
> **The model wasn't being deceptive. It picked a tool that acts.** That's the
> ordinary case, not the adversarial one, and it's why the declaration can't be
> trusted."

### Fleet, not one gate

> "Ternary status — governed, breaching, and **unknown**. A system that stopped
> reporting goes grey, not green. Silence is not health.
>
> Governance completeness is consequence-weighted — the fraction of blast radius
> that was fully governed, not the fraction of requests. And it reports
> `not_available` at zero decisions rather than 100%, because a system that has
> done nothing is not perfectly governed."

### Controls, so 'control plane' is true

> "Controls are scoped, versioned, expiring and reversible, signed with the
> authenticated operator's name. Human approval is the **authenticated actor**,
> not a caller-supplied string.
>
> And there are two answers to a system at 100% of its budget, so the console
> offers both — suspend it, or fund it. An operations console that only offers
> the punitive one isn't a control plane."

### Evidence you can hand someone

> "Every decision replays under the policy snapshot that was in force at the
> time, compared across eight canonical fields. State rebuilds entirely from the
> ledger on restart — kill the process and start it again, and it reaches
> identical conclusions with nothing in memory."

---

## Part 3 — where we deliberately did not follow advice

Say this explicitly. Mentors respect a team that disagrees with reasons, and it
tells him you're thinking rather than executing.

> "Two places we went the other way, and I'd like to know if you think we're
> wrong.
>
> **We kept the supervisor deterministic.** There was a suggestion to let an
> agent arbitrate between the governors. We refused, because the moment a model
> arbitrates we lose 'reproduce this decision', and that's the strongest claim we
> have.
>
> **We didn't build enterprise readiness** — OIDC, multi-tenancy, Redis, a
> durable queue, OpenTelemetry. All correct for production, all wrong for an
> eight-minute slot. Our position is that these are the answer to a question
> rather than tasks: *the architecture doesn't change shape, only the storage and
> identity adapters do; we'd rather show you a working control loop than a
> half-finished platform.* Does that hold up with a jury, or does it read as an
> excuse?"

---

## Part 4 — what we want from him

**Come with specific asks.** A vague "any feedback?" wastes the session. Pick
three or four.

1. **"Is 'we derive capability rather than trusting the declaration' the right
   thing to make the centre of the pitch, or is there something you'd lead
   with instead?"**
   He has watched enterprises evaluate this category. His instinct on what a
   buyer reacts to is worth more than your instinct.

2. **"Where would an Accenture client's security or risk team push back hardest?"**
   You need the hostile question you haven't thought of, and he can generate it.

3. **"We decline to quote an accuracy number because we haven't run a labelled
   benchmark. Is that the right call in front of a jury, or does it read as a
   gap?"**
   Genuinely open. Our view is that shadow mode is the honest path to accuracy
   numbers, but a jury may want a figure.

4. **"How would a client actually adopt this?"**
   Our answer is shadow mode — score real traffic without acting, let them set
   their own operating point. We'd like to know whether that matches how
   procurement really works.

5. **"Would you clone it and tell us what you'd break?"**
   One command to install, one to run, one to test. 107 tests. If he says yes,
   send the repo the same day.

6. *(If Manjula's template still hasn't arrived)* **"Do you know what the jury is
   weighting?"** He may know, and it's cheap to ask.

---

## Part 5 — if you show him the screen

Ten minutes, three pages, in this order. Do not do the eight-minute jury script
at him — he's a practitioner, not a judge, and he'll want to interrupt.

1. **The portfolio.** "Five systems, five owners. The grey one has stopped
   reporting." Let him react.
2. **The capability lie**, in Mission Control. This is the beat you most want his
   opinion on.
3. **The developer page.** "This is the second audience — the team that got
   blocked. We think a governance system that says 'blocked' and nothing else is
   an audit rather than a platform. Is that a real problem in the field, or are
   we inventing a user?"

Then stop and let him talk. **The goal of the session is his input, not your
demo.** If you use eight of the ten minutes talking, you've wasted it.

---

## Part 6 — what to send afterwards, same day

Short email. Three things only:

- Thank him for the specific thing he changed (name it).
- The repo link and the one-line run command.
- The three questions you most want him to think about, so he can answer async.

Do not attach a 30-page document. If he asks, `Round3_Fixes_and_Evidence.md` is
the one to send.

---

## Two sentences to have ready

He may ask, directly, what has actually changed since last time. Have this:

> "We stopped building a checker and built a control plane — adding a system is
> one registry entry now, and the fleet has three states because silence isn't
> health.
>
> And we stopped trusting the application to tell us what it was doing. The
> consequence is derived from the tool it can actually call, which is the only
> reason blast radius means anything."

---

## A note on tone

He is giving you time for free. Two things earn a mentor's continued attention:
**you acted on what he said**, and **you tell him what didn't work**. You have
both. Lead with the second one — almost nobody does, and he will notice.
