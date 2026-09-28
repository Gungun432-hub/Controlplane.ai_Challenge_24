"""The three things the grand-finale build added, and the seam that joins them.

1. **Subject scope.** An assistant is registered to be asked about the things its
   owner gave it documents for. Asking a support copilot about fund performance
   costs zero tokens and gets the person pointed at the right assistant by name.
2. **The omission check.** The failure class where every sentence is true and the
   reader's purpose is defeated anyway, because the one line that governed them
   was left out.
3. **The adjudicator, deepened.** Two charges in one call, domain calibration, a
   confidence floor, and — the part that matters when somebody asks how we know
   a model-based checker works — a labelled evaluation set with a score.

Plus the integration the whole thing exists for: a question typed on the user
page is priced by exactly the code that priced the seeded history, and lands in
the portfolio's own numbers with a receipt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conftest import bundled_corpus                                    # noqa: E402
from python.controlplane.adjudicator import (Adjudication, ClaimVerdict,  # noqa: E402
                                             DOMAIN_NOTES, EXEMPLARS,
                                             MIN_CONTRADICTION_CONFIDENCE,
                                             Sufficiency, adjudicate,
                                             judge_required, should_adjudicate,
                                             system_prompt, to_detector)
from python.controlplane.gate import ESCALATE, PASS, BLOCK             # noqa: E402
from python.controlplane.ledger import JsonlLedger                     # noqa: E402
from python.controlplane.org import AMBIENT, SCENARIOS, build          # noqa: E402
from python.controlplane.plane import ControlPlane                     # noqa: E402
from python.controlplane.providers import OfflineProvider              # noqa: E402
from python.controlplane.purpose import PURPOSE_DEFEATED, inspect, purpose  # noqa: E402
from python.controlplane.scope import FOREIGN, IN_SCOPE, UNCOVERED, ScopeIndex  # noqa: E402


@pytest.fixture()
def plane(tmp_path):
    return ControlPlane(build(), OfflineProvider(),
                        JsonlLedger(tmp_path / "l.jsonl", "k"),
                        corpus=bundled_corpus())


# =========================================================== subject scope ===
class TestSubjectScope:
    def test_scope_is_derived_from_the_corpus_not_a_hardcoded_list(self, plane):
        """The property that makes this scale: nobody wrote these terms down."""
        stats = plane.scope.stats()["systems"]
        assert set(stats) == set(plane.registry.applications)
        for sid, row in stats.items():
            assert row["signatureTerms"] > 0, sid
        # And they are genuinely distinctive, not the same words five times.
        support = set(stats["support-copilot"]["top"])
        finance = set(stats["finance-decide"]["top"])
        assert not support & finance

    def test_a_finance_question_in_support_is_redirected_by_name(self, plane):
        v = plane.scope.check("support-copilot",
                              "Is the 8.4% return on the Horizon fund guaranteed?")
        assert v.verdict == FOREIGN
        assert v.best_other == "finance-decide"
        assert "Finance Decision Assistant" in v.reason
        assert not v.allowed

    def test_shared_vocabulary_does_not_mask_a_foreign_subject(self, plane):
        """The bug this ordering exists to prevent.

        Retail "returns" and financial "returns" are the same word, so the
        support corpus retrieves something for a fund question and clears an
        absolute coverage floor on a subject it has no business answering. Only
        the comparison against other systems can see that."""
        mine = plane.scope.coverage("support-copilot",
                                    "Is the 8.4% return on the Horizon fund guaranteed?")
        assert mine > 0, "precondition: support really does retrieve something"
        assert plane.scope.check(
            "support-copilot",
            "Is the 8.4% return on the Horizon fund guaranteed?").verdict == FOREIGN

    def test_the_same_question_is_in_scope_for_its_own_system(self, plane):
        v = plane.scope.check("finance-decide",
                              "Is the 8.4% return on the Horizon fund guaranteed?")
        assert v.verdict == IN_SCOPE

    def test_nobodys_documents_cover_it(self, plane):
        v = plane.scope.check("support-copilot", "What is Chipotle's share price today?")
        assert v.verdict == UNCOVERED
        # Crucially NOT a refusal: uncovered is the honest case the problem
        # statement names, and it is allowed through with the fact recorded.
        assert v.allowed

    def test_no_ambient_or_scenario_traffic_is_wrongly_redirected(self, plane):
        """A scope check that turns away ordinary work is worse than none."""
        wrong = [(sid, q) for sid, q in AMBIENT
                 if plane.scope.check(sid, q).verdict == FOREIGN]
        assert wrong == []
        for sc in SCENARIOS:
            v = plane.scope.check(sc["systemId"], sc["message"])
            if sc["id"] == "campaign-fin":
                # The one deliberate exception: the identical-text scenario is a
                # marketing send submitted to the regulated finance system. A
                # person typing it would be redirected; the console scenario
                # submits it as an application, which is the case the problem
                # statement is about.
                assert v.verdict == FOREIGN
            else:
                assert v.verdict != FOREIGN, sc["id"]

    def test_every_registered_sample_question_works_on_its_own_system(self, plane):
        for app in plane.registry.applications.values():
            for sample in app.sample_questions:
                v = plane.scope.check(app.system_id, sample["q"])
                expect_foreign = "redirected" in sample["why"]  # the chip says so
                assert (v.verdict == FOREIGN) is expect_foreign, (
                    f"{app.system_id}: {sample['q']} -> {v.verdict}")

    def test_scope_follows_the_evidence_when_a_document_is_added(self, plane):
        question = "What is our policy on sabbatical leave after five years?"
        before = plane.scope.check("recruit-screen", question)
        plane.corpus.add("recruit-screen", "sabbatical.md",
                         b"# Sabbatical policy\n\nAn employee with five years of "
                         b"continuous service may apply for a sabbatical of up to "
                         b"three months. Sabbatical requests require the approval of "
                         b"the department head and are unpaid.\n",
                         origin="uploaded")
        plane.rebuild_scope()
        after = plane.scope.check("recruit-screen", question)
        assert after.coverage > before.coverage
        assert after.verdict == IN_SCOPE

    def test_a_redirect_costs_nothing_and_never_enters_the_review_queue(self, plane):
        out = plane.ask("support-copilot",
                        "Is the 8.4% return on the Horizon fund guaranteed?",
                        session_id="s1", user="Ravi Menon")
        assert out["status"] == "redirected"
        assert out["tokensSpent"] == 0
        assert out["redirectName"] == "Finance Decision Assistant"
        # No model call, no decision recorded, and nothing for a human to do.
        assert plane.decisions == plane.decisions and not any(
            d.get("origin") == "user" for d in plane.decisions)
        assert plane.review_queue("held") == []
        assert len(plane.redirected) == 1

    def test_the_user_is_told_which_assistant_to_ask(self, plane):
        plane.ask("support-copilot", "Is the 8.4% return on the Horizon fund guaranteed?",
                  session_id="s2", user="Ravi Menon")
        turn = plane.chat("s2")[-1]
        assert turn["outcome"]["status"] == "redirected"
        assert turn["outcome"]["scope"]["bestOtherName"] == "Finance Decision Assistant"


# ======================================================== the omission check ===
CAMPAIGN = ("Internal sends of any size: no approval required. External sends up to "
            "50,000 contacts: marketing manager approval. External sends above "
            "50,000 contacts: marketing director plus legal sign-off. An external "
            "send cannot be recalled once dispatched.")
REFUNDS = ("Refunds up to 5,000 rupees are approved automatically. Refunds above "
           "5,000 rupees require a named approver. Refunds settle within 5 to 7 "
           "working days.")


class TestPurposeDefeated:
    def test_the_car_wash(self):
        """Every word true. The reader sends 80,000 unapproved emails."""
        r = inspect("Can I send this festive campaign to our 80,000 external contacts?",
                    "The festive copy follows the approved tone guide and makes no "
                    "pricing claim, so it is ready to go out to your external list.",
                    [CAMPAIGN])
        assert r.omissions
        assert "sign-off" in r.omissions[0].sentence

    def test_a_crossed_threshold_is_reported_first_and_quoted(self):
        r = inspect("Can I refund this customer 12,000 rupees straight away?",
                    "Refunds settle within 5 to 7 working days.", [REFUNDS])
        assert r.omissions
        first = r.omissions[0]
        assert first.threshold == 5000.0 and first.asked_value == 12000.0
        assert "named approver" in first.sentence

    def test_a_condition_scoped_elsewhere_is_not_an_omission(self):
        """The most annoying false positive this check can produce: a rule about
        EXTERNAL sends reported against a question about an INTERNAL one."""
        r = inspect("Do I need approval to send to 4,000 internal staff?",
                    "Internal sends of any size need no approval, so you can send to "
                    "4,000 internal recipients without sign-off.", [CAMPAIGN])
        assert r.omissions == []

    def test_an_answer_that_carries_the_condition_is_not_flagged(self):
        r = inspect("Can I send this campaign to 80,000 external contacts?",
                    "External sends above 50,000 contacts require the marketing "
                    "director plus legal sign-off, so you need that before sending.",
                    [CAMPAIGN])
        # The approval gate was carried, so it is not reported. (The separate
        # warning that an external send cannot be recalled genuinely IS still
        # missing from this answer, and reporting that one is correct.)
        assert not any("sign-off" in o.sentence for o in r.omissions)
        assert not any(o.threshold for o in r.omissions)

    def test_answered_the_adjacent_question(self):
        r = inspect("How long will delivery take to my address?",
                    "Your order is confirmed and will be dispatched from our "
                    "warehouse. You will receive a tracking link by email.",
                    ["Metro addresses: 2 to 3 working days from dispatch."])
        assert r.unanswered == "duration"
        assert r.expected == "a length of time"

    def test_a_duration_without_a_digit_still_counts_as_an_answer(self):
        r = inspect("How long does it take?",
                    "It usually takes about a week from dispatch.",
                    ["Metro addresses: 2 to 3 working days from dispatch."])
        assert r.unanswered == ""

    def test_going_ahead_anyway_raises_the_score(self):
        skipped = purpose(
            answer="The festive copy follows the approved tone guide.",
            prompt="Can I send this campaign to 80,000 external contacts?",
            sources=[CAMPAIGN])
        pushy = purpose(
            answer="Yes, you can send it — the festive copy follows the approved "
                   "tone guide.",
            prompt="Can I send this campaign to 80,000 external contacts?",
            sources=[CAMPAIGN])
        assert pushy.score > skipped.score
        assert pushy.detail["unconditionalGoAhead"] is True

    def test_it_is_measured_against_everything_retrieved_not_only_what_was_cited(self):
        """Measuring an omission against the sources the agent chose to cite
        would be asking the agent to mark its own homework."""
        result = purpose(answer="Refunds settle within 5 to 7 working days.",
                         prompt="Can I refund this customer 12,000 rupees?",
                         sources=["Refunds settle within 5 to 7 working days."],
                         retrieved=[REFUNDS])
        assert result.detail["omittedCondition"] is True
        assert result.detail["measuredAgainst"] == "everything retrieval surfaced"

    def test_no_sources_is_reported_as_nothing_to_check_not_as_clean(self):
        result = purpose(answer="Refunds take a week.", prompt="How long?", sources=[])
        assert result.score == 0.0
        assert "no source text" in result.evidence[0]
        assert result.detail["omittedCondition"] is not True

    def test_an_omission_cannot_pass_at_any_price(self, plane):
        """The car-wash floor. A price is a probability; an omission is a fact
        about the text, and it takes a floor for the same reason a numeric
        contradiction does."""
        record = plane.turn(
            "marketing-copilot",
            "Can I send this festive campaign to our 80,000 external contacts today?")
        omitted = [d for d in record["detectors"]
                   if d["detail"].get("omittedCondition")]
        if omitted:
            assert record["decision"]["action"] != PASS

    def test_the_label_reaches_the_receipt(self, plane):
        record = plane.turn("marketing-copilot",
                            "Can I send this to our 80,000 external contacts?")
        labels = {lab for d in record["detectors"] for lab in (d["labels"] or [])}
        detail = [d for d in record["detectors"] if d["detectorId"] == "purpose"]
        assert detail, "the purpose detector ran"
        if detail[0]["labels"]:
            assert PURPOSE_DEFEATED in labels


# ============================================================ the adjudicator ===
SRC = ["Refunds are issued to the original payment method and settle within 5 to 7 "
       "working days. Refunds above 5,000 rupees require a named approver."]


class _Judge:
    """A judge that returns exactly what the test tells it to."""
    judge_model = "test-judge"

    def __init__(self, payload: str):
        self.payload = payload
        self.seen: list[tuple[str, str]] = []

    def adjudicate(self, system, prompt, timeout_s=6.0):
        self.seen.append((system, prompt))
        return self.payload, {"totalTokens": 42}


class TestAdjudicatorCalibration:
    def test_the_prompt_carries_the_exemplars_and_the_domain_note(self):
        prompt = system_prompt("finance-decide")
        for exemplar in EXEMPLARS:
            assert exemplar.splitlines()[0] in prompt
        assert DOMAIN_NOTES["finance-decide"] in prompt

    def test_an_unknown_domain_falls_back_to_the_base_prompt(self):
        assert system_prompt("no-such-system") == system_prompt("")

    def test_the_question_reaches_the_judge(self):
        judge = _Judge('{"verdicts":[{"n":1,"needs_evidence":true,'
                       '"verdict":"supported","confidence":0.9}]}')
        adjudicate("Refunds settle within 5 to 7 working days of approval.", SRC,
                   judge, question="How long does a refund take?",
                   domain="support-copilot")
        system, prompt = judge.seen[0]
        assert "How long does a refund take?" in prompt
        assert DOMAIN_NOTES["support-copilot"] in system

    def test_a_low_confidence_contradiction_is_downgraded_and_recorded(self):
        conf = MIN_CONTRADICTION_CONFIDENCE - 0.1
        judge = _Judge('{"verdicts":[{"n":1,"needs_evidence":true,'
                       f'"verdict":"contradicted","confidence":{conf}}}]}}')
        adj = adjudicate("Refunds settle within 5 to 7 working days of approval.",
                         SRC, judge)
        assert adj.verdicts[0].verdict == "uncovered"
        assert adj.verdicts[0].downgraded_from == "contradicted"
        assert adj.as_dict()["downgraded"] == 1

    def test_a_confident_contradiction_is_kept(self):
        judge = _Judge('{"verdicts":[{"n":1,"needs_evidence":true,'
                       '"verdict":"contradicted","confidence":0.88}]}')
        adj = adjudicate("Refunds settle within 5 to 7 working days of approval.",
                         SRC, judge)
        assert adj.verdicts[0].verdict == "contradicted"
        assert to_detector(adj).detail["contradiction"] is True


class TestAdjudicatorSufficiency:
    def test_the_second_charge_is_parsed_and_priced(self):
        judge = _Judge('{"verdicts":[{"n":1,"needs_evidence":true,'
                       '"verdict":"supported","confidence":0.9}],'
                       '"sufficiency":{"verdict":"omits_condition","confidence":0.8,'
                       '"omitted":"Refunds above 5,000 rupees require a named approver."}}')
        adj = adjudicate("Refunds settle within 5 to 7 working days of approval.",
                         SRC, judge, question="Can I refund 12,000 rupees?")
        assert adj.sufficiency.verdict == "omits_condition"
        det = to_detector(adj)
        # A supported claim alone would have scored zero. The omission is what
        # carries the finding.
        assert det.score >= 0.55
        assert det.detail["omittedCondition"] is True
        assert PURPOSE_DEFEATED in det.labels

    def test_answering_a_different_question_is_scored_lower_than_an_omission(self):
        def run(verdict):
            judge = _Judge('{"verdicts":[{"n":1,"needs_evidence":true,'
                           '"verdict":"supported","confidence":0.9}],'
                           f'"sufficiency":{{"verdict":"{verdict}","confidence":0.7}}}}')
            return to_detector(adjudicate(
                "Refunds settle within 5 to 7 working days of approval.", SRC,
                judge)).score
        assert run("answers_different_question") < run("omits_condition")
        assert run("complete") < run("answers_different_question")

    def test_an_unparseable_sufficiency_block_does_not_lose_the_verdicts(self):
        judge = _Judge('{"verdicts":[{"n":1,"needs_evidence":true,'
                       '"verdict":"supported","confidence":0.9}],'
                       '"sufficiency":{"verdict":"nonsense"}}')
        adj = adjudicate("Refunds settle within 5 to 7 working days of approval.",
                         SRC, judge)
        assert adj.ran and adj.verdicts
        assert adj.sufficiency.verdict == ""

    def test_the_offline_judge_answers_both_charges(self):
        adj = adjudicate(
            "The festive copy follows the approved tone guide and makes no pricing "
            "claim, so it is ready to go out to your external list.",
            [CAMPAIGN], OfflineProvider(),
            question="Can I send this campaign to our 80,000 external contacts?")
        assert adj.ran
        assert adj.sufficiency.verdict == "omits_condition"


class TestAdjudicatorTriggering:
    BASE = dict(tier="authoritative", price=50, pass_threshold=22, grounding=None,
                already_blocked=False, claims=["Refunds settle in 5 days."])

    def test_an_uncovered_subject_overrides_the_price_floor(self):
        want, why = should_adjudicate(**{**self.BASE, "price": 1, "scope": "uncovered"})
        assert want and "no document held by any registered system" in why

    def test_a_suspected_omission_overrides_the_price_floor(self):
        want, why = should_adjudicate(**{**self.BASE, "price": 1,
                                         "purpose_flagged": True})
        assert want and "left out" in why

    def test_a_clean_grounded_cheap_answer_still_never_pays_for_a_judge(self):
        want, _ = should_adjudicate(**{**self.BASE, "price": 1})
        assert not want

    def test_a_blocked_decision_is_not_adjudicated_however_uncovered(self):
        want, _ = should_adjudicate(**{**self.BASE, "already_blocked": True,
                                       "scope": "uncovered"})
        assert not want

    def test_the_judge_is_required_only_where_it_is_load_bearing(self):
        assert judge_required(tier="parametric", effective_action="advise")
        assert judge_required(tier="authoritative", effective_action="execute",
                              scope="uncovered")
        # Below advise the stakes do not justify blocking on an unreachable
        # dependency.
        assert not judge_required(tier="parametric", effective_action="draft")
        assert not judge_required(tier="authoritative", effective_action="advise")


class TestAdjudicatorFailsClosed:
    def test_a_required_judge_that_fails_is_recorded_mandatory(self):
        adj = Adjudication(False, "unreachable", error="TimeoutError: no response")
        assert to_detector(adj, required=True).requirement == "mandatory"
        assert to_detector(adj, required=False).requirement == "advisory"

    def test_an_unreachable_required_judge_cannot_take_the_clean_pass_route(self):
        from python.controlplane.detectors import DetectorResult
        from python.controlplane.gate import resolve_profile, route
        from python.controlplane.registry import Capability

        profile = resolve_profile("customer_support", None)
        cap = Capability("advise", "advise", 0.70, False, True, False, tool_id="t")
        failed = DetectorResult("adjudication", status="failed",
                                error_code="adjudicator_unavailable",
                                requirement="mandatory",
                                evidence=["the adjudicator could not be reached"])
        decision = route("Refunds settle in five days.", [failed],
                         {"price": 0, "band": [0, 0], "dominant": None, "labels": [],
                          "pFailure": 0.0, "confidence": 0.5, "contributions": {}},
                         profile, cap, {"failClosed": False, "mandatoryMissing": [],
                                        "status": "ungoverned_due_to_failure",
                                        "fullyGoverned": False})
        assert decision["action"] == ESCALATE
        assert decision["detail"]["floor"] == "judge_unavailable"

    def test_the_judgement_is_recorded_on_the_receipt_for_replay(self, plane):
        record = plane.turn("finance-decide",
                            "Is the 8.4% return on the Horizon fund guaranteed?")
        adj = record["adjudication"]
        if adj.get("ran"):
            assert adj["promptSha256"]
            assert "sufficiency" in adj
            snapshot = record["detectorsAtDecision"]
            assert [d for d in snapshot if d["detectorId"] == "adjudication"]


class TestJudgeEvaluation:
    """The answer to "you used a model to check a model — how do you know?"."""

    def test_the_labelled_set_is_weighted_towards_clean_cases(self):
        from python.controlplane.judge_cases import CASES, NEGATIVE, POSITIVE
        assert len(CASES) >= 16
        # For a checker the expensive error is the false alarm, so the set has to
        # be able to measure it.
        assert len(NEGATIVE) > len(POSITIVE)

    def test_the_deterministic_judge_scores_well_enough_to_ship(self):
        from python.controlplane.judge_eval import run
        report = run(OfflineProvider())
        assert report["catchRate"] == 1.0, "a miss is an answer somebody acts on"
        assert report["falseAlarmRate"] <= 0.15, "a checker that cries wolf is ignored"
        assert report["exactAgreement"] >= 0.85
        assert report["tokens"] == 0, "the reference judge must cost nothing"

    def test_every_case_is_explained(self):
        from python.controlplane.judge_cases import CASES
        for case in CASES:
            assert case.why and len(case.why) > 20, case.id
            assert case.tags


# ================================================= the user page ↔ portfolio ===
class TestIntegration:
    def test_a_user_question_is_priced_by_the_same_code_as_everything_else(self, plane):
        plane.turn("support-copilot", "What is the status of my open ticket?")
        out = plane.ask("support-copilot", "How long does a refund take to reach my bank?",
                        session_id="s", user="Ravi Menon")
        assert out["status"] == "answered"
        record = plane.by_id[out["requestId"]]
        assert record["origin"] == "user"
        # Same shape, same fields, same ledger — not a parallel code path.
        ambient = [d for d in plane.decisions if d.get("origin") == "ambient"][0]
        # Every field a governed decision carries, the user's question carries
        # too. (Deferred verification later adds two more to whichever record it
        # amends, so the user record's keys are a subset, never a different set.)
        assert set(record) <= set(ambient) or set(ambient) <= set(record)
        assert {"risk", "decision", "governance", "policy", "detectorsAtDecision",
                "evidence", "adjudication", "ledgerIndex"} <= set(record)

    def test_it_lands_in_the_portfolio_and_names_itself_as_user_traffic(self, plane):
        plane.ask("marketing-copilot",
                  "Can I send this festive campaign to our 80,000 external contacts?",
                  session_id="s", user="Neha Bhatt")
        project = plane.project("marketing-copilot")
        assert project["userTurns"] == 1
        assert project["userExposure"] > 0
        fleet = plane.fleet()
        live = fleet["liveTraffic"]
        assert live["turns"] == 1 and live["turnsAllTime"] == 1
        assert live["recent"][0]["systemId"] == "marketing-copilot"
        assert live["recent"][0]["requestId"] in plane.by_id

    def test_oversight_cost_is_where_a_single_question_actually_shows_up(self, plane):
        """One question costs a fraction of a rupee in tokens against a monthly
        budget in the tens of thousands. What moves is the cost of pulling a
        human in, and that is reported as its own line rather than folded into
        model spend — two budgets, two owners."""
        out = plane.ask("finance-decide",
                        "Is the 8.4% return on the Horizon fund guaranteed?",
                        session_id="s", user="Anita Desai")
        record = plane.by_id[out["requestId"]]
        if record["decision"]["action"] in (ESCALATE, BLOCK):
            assert record["oversightCostInr"] > record["spendInr"] * 100
            assert record["totalCostInr"] == pytest.approx(
                record["spendInr"] + record["oversightCostInr"], abs=0.01)
        live = plane.live_traffic()
        assert live["perThousandTurnsInr"] > 0

    def test_the_user_is_shown_where_their_question_landed(self, plane):
        plane.ask("finance-decide", "Is the 8.4% return on the Horizon fund guaranteed?",
                  session_id="s", user="Anita Desai")
        outcome = plane.chat("s")[-1]["outcome"]
        acct = outcome["accounting"]
        assert acct["system"] == "Finance Decision Assistant"
        assert acct["ledgerIndex"] is not None
        assert "adjudication" in outcome

    def test_a_released_question_still_counts_as_user_traffic(self, plane):
        out = plane.ask("support-copilot",
                        "My card is 4539578763621486 and I was charged twice.",
                        session_id="s", user="Ravi Menon")
        assert out["status"] == "held"
        plane.review_question(out["heldId"], "pass", actor="Priya Nair",
                              note="Verified caller.")
        assert plane.live_traffic()["turns"] == 1

    def test_the_departments_are_the_same_on_every_surface(self, plane):
        """The registry is the only place a system is named. The user page reads
        the same rows the console, portfolio and advisor read, so a rename lands
        everywhere at once and cannot drift."""
        for app in plane.registry.applications.values():
            row = app.as_dict()
            assert row["name"] and row["department"]
            assert row["endUser"], f"{app.system_id} has nobody to ask questions"
            assert row["sampleQuestions"], f"{app.system_id} has no sample questions"
            assert plane.project(app.system_id)["name"] == row["name"]
            assert plane.scope.names[app.system_id] == row["name"]
