"""Pre-load the plane with ambient traffic so the console has a history.

The history spans **days**, not minutes. A burn-rate forecast — "at this rate you
exhaust the budget on Thursday" — is only honest if there is a real observation
window behind it, and extrapolating a month from forty minutes of traffic would
be exactly the kind of invented number this product exists to stop.

Traffic is weighted towards the present so the live stream still reads as live.
"""
import datetime as _dt
import random

# How far back the synthetic backdrop reaches. Long enough for a spend trend to
# mean something, short enough that a month's budget is not obviously spent.
WINDOW_DAYS = 14.0


def seed(cp, turns: int = 90, seed: int = 7) -> int:
    from python.controlplane.org import AMBIENT
    rng = random.Random(seed)
    now = _dt.datetime.now(_dt.timezone.utc)

    # The most recent stretch round-robins over every reporting system, so a
    # system reads as silent only when it genuinely is. With purely random
    # selection a system could go quiet by luck, and "no signal" would stop
    # meaning anything.
    reporting = [x for x in AMBIENT if x[0] != "it-ops-agent"]
    systems = sorted({x[0] for x in reporting})
    tail = max(len(systems) * 2, min(12, turns // 4))

    for i in range(turns):
        if i >= turns - tail:
            want = systems[(turns - 1 - i) % len(systems)]
            options = [x for x in reporting if x[0] == want] or reporting
            system_id, message = rng.choice(options)
        else:
            system_id, message = rng.choice(AMBIENT)

        # Quadratic weighting: most traffic is recent, but the tail reaches back
        # far enough to compute a rate from. i = 0 is the oldest turn.
        share = 1.0 - (i / max(1, turns - 1))          # 1.0 → 0.0
        age_days = WINDOW_DAYS * (share ** 2)
        age_days += rng.uniform(-0.12, 0.12)           # jitter, so it is not a curve
        age_days = max(0.0008, age_days)               # never in the future

        if system_id == "it-ops-agent":
            # This system stopped reporting four hours ago. "No signal" is then
            # derived from evidence rather than asserted by the seeder, and the
            # same conclusion survives a restart.
            age_days += 4 / 24

        # Decide the time BEFORE the turn, so the ledger entry and the
        # projection can never disagree about when something happened.
        at = (now - _dt.timedelta(days=age_days)).isoformat().replace("+00:00", "Z")
        try:
            cp.turn(system_id, message, at=at, origin="seed")
        except Exception:                                            # noqa: BLE001
            continue

    return len(cp.decisions)
