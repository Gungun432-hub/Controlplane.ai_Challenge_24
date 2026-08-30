"""Risk pricing.

    risk_price = P(failure) x blast_radius x 100

P(failure) is estimated from the detector signals. Blast radius comes from
deployment context - who is asking and what the answer does next - and never
from the content of the answer itself.

Two design choices worth stating explicitly:

1. Signals compound but do not simply add. A dominant signal sets the floor, and
   remaining signals raise the price through a noisy-OR term at half weight.
   This is how the overlap case behaves sensibly: a fabricated claim about a
   named person raises both `grounding` and `privacy`, and the combined price is
   higher than either alone without double-counting one underlying finding.

2. Every price carries a confidence band derived from detector confidence. The
   system never reports a score without saying how much it trusts it. A wide
   band is itself routable: an uncertain low price is not the same as a
   confident low price.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .detectors.base import UNVERIFIABLE, Signal

# What the answer does downstream. This is the entire blast-radius model.
ACTION_RADIUS = {
    "read": 0.10,      # read-only lookup, nobody acts on it directly
    "draft": 0.35,     # drafts something a human will review
    "advise": 0.70,    # customer-facing advice, relied upon
    "decide": 0.90,    # produces a decision about a person
    "execute": 1.00,   # takes an action that cannot be undone
}

AUDIENCE_MULT = {"internal": 1.0, "external": 1.15}


@dataclass
class RiskPrice:
    price: int
    p_failure: float
    blast_radius: float
    confidence: float
    band: tuple[int, int]
    dominant: str
    labels: list[str] = field(default_factory=list)
    contributions: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "price": self.price,
            "p_failure": round(self.p_failure, 4),
            "blast_radius": round(self.blast_radius, 3),
            "confidence": round(self.confidence, 3),
            "band": list(self.band),
            "dominant": self.dominant,
            "labels": self.labels,
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
        }


def blast_radius(action_class: str, audience: str, regulated: bool) -> float:
    r = ACTION_RADIUS.get(action_class, ACTION_RADIUS["draft"])
    r *= AUDIENCE_MULT.get(audience, 1.0)
    if regulated:
        r *= 1.2
    return float(min(1.0, r))


def price(signals: list[Signal], weights: dict[str, float], action_class: str,
          audience: str, regulated: bool, session_risk: float = 0.0) -> RiskPrice:
    contributions: dict[str, float] = {}
    labels: list[str] = []

    for s in signals:
        w = float(weights.get(s.name, 1.0))
        adjusted = min(1.0, s.score * w)
        contributions[s.name] = adjusted
        for lab in s.labels:
            if lab not in labels:
                labels.append(lab)

    if contributions:
        dominant_name = max(contributions, key=lambda k: contributions[k])
        dominant = contributions[dominant_name]
        others = [v for k, v in contributions.items() if k != dominant_name]
    else:
        dominant_name, dominant, others = "none", 0.0, []

    residual = 1.0
    for v in others:
        residual *= (1.0 - v)
    residual = 1.0 - residual

    p_failure = dominant + (1.0 - dominant) * 0.5 * residual

    # A session that has already accumulated risk raises the floor for later
    # turns. Multi-turn risk compounds; single-turn scoring alone misses it.
    if session_risk > 0:
        p_failure = p_failure + (1.0 - p_failure) * min(0.4, session_risk * 0.4)

    br = blast_radius(action_class, audience, regulated)
    raw = p_failure * br
    price_val = int(round(min(100.0, raw * 100)))

    confs = [s.confidence for s in signals] or [0.3]
    confidence = float(sum(confs) / len(confs))
    # Lower confidence widens the band symmetrically around the point estimate.
    half = int(round((1.0 - confidence) * 22))
    band = (max(0, price_val - half), min(100, price_val + half))

    return RiskPrice(price_val, p_failure, br, confidence, band, dominant_name, labels, contributions)


def is_unverifiable(signals: list[Signal]) -> bool:
    return any(UNVERIFIABLE in s.labels for s in signals)
