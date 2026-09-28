"""The two things the finale build added for the people reading the screen.

1. **Plain English.** Our team lead's correction, verbatim: *"the answer or
   evaluation in the user AI with the answer from the controlplane has to be in
   simpler language so the users can also understand."* The wording lives in
   Python, not in a page's JavaScript, because three surfaces render a verdict
   and when each wrote its own they drifted.
2. **The two supervisors.** Our mentor asked where the supervisory agents are in
   our architecture and who wins when they disagree. Both were already here and
   neither was named.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from python.controlplane.plain import verdict                       # noqa: E402
from python.controlplane.supervisors import (ARBITRATION, CHARTERS,  # noqa: E402
                                             COST, SAFETY, charters, review)

JARGON = ("risk price", "detector", "parametric", "tier", "grounding",
          "abstention", "adjudication", "threshold", "blast radius", "score")


def _all_text(v: dict) -> str:
    return " ".join([v["headline"], *v["because"], v["doThis"]]).lower()


class TestThePersonCanReadIt:

    def test_no_jargon_reaches_the_person(self):
        cases = [
            {"status": "refused_harmful", "harm": {"family": "abuse"}},
            {"status": "redirected", "scope": {"reason": "this assistant holds "
                                               "refund policy, not fund performance"}},
            {"status": "budget_exhausted",
             "spend": {"name": "Finance", "usedInr": 41600, "budgetInr": 40000}},
            {"status": "capacity_exhausted", "capacity": {"name": "Marketing"}},
            {"status": "held", "ingress": {"reasons": ["a card number was pasted"]}},
            {"status": "answered", "decision": {"action": "pass"},
             "verification": {"sourcesCited": 3}},
            {"status": "answered", "decision": {"action": "escalate"},
             "verification": {"status": "unverified"}},
        ]
        for record in cases:
            text = _all_text(verdict(record))
            leaked = [w for w in JARGON if w in text]
            assert not leaked, f"{leaked} leaked into: {text}"

    def test_it_never_says_no_sources_when_sources_were_ignored(self):
        """Two different failures, and calling both "no sources" was untrue."""
        ignored = verdict({"status": "answered",
                           "decision": {"action": "escalate"},
                           "verification": {"status": "partly_verified",
                                            "sourcesCited": 0},
                           "retrieval": {"chunkIds": ["a", "b", "c", "d", "e", "f"]}})
        text = " ".join(ignored["because"])
        assert "6 relevant passages" in text
        assert "does not point at any of them" in text

    def test_it_never_says_the_figures_check_out_unless_they_were_checked(self):
        """The page once printed "we checked the figures against it" directly
        above "nothing here is settled by anything we hold"."""
        unchecked = verdict({"status": "answered",
                             "decision": {"action": "escalate"},
                             "verification": {"status": "unverified",
                                              "sourcesCited": 1},
                             "retrieval": {"chunkIds": ["a"]}})
        text = " ".join(unchecked["because"]).lower()
        assert "check out" not in text

    def test_a_decline_is_reported_as_the_system_working(self):
        v = verdict({"status": "answered",
                     "decision": {"action": "pass", "abstention": True}})
        assert "could not answer" in v["headline"]
        assert "not a failure" in " ".join(v["because"])

    def test_the_car_wash_verdict_names_the_thing_the_person_lost(self):
        v = verdict({
            "status": "answered",
            "decision": {"action": "escalate",
                         "detail": {"floor": "objective_unserved"}},
            "detectors": [{"detectorId": "purpose", "status": "ok", "detail": {
                "plainEnglish": "You asked about “car wash station” and the answer "
                                "never comes back to it."}}]})
        assert "car wash station" in " ".join(v["because"])
        assert v["doThis"]

    def test_confidently_wrong_is_explained_not_labelled(self):
        v = verdict({
            "status": "answered",
            "decision": {"action": "escalate",
                         "detail": {"floor": "confidently_wrong"}},
            "detectors": [{"detectorId": "certainty", "status": "ok", "detail": {
                "confidentlyWrong": True,
                "overbought": [{"text": "Your refund will definitely be there "
                                        "by Friday."}]}}]})
        assert "more certain than the evidence" in v["headline"]
        assert "definitely" in " ".join(v["because"])

    def test_every_verdict_has_a_headline_and_at_least_one_reason(self):
        for status in ("refused_harmful", "redirected", "budget_exhausted",
                       "capacity_exhausted", "held", "blocked"):
            v = verdict({"status": status})
            assert v["headline"] and v["because"], status


class TestTheTwoSupervisors:

    def test_neither_supervisor_can_do_the_other_one_s_job(self):
        cost, safety = CHARTERS[COST], CHARTERS[SAFETY]
        assert not set(cost.detectors) & set(safety.detectors)
        # the rule that matters most, stated in the charter itself
        assert any("release" in x for x in cost.may_not)
        assert any("budget" in x for x in safety.may_not)

    def test_safety_is_never_overridden_by_cost(self):
        record = {"status": "answered",
                  "decision": {"action": "escalate",
                               "reason": "held above the pass line",
                               "detail": {"floor": "omitted_condition"}},
                  "detectors": [{"detectorId": "cost", "status": "ok", "score": 0.8,
                                 "evidence": ["24x the median for this task class"]},
                                {"detectorId": "grounding", "status": "ok",
                                 "score": 0.6, "evidence": ["1 claim unsourced"]}]}
        out = review(record)
        assert out["decidedBy"] == SAFETY
        assert out["rule"] == "safety_not_overridden_by_cost"
        assert out["costControl"] and out["safetyRisk"]

    def test_a_budget_refusal_is_cost_s_and_reports_earliest(self):
        out = review({"status": "budget_exhausted"})
        assert out["decidedBy"] == COST
        assert out["rule"] == "earliest_stop_wins"
        assert out["costControl"][0]["stopped"] is True

    def test_a_pre_model_harm_refusal_names_both(self):
        """The judgement is Safety's; the position — before a rupee is spent —
        is Cost's contribution. Attributing it to one would be tidier and less
        true."""
        out = review({"status": "refused_harmful", "harm": {"family": "stereotype"}})
        assert out["decidedBy"] == SAFETY
        assert out["costControl"] and out["safetyRisk"]
        assert "zero tokens" in out["costControl"][0]["detail"]

    def test_a_clean_pass_says_no_supervisor_intervened(self):
        out = review({"status": "answered", "decision": {"action": "pass"},
                      "detectors": []})
        assert out["decidedBy"] == "no supervisor intervened"

    def test_the_page_and_the_code_read_the_same_charters(self):
        served = charters()
        assert [s["id"] for s in served["supervisors"]] == [COST, SAFETY]
        assert len(served["arbitration"]) == len(ARBITRATION) == 3
        for rule in served["arbitration"]:
            assert rule["rule"] and rule["why"]

    def test_every_registered_detector_belongs_to_exactly_one_supervisor(self):
        """A detector nobody owns is a finding nobody is accountable for."""
        from python.controlplane.detectors import DETECTORS
        owned = set(CHARTERS[COST].detectors) | set(CHARTERS[SAFETY].detectors)
        unowned = set(DETECTORS) - owned
        assert not unowned, f"no supervisor owns: {sorted(unowned)}"
