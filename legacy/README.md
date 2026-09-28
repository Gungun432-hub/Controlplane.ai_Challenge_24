# Superseded scaffold — not the runtime

These modules are the pre-v2 build. They are kept only so the history of the
prototype is legible; **nothing here is imported by the running system** and
nothing here is maintained.

| File | Superseded by |
|---|---|
| `engine.py` | `python/controlplane/gate.py` + `plane.py` |
| `server.py` | `python/controlplane/api.py` |
| `seed.py` | `seed_history.py` |
| `fixtures.py` | `python/controlplane/org.py` |

Why they were replaced, specifically:

- `engine.py` annotated a latency budget but never enforced it: it waited on
  every detector future with no timeout, and priced demoted signals as if they
  had returned cleanly. A crashed detector returned `score=0.0`, which is
  indistinguishable from a clean check.
- `server.py` accepted `blastRadius` from the caller. Blast radius is the whole
  of the idea; if its input can be forged the idea is decorative. In v2 it is
  derived from the tool binding.
