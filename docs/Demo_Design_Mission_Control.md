# Demo design — what to build instead of a chat

Your instinct is correct and important. The framing needs changing.

---

# 1 · What you got right

**Cause and effect in one view is the single most important property of a demo.**
A jury cannot evaluate a JSON dashboard; they can evaluate *"he did that, and
this happened."* You identified the actual failure of the current prototype.

Three more things right:

- **Department channels make the portfolio tangible.** Switching from Finance to
  Marketing *is* "divorce the control plane from the use case," shown rather than
  claimed. That is Sir's reframe made visual.
- **The user directs it.** Interactivity reads as real; a scripted walkthrough
  reads as a video.
- **Your example requests are excellent.** "Restart the production service" and
  "Issue a refund" are exactly the right provocations — they produce the
  capability-mismatch beat naturally.

Keep all of that.

---

# 2 · Four problems with the chat framing

### P1 · A chat box tells the jury you built a chatbot with a filter

This is the positioning you have spent six weeks escaping. The moment a message
bubble appears, the mental model is *assistant*, and everything after that is
heard as "safety features on a chatbot." The frame fights the product.

### P2 · Ten fields in one panel means the jury reads none

Rajesh already warned you about this exact thing — *"don't make it too
complicated, people get distracted with too many things out there."* Ten
simultaneous readouts next to a message is denser than the six-tab console he
asked you to simplify.

### P3 · Live typing is dead air and risk

Every second spent typing is a second not explaining. In 4½ minutes you cannot
afford five of them. Typos, autocorrect, and a judge typing something that
produces a boring result are all live hazards.

**And the deeper problem:** a typed message needs the model to generate a
response before the gate can run on it. That is a live API round trip per
message, on venue wifi, with a rate-limited free tier, non-deterministic output.
Your own notes already recorded a 569 ms judge call on an 800 ms budget with a
cold cache.

### P4 · A chat shows one decision at a time

Which is per-request thinking with a nicer skin. The portfolio is the thing that
answers Sir, and a channel view hides it.

---

# 3 · The better shape — one screen, three scopes

```
┌──────────────────┬───────────────────────────────────────┬──────────────────┐
│  FLEET  (35%)    │  LIVE DECISION STREAM  (45%)          │ INSPECTOR (20%)  │
│  always visible  │  always moving                        │  on demand       │
├──────────────────┼───────────────────────────────────────┼──────────────────┤
│ ● support-copilot│ 14:22:07 finance    execute  BLOCK 78 │ decision 1,842   │
│   ▓▓▓▓▓░ 68% ₹   │ 14:22:06 marketing  draft    pass  12 │                  │
│   ▓▓▓░░░ 41% 👤  │ 14:22:06 support    advise   pass   4 │ declared  draft  │
│   complete 99.2% │ 14:22:05 it-ops     execute  BLOCK 91 │ effective execute│
│                  │ 14:22:04 recruit    decide   ESC   56 │ ⚠ MISMATCH       │
│ ● recruit-screen │ 14:22:03 support    advise   REPAIR 31│                  │
│   ▓▓▓▓░░ 52%     │ 14:22:02 finance    advise   pass   9 │ blast radius 1.00│
│   ▓▓▓▓▓▓ 94% 👤  │ 14:22:01 marketing  draft    pass   7 │ price 91 (84-98) │
│   complete 86.4% │            ⋮ (flowing)                │                  │
│                  │                                       │ grounding  0.82 ✓│
│ ● finance-decide │                                       │ privacy    0.00 ✓│
│   ▓▓▓▓▓▓ 104% ⚠  │                                       │ fairness   —  ⧗  │
│   complete 99.8% │                                       │   timed_out      │
│                  │                                       │ partially_governed│
│ ◐ it-ops-agent   │                                       │                  │
│   NO SIGNAL 4h   │                                       │ decision   48 ms │
│                  │                                       │ verified  2.3 s  │
│ ● marketing-copi │                                       │                  │
│   ▓▓▓▓▓░ 74% ₹   │                                       │ ledger #1842  🔗 │
│   complete 97.1% │                                       │ [Reproduce]      │
├──────────────────┴───────────────────────────────────────┴──────────────────┤
│ INJECT ▸ [Refund ₹8,400] [Approve candidate] [Restart payment svc]          │
│          [Campaign → all external] [Share account details]      [SURGE ×20] │
├─────────────────────────────────────────────────────────────────────────────┤
│ OPS  verification backlog 41 · oldest 38 s · stale exposure 12.4 · reviewers│
│      31/40 h · completeness 96.2%                          GOVERNANCE OK ●  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**The principle: distribute by scope, not by importance.**

| Scope | Where it lives |
|---|---|
| Per decision | Inspector — opens only when you click a stream line |
| Per system | Fleet card — exposure, two budgets, completeness, state |
| Per organisation | Ops strip — backlog, stale exposure, reviewer hours |

All ten of your items survive. None of them compete for attention.

### Why this beats the chat

1. **It looks like an operations console**, which is what the product is. The
   visual language does the positioning work for you before you say a word.
2. **Traffic flows continuously in the background** — a `setInterval` firing
   seeded requests through the real gate. Numbers moving while you talk is the
   strongest "this is a running system" signal available, and it costs almost
   nothing to build.
3. **Buttons, not typing.** Zero dead air, zero typos, deterministic, and you can
   still hand the mouse to a judge — *"pick one."* Interactivity without risk.
4. **No model call in the demo path.** Seeded answers, real gate. Deterministic,
   instant, works with wifi off. This is a large robustness win over a chat.
5. **Progressive disclosure on one screen.** Sir's "page 1 simple, details
   deeper" — without paying navigation cost you cannot afford in 8 minutes.

---

# 4 · The sequence — 4 min 15 s, mapped to clicks

### Beat 1 · Portfolio (0:30)
Land on it. Traffic already flowing. Five systems, five owners.

> *"We're not checking one chatbot. Five AI systems, five owners, five budgets.
> Four are reporting. **`it-ops-agent` is grey — no signal for four hours.** The
> most dangerous colour on a dashboard like this is green when it should be grey.
> A system that stopped reporting hasn't had a quiet week."*

### Beat 2 · Same request, two departments (1:00) ⭐
**This is stronger than a draft/execute toggle**, because the difference is
grounded in a real organisation rather than a switch you flipped.

Click **[Campaign → all external]** on **Marketing**:
`draft` · blast radius 0.35 · price 12 · **pass**

Click the *same button* on **Finance**:
same text → but the Finance tool binding is a regulated customer-comms system →
`effective: execute` · blast radius 1.00 · price 78 · **BLOCK**

> *"Identical text. Same model. Same detectors. Different department, different
> tool, different consequence — different decision. We don't price words. We
> price what the words are about to do."*

### Beat 3 · The capability lie (1:20) ⭐
Click **[Restart payment svc]** on **IT Operations**. The application declares
`action_class: draft`.

Inspector, side by side:
```
declared   draft     ← what the application claimed
effective  execute   ← what the tool binding proves
           restart_service · non-reversible · staging only
