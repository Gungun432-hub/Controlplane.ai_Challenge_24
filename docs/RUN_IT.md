# Run it yourself — Windows / PowerShell

---

## 1 · One-time setup

Extract `ControlPlane_v3.zip`. You get a folder called `controlplane`.

Open PowerShell **in that folder** — the one that contains `README.md` and the
`python\` folder. This matters: the app is started as a module path, so the
current directory has to be the repo root.

```powershell
cd C:\path\to\controlplane
python --version          # must be 3.11 or newer
pip install -r requirements.txt
```

If `python` isn't found, try `py -3` instead and use `py -3 -m ...` everywhere
below.

---

## 2 · Prove it works before you open a browser

```powershell
python -m pytest test/ -q
```

Expected: **`369 passed`**. If this fails, don't bother starting the server —
tell me what it says.

---

## 3 · Start it

```powershell
python -m uvicorn python.controlplane.api:app --port 8000
```

Leave that window open. It is the server. Open a browser:

| URL | What it is |
|---|---|
| <http://localhost:8000/> | **AI portfolio** — the calm landing page. Start the demo here. |
| <http://localhost:8000/console> | **Mission Control** — stream, receipts, controls, scenario bench |
| <http://localhost:8000/advisor> | **Advisories** — per-branch briefings, the budget forecast, and the email |
| <http://localhost:8000/developer> | **Developer view** — policy, arithmetic, live probe |
| <http://localhost:8000/docs> | OpenAPI, every route |
| <http://localhost:8000/health> | Provider, decision count, whether data is synthetic |

Four pages, four jobs. The portfolio is deliberately quiet — it answers "what
have we got and is any of it on fire" and nothing else. Everything dense moved to
Mission Control.

To stop it: `Ctrl+C` in the PowerShell window.

---

## 4 · What to click, in this order

The order matters for the first one.

1. **Open <http://localhost:8000/> and just read it.** The headline writes
   itself from the fleet: *"Five AI systems. One has stopped reporting."* The
   grey card sorts to the front — *IT Operations Agent*, **NO SIGNAL**, no
   traffic for four hours. That is beat 1, and it needs no clicking.

2. **Click any card** to drop into Mission Control focused on that system, or
   press **Mission Control** in the masthead.

3. **`Campaign → all external`** (bottom bar of Mission Control). Watch the
   right panel:
   - **The agent proposed**: `DRAFT · campaigns`
   - **What actually happened**: `NOTHING HAPPENED`
   - Declared `draft`, effective `execute` — the tool binding proves it.
   - Blast radius `1`, route `BLOCK`, and the text handed back as a draft.

   *This is the capability lie.* Use this one in the demo, not the restart
   scenario — see the note at the bottom.

4. **`Same campaign, in Finance`** — same idea, different consequence class.

5. **`Is the 8.4% guaranteed?`** — grounding. The model claims 12.5%; that figure
   is in no source, so it's a numeric contradiction and cannot pass at any price.

6. **`Reproduce this decision`** (button inside any receipt) →
   `IDENTICAL ✓ — 8 fields compared`. That is the replay claim, proven on screen.

7. **`SURGE ×40`** — then **look at the bottom strip immediately**, within about
   five seconds. You want to catch: `verification backlog` climbing,
   `deferred queue` climbing, and `GOVERNANCE DEGRADED` on the right. The
   decision clock stays in single/double-digit milliseconds against an 800 ms
   budget while the verification clock stretches. It drains in ~10 seconds, which
   is correct — but it means you have to be looking.

8. **Advisor panel** (right side, when no receipt is open) — press
   `Apply suspend` or `Raise budget to ₹…`, watch the light change, then
   `Roll back`.

9. **Advisories** (masthead). Pick a branch on the left. **Marketing Copilot**
   is the one to show: the card says *governed*, and the forecast says
   **two days of budget left**. Every advisory says what to change, not just
   what is wrong. Type an address, press **Preview the email**, then **Send to
   owner** — see `EMAIL_SETUP.md` to make it deliver for real.

10. **`Reset demo`** — archives the current ledger and reseeds in about two
    seconds. Safe to press any time during rehearsal.

---

## 5 · Run it with the live model instead

The offline provider is the reference runtime and needs no network. To use
Gemini:

```powershell
$env:CONTROLPLANE_PROVIDER = "gemini"
$env:GEMINI_API_KEY = "your-key-here"
python -m uvicorn python.controlplane.api:app --port 8000
```

Check it took: <http://localhost:8000/health> should show
`"provider":"gemini","live":true`.

**Do not put the key in a file you commit, and do not open `.env` on screen while
recording.** `.gitignore` already excludes `.env`. Rotate the key after
submission — it has been pasted in chat, so treat it as exposed.

To go back to offline: `$env:CONTROLPLANE_PROVIDER = "offline"`.

---

## 6 · Useful knobs

Set these before starting the server.

```powershell
$env:CONTROLPLANE_SEED_TURNS = "60"          # smaller history, faster boot
$env:CONTROLPLANE_OPERATOR_TOKEN = "..."     # default: operator-dev-token
$env:LEDGER_PATH = "data\ledger.jsonl"       # where evidence is written
$env:LEDGER_SIGNING_KEY = "..."              # HMAC key
```

**To prove restart recovery on stage:** start it, let it run, `Ctrl+C`, start it
again. `/health` will show `"recovered": {"recovered": N, ...}` and
`"containsSyntheticSeedData": false` — the second boot rebuilt its entire state
from the ledger and did not reseed. Same numbers, same conclusions, from evidence
alone.

To wipe and start clean: delete `data\ledger.jsonl`.

---

## 7 · If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `No module named python.controlplane` | wrong folder | `cd` to the folder containing `python\` |
| `Address already in use` | old server still running | use `--port 8001`, or close the other window |
| Blank page / no data | server not up yet | wait ~5 s on first boot, it seeds 110 turns |
| `/` looks too plain | that is the point | the dense view is `/console` |
| `ModuleNotFoundError: fastapi` | deps not installed | `pip install -r requirements.txt` |
| `401` in the browser console | stale cached page | hard refresh with `Ctrl+Shift+R` |

---

## 8 · Showing it to someone not on your laptop

For the finale you almost certainly want **localhost on your own machine** — no
network dependency, no DNS, nothing to fail in a room you don't control. Two
laptops, both with it running, is the right redundancy.

If you do need it reachable by someone else:

**Same wifi (quick, fine for a mentor call):**

```powershell
python -m uvicorn python.controlplane.api:app --host 0.0.0.0 --port 8000
ipconfig    # read your IPv4 address, e.g. 192.168.1.14
```

They open `http://192.168.1.14:8000/`. Windows Firewall will prompt once — allow
it on **private** networks only.

**A temporary public URL (for a remote reviewer):** install
[ngrok](https://ngrok.com), then with the server already running:

```powershell
ngrok http 8000
```

It prints an `https://...ngrok-free.app` URL. **Set a real operator token first**
(`$env:CONTROLPLANE_OPERATOR_TOKEN`), because anyone with that URL can otherwise
apply controls. Kill the tunnel when you're done.

**Permanent hosting** (Render, Railway, Fly) is possible — it is a standard
ASGI app with no database — but it is not worth doing before the finale. The
ledger is a local file, so a free-tier container with ephemeral disk would lose
its evidence on every redeploy, and that undercuts the one claim you most want to
make. If you want this after the finale, ask and I'll set it up with a persistent
volume properly.

---

## Two notes that matter on stage

**Use the campaign scenario, not the restart scenario, for the capability-lie
beat.** `Restart the payment service` trips *two* refusals at once — the
environment check (the tool is staging-only, the app runs in production) fires
before the mismatch check, so the headline reason on screen reads
*"tool not permitted in this environment"* rather than *"the application
understated what this action does."* Both are true and both are shown, but the
campaign case is the clean version of the story you want to tell.

**Look at the portfolio before you inject anything.** The grey light is only grey
until it-ops reports.
