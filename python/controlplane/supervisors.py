"""The two supervisors, named — bridging the architecture we were asked about.

Our mentor's picture of a governed agent system had **two supervisory agents**
sitting over the workers: one watching what the work costs, one watching whether
it is safe to release. His question to us was not "did you build that" but
"where is it in yours, and who wins when they disagree".

The honest answer is that we already had both, and had never named them. The
budget gate, the admission control and the token accounting are one supervisor.
The detectors, the evidence floor, the judge and the release gate are another.
They run at different points, they answer to different people, and they resolve
conflicts by a rule that has been in the code since the first build. Naming them
does not add a layer — it makes an architecture we can already defend visible on
a receipt, which is the part that was missing.

What we are **not** claiming, and will say first if asked:

* These are not autonomous LLM agents. They are deterministic supervisors with
  written charters. A supervisor whose judgement is itself a model call is a
  supervisor that can be talked out of its job — and the one model-based check we
  do run, the adjudicator, is explicitly advisory and cannot lift a gate.
* There is no negotiation between them. Arbitration is a fixed rule, not a
  conversation, because a conversation is a thing an attacker can join.

The charters
------------
**Cost & Capacity Control** answers to the budget holder. Its jurisdiction ends
at the moment the model is called: it decides whether a question is worth
starting, never whether an answer is fit to release. It can refuse work, and it
can make work more expensive by demanding review — it cannot make an unsafe
answer cheaper by waving it through.

**Safety & Risk** answers to the system's owner and, through them, to whoever
carries the regulatory exposure. Its jurisdiction begins when an answer exists.
It can hold, edit, escalate or withhold — and it cannot spend a rupee, because a
supervisor that can authorise its own spending is not a control.

Arbitration
-----------
Three rules, in order, and each one exists because the alternative is a headline:

1. **Safety is never overridden by cost.** A finding stands whatever the budget
   says. "We released it because review was expensive" is the sentence this rule
   exists to make impossible.
2. **Cost may only ever subtract work, never add release.** It can stop a
   question before the model. It can never turn a hold into a pass.
3. **When both would stop the work, cost stops it first**, because stopping
   earlier is cheaper and the person gets a truer reason: *"this department is
   out of budget"* is more useful than *"your answer was flagged"* when the
   question was never going to be asked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COST = "cost_control"
SAFETY = "safety_risk"


@dataclass(frozen=True)
class Charter:
    id: str
    name: str
    answers_to: str
    jurisdiction: str
    may: tuple[str, ...]
    may_not: tuple[str, ...]
    #: detector ids this supervisor reads. Everything else is not its business.
    detectors: tuple[str, ...] = ()
    #: gates it owns that never involve a detector at all.
    gates: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "answersTo": self.answers_to,
                "jurisdiction": self.jurisdiction, "may": list(self.may),
                "mayNot": list(self.may_not), "detectors": list(self.detectors),
                "gates": list(self.gates)}


CHARTERS: dict[str, Charter] = {
    COST: Charter(
        COST, "Cost & Capacity Control",
        answers_to="the budget holder for the system",
        jurisdiction="everything before the model is called",
        may=("refuse a question when the department is out of money or reviewer time",
             "reserve reviewer capacity before work starts, atomically",
             "price the token and oversight cost of every decision",
             "warn an owner that a budget will not last the period"),
        may_not=("release an answer another supervisor flagged",
                 "lower a threshold, lift a gate or waive the evidence floor",
                 "see the answer at all — its jurisdiction ends before there is one"),
        detectors=("cost",),
        gates=("monthly spend cap", "weekly reviewer capacity", "atomic admission")),
    SAFETY: Charter(
        SAFETY, "Safety & Risk",
        answers_to="the system's owner, and whoever carries the regulatory exposure",
        jurisdiction="everything from the moment an answer exists",
        may=("hold, edit, escalate or withhold an answer",
             "require a second opinion and fail closed without one",
             "refuse an irreversible action on weak evidence at any price",
             "demand a human reviewer, and so spend the budget holder's money"),
        may_not=("authorise spending on its own behalf",
                 "be overruled by a budget",
                 "act on the world — it governs proposals, it does not execute"),
        detectors=("grounding", "privacy", "fairness", "purpose", "certainty",
                   "toxicity", "abstention", "adjudication", "citation"),
        gates=("harm gate (runs pre-model)", "organisation blocklist (pre-model)",
               "evidence floor", "capability ceiling", "omitted condition",
               "objective unserved", "confidently wrong", "release gate")),
}

# The three arbitration rules, as data, so the page and the receipt quote the
# same text the code enforces.
ARBITRATION = (
    ("safety_not_overridden_by_cost",
     "A safety finding stands whatever the budget says.",
     "“We released it because review was expensive” is the sentence this "
     "rule exists to make impossible."),
    ("cost_may_only_subtract",
     "Cost may stop work before the model. It can never turn a hold into a pass.",
     "A supervisor that can wave things through is not a control."),
    ("earliest_stop_wins",
     "When both would stop the work, the earlier one reports.",
     "“This department is out of budget” is a truer reason than “your "
     "answer was flagged” for a question that was never going to be asked."),
)


@dataclass
class Finding:
    supervisor: str
    source: str
    detail: str
    stopped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"supervisor": self.supervisor, "source": self.source,
                "detail": self.detail[:220], "stopped": self.stopped}


@dataclass
class Review:
    findings: list[Finding] = field(default_factory=list)
    decided_by: str = ""
    rule: str = ""

    def of(self, supervisor: str) -> list[Finding]:
        return [f for f in self.findings if f.supervisor == supervisor]

    def as_dict(self) -> dict[str, Any]:
        return {"decidedBy": self.decided_by, "rule": self.rule,
                "costControl": [f.as_dict() for f in self.of(COST)],
                "safetyRisk": [f.as_dict() for f in self.of(SAFETY)]}


def review(record: dict[str, Any]) -> dict[str, Any]:
    """Who saw what, who decided, and under which rule.

    Reads the decision that was already taken — it does not take one. Putting the
    arbitration *after* the fact would be dishonest if the two supervisors were
    really negotiating; they are not, so this is a faithful attribution of a
    decision the gate had already made deterministically."""
    result = Review()
    status = record.get("status") or ""
    decision = record.get("decision") or {}
    action = decision.get("action") or ""

    # ---- what cost control saw ----------------------------------------
    if status in ("budget_exhausted", "capacity_exhausted"):
        which = ("the monthly spend cap" if status == "budget_exhausted"
                 else "this week's reviewer capacity")
        result.findings.append(Finding(
            COST, which, "the department is out; the question was refused before "
                         "the model, so nothing was generated and nothing was spent",
            stopped=True))
        result.decided_by = COST
        result.rule = "earliest_stop_wins"
        return result.as_dict()

    if status == "refused_harmful":
        family = (record.get("harm") or {}).get("family") or "harm"
        # The harm gate runs before the model and spends nothing, so it is cost
        # control's gate by position — but it is safety's judgement. Both are
        # recorded, because pretending otherwise would be tidier and less true.
        result.findings.append(Finding(
            COST, "pre-model refusal", f"stopped at the door on '{family}'; zero "
                                       f"tokens, zero rupees", stopped=True))
        result.findings.append(Finding(
            SAFETY, "harm gate", f"the request reads as '{family}'", stopped=True))
        result.decided_by = SAFETY
        result.rule = "safety_not_overridden_by_cost"
        return result.as_dict()

    for detector in record.get("detectors") or []:
        if detector.get("status") not in ("ok", "completed", "completed_async"):
            continue
        name = detector.get("detectorId") or ""
        score = float(detector.get("score") or 0.0)
        if score <= 0.0:
            continue
        evidence = (detector.get("evidence") or [""])[0]
        if name in CHARTERS[COST].detectors:
            result.findings.append(Finding(COST, name, evidence))
        elif name in CHARTERS[SAFETY].detectors:
            result.findings.append(Finding(SAFETY, name, evidence))

    floor = (decision.get("detail") or {}).get("floor")
    if floor:
        result.findings.append(Finding(
            SAFETY, f"floor: {floor}",
            decision.get("reason") or "", stopped=action in ("block", "escalate")))

    # ---- who decided ---------------------------------------------------
    if action in ("block", "escalate", "repair"):
        result.decided_by = SAFETY
        result.rule = ("safety_not_overridden_by_cost" if result.of(COST)
                       else "cost_may_only_subtract")
    elif action:
        result.decided_by = "no supervisor intervened"
        result.rule = "cost_may_only_subtract"
    return result.as_dict()


def charters() -> dict[str, Any]:
    """Everything the developer page needs to render this, from one place."""
    return {"supervisors": [CHARTERS[COST].as_dict(), CHARTERS[SAFETY].as_dict()],
            "arbitration": [{"id": i, "rule": r, "why": w} for i, r, w in ARBITRATION]}
