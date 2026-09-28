# 8 minutes + 5 Q&A — what this changes

Accenture, Grand Finale · Team Challenge_24

---

## What actually changed

| | Previously assumed | Now confirmed |
|---|---|---|
| Presentation | 10 min | **8 min — presentation *and* live demo together** |
| Q&A | 5 min | 5 min |
| Deck | optional (per Rajesh) | **mandatory, 16:9, Accenture template** |
| Prototype | expected | **mandatory, working, demonstrated live** |

Two consequences that matter more than they look:

**1. Your demo just lost a third of its time.** Eight minutes total means roughly
**3 minutes of slides and 4½ minutes of demo**, with 30 seconds of slack you will
need. Six demo beats is now impossible. Four is the honest maximum.

**2. Q&A is now 38% of your total airtime.** Five minutes of questions against
eight minutes of presentation. **This inverts the build calculus in a useful
way:** depth you cannot show, you can still be *asked about*. Everything beyond
what fits in 4½ minutes is not wasted — it moves from the demo into the Q&A and
onto backup slides.

So the build guidance sharpens rather than shrinks:

> **Build to Stop C. Demo Stop B plus one control action. Keep D and E as Q&A
> ammunition and backup slides.**

---

## The 8-minute script

Rehearse against a visible timer. Every team overruns; the ones who don't are
the ones who rehearsed with a clock.

| Time | Segment | Mode |
|---|---|---|
| **0:00–0:45** | **The king.** A consulting firm told everyone to use AI. Within a month the token bill was frightening — people writing two-line emails with a frontier model. In the same quarter a screening copilot nobody was watching was making decisions about real people. Two failures, one cause: **nobody could see what any of the AI systems were doing.** | Slides |
| **0:45–1:30** | **Priya's two questions.** She runs the AI platform and is accountable for both. What is all of this costing us, and what is it doing that we couldn't defend in public? Cost and risk. There is no third question. | Slides |
| **1:30–2:00** | **What ControlPlane is.** One line changed — the model base URL. Every AI system in the organisation subscribes. We price every answer and every action by **what it is about to do**, not how it is worded. Architecture slide: data plane / ledger / control plane. | Slides |
| **2:00–6:15** | **LIVE** — four beats, below | Browser |
| **6:15–7:15** | **Impact and scale.** ₹20.8 cr exhaustive review → ₹1.01 cr. Measured throughput. Two registries: a new risk category is one line, a new governance domain is one line. Differentiation: they secure, we price correctness. | Slides |
| **7:15–8:00** | **Close on the people.** Priya sleeps. Arun controls his own spend. The developer knows why they were flagged. The auditor finally gets an answer to "why was this allowed to reach a customer?" | Slides |

### The four demo beats — 4 min 15 s

| | Beat | Time | The line |
|---|---|---|---|
| **1** | **Portfolio.** Five systems, owners, two budgets, exposure, status — one of them **grey**. | 0:30 | *"We're not checking one chatbot. And the most dangerous colour here is green when it should be grey — a system that stopped reporting hasn't had a quiet week."* |
| **2** | **Identical text, two action classes.** Same bytes as a `draft` and as an `execute`. Two prices, two decisions. | 1:00 | *"Same model, same words, same detectors. Different consequence, different decision."* |
| **3** | **The capability lie.** ⭐ The IT agent calls `restart_service` in production declaring `draft`. Effective capability resolves to `execute` from the tool binding → blast radius 1.00 → hard gate → side effect blocked, safe text preserved, mismatch recorded. | 1:20 | *"Everyone else trusts the application to declare what it's doing. Blast radius is the whole of our idea — if its input can be forged, the idea is decorative."* |
| **4** | **Control.** The red system. The cost agent's recommendation with its numbers. Arun presses **Suspend** — or raises the budget. The light changes. | 1:25 | *"That is the difference between a dashboard and a control plane."* |

**Two screen switches in the whole presentation.** Slides → browser at 2:00,
browser → slides at 6:15. Every extra switch costs 5–10 seconds and invites a
fumble. Put the deck in presenter view on one display and the browser on the
other, both already open, both already at the right place.

---

## What moves to Q&A and backup slides

Not cut — relocated. Have a slide for each, hidden at the end of the deck, ready
to jump to if asked.

| Moved out of the demo | Where it lives now |
|---|---|
| Honest degradation + two clocks | Backup slide. **Volunteer it if asked anything about latency or performance.** It is your strongest credibility moment. |
| Arbitration between governors | Architecture slide + backup. Answer to *"what makes this agentic?"* |
| Reproduce this decision | Backup. Answer to *"how would an auditor verify this?"* |
| Shadow mode | Backup. Answer to *"how would a customer adopt this?"* — and it is your best answer to *"who buys this?"* |
| Governance completeness | Backup. Answer to *"how do you know your governance is working?"* |
| Evaluation / operating point | Backup. Answer to *"how accurate is it?"* |
| Competitive position | Backup. Answer to *"isn't this ServiceNow / Prisma AIRS?"* |

**Rehearse the jump.** Know the slide numbers. "Let me show you" plus three
seconds of arrow-key navigation reads as preparedness; fifteen seconds of
scrolling reads as the opposite.

---

## Revised build priority

The 8-minute constraint does **not** mean build less. It means demo less.

| Stop | Build it? | Demoed? |
|---|---|---|
| **A** — truthful gate, capability | **Yes, essential** | Beats 2 and 3 |
| **B** — fleet, portfolio, exposure, two budgets, grey state | **Yes, essential** | Beat 1 |
| **C** — controls, governors, supervisor, arbitration | **Yes** | Beat 4 uses the control; arbitration goes to Q&A |
| **D** — replay, reproduce, shadow | **Yes if you get there** | Q&A only |
| **E** — rule engine, effectiveness | **If time allows** | Q&A only |

**Beats 2 and 3 both live inside Stop A.** Beat 1 needs B. Beat 4 needs one
control action from C. That is the entire demo surface — everything else you
build is for the five minutes where a jury is trying to find the edge of what
you understand.

---

## Practical, and worth doing this week

1. **Get the template now.** If you don't already have the Accenture 16:9
   template, email Manjula today. Building a deck and then reformatting it into
   a prescribed template the night before is a known way to lose an evening.
2. **Ask her what the jury is expecting** while you're at it — she offered this
   on the mentor call and nobody followed up.
3. **8:00 is a hard stop.** Assume you will be cut off. Put nothing load-bearing
   after 7:15.
4. **Rehearse the demo at least ten times**, including once on the other laptop,
   once on a clean clone, and once with wifi disabled in offline provider mode.
5. **Screenshot deck of every demo beat**, in order, hidden at the end. If the
   laptop dies you keep talking. You will almost certainly not need it.
6. **Decide who speaks when.** Two presenters, eight minutes. A handover mid-demo
   costs time; a handover at a slide boundary costs nothing. Suggested: Gungun
   takes 0:00–2:00 and 6:15–8:00, Adithya drives the demo.
7. **Reset script.** One command that reseeds to a known state in two seconds, so
   a fumbled beat is recoverable instead of fatal.

---

## The one thing to internalise

Eight minutes with a mandatory live demo means **the demo must carry the
argument, not illustrate it.** Do not narrate what the jury is already watching.
Say the sentence that explains what they just saw, then move.

Each of the four beats has exactly one sentence. Learn those four sentences
cold. Everything else in the demo is pointing and clicking.
