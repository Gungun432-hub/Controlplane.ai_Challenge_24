"""Graded routing.

Four outcomes, not two. The reason for the gradation is operational rather than
theoretical: a checker that can only allow or block gets switched off, because
blocking a customer-facing assistant is more disruptive than the failure it is
preventing in the overwhelming majority of cases.

    PASS      release untouched, verify asynchronously by sampling
    REPAIR    deterministic inline fix, user is never made to wait for a human
    ESCALATE  release with uncertainty surfaced, human verifies in parallel
    BLOCK     withhold - reserved for irreversible actions and hard gates

The one asymmetry worth naming: BLOCK is available only where the action is
irreversible or the policy declares a hard gate. Everywhere else the worst
outcome is ESCALATE, because withholding an answer has a cost too and it is
usually paid by the wrong person.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import Policy
from .detectors import pii as pii_det
from .detectors.base import PRIVACY, Signal
from .scoring import RiskPrice, is_unverifiable

PASS, REPAIR, ESCALATE, BLOCK = "pass", "repair", "escalate", "block"

# Actions that cannot be undone once taken.
IRREVERSIBLE = {"execute", "decide"}


@dataclass
class Decision:
    action: str
    reason: str
    released_text: str
    repairs: list[str] = field(default_factory=list)
    surfaced_uncertainty: str | None = None
    abstained: bool = False
    review_queue: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "repairs": self.repairs,
            "surfaced_uncertainty": self.surfaced_uncertainty,
            "abstained": self.abstained,
            "review_queue": self.review_queue,
            "detail": self.detail,
        }


def _apply_repairs(text: str, signals: list[Signal], policy: Policy,
                   sources: list[str]) -> tuple[str, list[str]]:
    applied: list[str] = []
    out = text

    if "redact_pii" in policy.repair_actions:
        findings = pii_det.scan(out)
        if findings:
            out = pii_det.redact(out, findings)
            applied.append(f"redact_pii({len(findings)})")

    if "attach_citation" in policy.repair_actions and sources:
        g = next((s for s in signals if s.name == "grounding"), None)
        if g and (g.detail.get("grounded_fraction") or 0) >= 0.5:
            out += f"\n\n[Sources: {len(sources)} document(s) retrieved for this answer]"
            applied.append("attach_citation")

    if "soften_overclaim" in policy.repair_actions:
        replacements = [
            ("is guaranteed", "is not guaranteed and is subject to terms"),
            ("guaranteed return", "target return (not guaranteed)"),
            ("will definitely", "is expected to"),
            ("always", "in most cases"),
        ]
        for a, b in replacements:
            if a in out.lower():
                idx = out.lower().index(a)
                out = out[:idx] + b + out[idx + len(a):]
                applied.append(f"soften_overclaim('{a}')")
    return out, applied


def route(text: str, signals: list[Signal], rp: RiskPrice, policy: Policy,
          action_class: str, sources: list[str]) -> Decision:
    th = policy.thresholds
    unverifiable = is_unverifiable(signals)
    hard_gate = action_class in policy.hard_gate_action_classes

    # --- hard gate: an irreversible action that cannot be evidenced -----------
    if hard_gate and (unverifiable or rp.price >= th["escalate"]):
        return Decision(
            BLOCK,
            reason=("policy declares a hard gate on '%s' actions and the response is "
                    "%s" % (action_class,
                            "unverifiable" if unverifiable else f"priced at {rp.price}")),
            released_text="",
            review_queue=policy.d.get("review_queue"),
            detail={"hard_gate": True, "action_class": action_class},
        )

    # --- contradiction floor ---------------------------------------------------
    # A numeric claim that contradicts the source of record is not a probability
    # judgement, it is a fact about the text. Blast radius decides how much a
    # *probable* failure is worth spending on; it must not be able to wave
    # through a demonstrated one. So a contradiction can never route to PASS,
    # however low-stakes the surface looks.
    contradiction = any(s.detail.get("contradiction") for s in signals)

    # --- clean pass -----------------------------------------------------------
    if rp.price < th["pass"] and not unverifiable and not contradiction:
        return Decision(PASS, f"risk price {rp.price} is below the pass threshold {th['pass']}", text)

    if contradiction and rp.price < th["escalate"]:
        repaired, applied = _apply_repairs(text, signals, policy, sources)
        note = ("At least one figure in this answer does not appear in any retrieved "
                "source or in your question. Treat those figures as unconfirmed.")
        return Decision(
            ESCALATE,
            reason="numeric claim contradicts the source of record; contradictions "
                   "cannot pass regardless of risk price",
            released_text=repaired if applied else text, repairs=applied,
            surfaced_uncertainty=note, review_queue=policy.d.get("review_queue"),
            detail={"price": rp.price, "floor": "contradiction", "band": list(rp.band)},
        )

    # --- deterministic repair -------------------------------------------------
    privacy_only = (
        rp.dominant == "pii"
        or (PRIVACY in rp.labels and rp.price < th["escalate"])
    )
    if privacy_only and rp.price < th["escalate"]:
        repaired, applied = _apply_repairs(text, signals, policy, sources)
        if applied:
            return Decision(
                REPAIR,
                reason="failure has a known deterministic fix, so the answer is repaired "
                       "inline rather than withheld",
                released_text=repaired, repairs=applied,
                detail={"price": rp.price},
            )

    if th["pass"] <= rp.price < th["escalate"] and not unverifiable:
        # A price above the pass line with no named finding means the detectors
        # are uneasy but cannot say why. There is nothing to tell the user and
        # nothing to fix, so we release and let the asynchronous sampler decide
        # whether this was worth learning from. Manufacturing a visible
        # intervention here would be pure alert fatigue.
        if not rp.labels:
            return Decision(PASS, f"risk price {rp.price} above the pass line but no named "
                                  f"finding to act on; released and sampled asynchronously", text)
        repaired, applied = _apply_repairs(text, signals, policy, sources)
        if applied:
            return Decision(REPAIR, "repairable findings resolved inline",
                            repaired, repairs=applied, detail={"price": rp.price})

    # --- block, only where the action is irreversible --------------------------
    if rp.price >= th["escalate"] and action_class in IRREVERSIBLE and rp.price >= th["escalate"] + 15:
        return Decision(
            BLOCK,
            reason=f"risk price {rp.price} on an irreversible '{action_class}' action",
            released_text="", review_queue=policy.d.get("review_queue"),
            detail={"irreversible": True},
        )

    # --- escalate, releasing the answer with its uncertainty visible -----------
    if unverifiable:
        note = ("No source material covers part of this answer, so it could not be "
                "verified either way. Treat the unsupported parts as unconfirmed.")
        return Decision(
            ESCALATE, "response contains unverifiable claims; abstaining from a support judgement",
            text, surfaced_uncertainty=note, abstained=True,
            review_queue=policy.d.get("review_queue"),
            detail={"price": rp.price, "band": list(rp.band)},
        )

    note = (f"Confidence is limited on this answer (risk price {rp.price}, "
            f"band {rp.band[0]}-{rp.band[1]}). A reviewer has been notified.")
    return Decision(
        ESCALATE, f"risk price {rp.price} at or above the escalate threshold {th['escalate']}",
        text, surfaced_uncertainty=note, review_queue=policy.d.get("review_queue"),
        detail={"price": rp.price, "band": list(rp.band), "dominant": rp.dominant},
    )