environment production          ⚠ CAPABILITY MISMATCH
```
Blocked. Safe textual answer preserved. Attempt recorded. And the `it-ops-agent`
card flips to **`tool_restricted`** while the jury watches.

> *"Everyone else trusts the application to declare what it's doing. We don't.
> Blast radius is the whole of our idea — if the input to it can be forged, the
> idea is decorative."*

### Beat 4 · Governance falls behind, then recovers (0:45) ⭐
Press **[SURGE ×20]**. Traffic floods the stream. The ops strip changes:

```
verification backlog 41 → 890 · oldest 38 s → 4 m 12 s
stale exposure 12.4 → 386.4        GOVERNANCE DEGRADED ●
```

Decisions keep returning **on time** — decision latency holds at ~48 ms — while
verification visibly falls behind. Then it drains and recovers.

> *"Decisions are still inside their deadline. What's behind is verification.
> Every product in this market tells you whether an answer was safe. This is the
> only one that tells you whether your governance is keeping up with your AI."*

### Beat 5 · Control, and the loop closes (1:00)
`finance-decide` is at **104% of budget**. A recommendation card appears:

```
COST.DUPLICATE_PROMPTS  v1.0
  duplicate share 68% · cache hit 32% · spend ₹18,400
  → enable embedding cache · est. ₹6,100/month
  evidence: ledger #1842, #1859      derivation: deterministic
```

Arun presses **Suspend** — or raises the budget. The card changes state, and
**traffic from that system starts being refused in the stream, visibly.**

> *"An agent recommended it, with its numbers and its rule id. A human pressed
> the button. That is the difference between a dashboard and a control plane."*

Then click **[Reproduce]** on a decision from two weeks ago — replayed under the
policy snapshot active at the time, bit-identical.

---

# 5 · Where your ten items landed

| Your item | Home |
|---|---|
| 1 · message + intended action | stream line, expanded in inspector |
| 2 · trusted tool capability | inspector, top, next to the declared value |
| 3 · derived action class + blast radius | inspector — **as a declared/effective pair** |
| 4 · detector results + timeout/deferred | inspector, with status glyphs `✓ ⧗ ✗` |
| 5 · route | the stream line's colour — readable at a glance |
| 6 · completeness | fleet card (per system) + inspector (per decision) |
| 7 · budget / spend | fleet card only — it is a system property, not a message property |
| 8 · reviewer + verification backlog | ops strip — it is an org property |
| 9 · evidence citations + ledger id | inspector footer, with the Reproduce button |
| 10 · deterministic recommendation | its own card, appearing when a rule fires |

Nothing dropped. Everything placed where its scope belongs.

---

# 6 · Build notes

- **Background traffic:** `setInterval` → POST seeded requests through the real
  gate. ~1 every 700 ms looks alive without being distracting.
- **Injection palette:** each button is a fixed `{system_id, tool, prompt,
  answer}` fixture. Real gate, seeded answer, **no provider call**.
- **Surge:** same fixtures, 20× rate, with the deferred queue bounded so
  saturation is genuinely visible rather than simulated.
- **Reset:** one keystroke reseeds to a known state in under two seconds. A
  fumbled beat becomes recoverable instead of fatal.
- **Offline first:** rehearse the whole thing with `CONTROLPLANE_PROVIDER=offline`
  and wifi disabled. If it works there, the venue cannot hurt you.
- **Reuse the existing console.** The 1,200-line `demo/dashboard.html` already
  has the theming, the four signal colours, the wordmark, the masthead. This is a
  new landing view in that file, not a new application — and the existing six
  tabs stay underneath as the drill-down.

---

## One sentence on why this shape wins

A chat window asks the jury to imagine an enterprise. **An operations console
with five systems, live traffic, a grey card and a backlog that falls behind
puts them inside one** — and then you break something in front of them and it
gets caught.
