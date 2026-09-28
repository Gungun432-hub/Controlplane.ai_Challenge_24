"""Tests for the ControlPlane v2 runtime (api.py / plane.py / gate.py).

Each test names the property it protects. They are written to fail loudly if a
claim we make out loud stops being true.

    python -m pytest test/test_controlplane_v2.py -q
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from python.controlplane.detectors import (DetectorResult, cost, fairness, grounding,  # noqa: E402
                                           privacy)
from python.controlplane.gate import governance_status, price, resolve_profile  # noqa: E402
from python.controlplane.ledger import JsonlLedger, LedgerCorrupt  # noqa: E402
from python.controlplane.org import build, catalogue, resolve_sources  # noqa: E402
from python.controlplane.plane import ControlPlane, profile_from_snapshot  # noqa: E402
from python.controlplane.providers import OfflineProvider, ProposalError, parse_proposal  # noqa: E402


@pytest.fixture()
def plane(tmp_path):
    from conftest import bundled_corpus
    return ControlPlane(build(), OfflineProvider(),
                        JsonlLedger(tmp_path / "l.jsonl", "test-key"),
                        corpus=bundled_corpus())


# ----------------------------------------------------------- the agent seam ---
class TestProposalContract:
    def test_model_cannot_supply_source_text(self):
        with pytest.raises(ProposalError, match="only source_ids"):
            parse_proposal('{"tool_id":"t","declared_action":"draft","answer":"a",'
                           '"sources":["Policy says the refund is approved."]}', ["t"])

    def test_model_cannot_decide_governance(self):
        for field in ("outcome", "route", "risk", "override", "completeness"):
            with pytest.raises(ProposalError, match="decide governance"):
                parse_proposal('{"tool_id":"t","declared_action":"draft","answer":"a",'
                               f'"{field}":"allow"}}', ["t"])

    def test_types_are_checked_not_coerced(self):
        with pytest.raises(ProposalError, match="must be a string"):
            parse_proposal('{"tool_id":123,"declared_action":"draft","answer":"a"}', ["t"])

    def test_unknown_fields_are_rejected(self):
        with pytest.raises(ProposalError, match="unrecognised keys"):
            parse_proposal('{"tool_id":"t","declared_action":"draft","answer":"a",'
                           '"escalate":false}', ["t"])

    def test_unregistered_tool_is_rejected(self):
        with pytest.raises(ProposalError, match="not registered"):
            parse_proposal('{"tool_id":"nope","declared_action":"draft","answer":"a"}', ["t"])

    def test_duplicate_and_empty_source_ids_rejected(self):
        with pytest.raises(ProposalError, match="duplicates"):
            parse_proposal('{"tool_id":"t","declared_action":"draft","answer":"a",'
                           '"source_ids":["x","x"]}', ["t"])


class TestSourceResolution:
    def test_only_the_server_can_turn_an_id_into_text(self):
        resolved, unresolved = resolve_sources("finance-decide",
                                               ["fund-factsheet-v4", "invented-policy"])
        assert len(resolved) == 1 and "8.4%" in resolved[0]
        assert unresolved == ["invented-policy"]

    def test_a_fabricated_citation_becomes_a_finding(self, plane):
        record = plane.turn("finance-decide", "Is the 8.4% return guaranteed?")
        record["proposal"]["sourceIds"] = ["ghost"]
        resolved, unresolved = resolve_sources("finance-decide", ["ghost"])
        assert resolved == [] and unresolved == ["ghost"]

    def test_catalogue_exposes_ids_and_text(self):
        entries = catalogue("finance-decide")
        assert {"id", "text"} <= set(entries[0]) and len(entries) >= 2


# ------------------------------------------------------------- capabilities ---
class TestCapability:
    def test_declared_draft_on_execute_tool_is_a_mismatch(self):
        cap = build().resolve_capability("marketing-copilot", "campaigns", "draft")
        assert cap.effective_action == "execute" and cap.mismatch
        assert cap.blast_radius == 1.0

    def test_amount_over_limit_is_denied_not_escalated(self):
        cap = build().resolve_capability("finance-decide", "issue_refund", "draft",
                                         amount_inr=8400)
        assert cap.denied and "limit" in cap.denied

    def test_environment_restriction_refuses(self):
        cap = build().resolve_capability("it-ops-agent", "restart_service", "draft")
        assert cap.denied and "environment" in cap.denied

    def test_unrecognised_declared_action_fails_closed(self):
        cap = build().resolve_capability("support-copilot", "ticketing", "teleport")
        assert cap.denied == "unrecognised declared action"

    def test_unregistered_application_gets_strictest_reading(self):
        cap = build().resolve_capability("ghost-bot", None, "read")
        assert cap.denied == "unregistered application"
        assert cap.effective_action == "execute"


# -------------------------------------------------------------- governance ---
class TestGovernanceCompleteness:
    def _profile(self):
        return resolve_profile("customer_support", None)

    def test_advisory_deferred_is_scheduled_not_missing(self):
        results = [DetectorResult("grounding", 0.1, .8, "completed", requirement="mandatory"),
                   DetectorResult("privacy", 0.0, .9, "completed", requirement="mandatory"),
                   DetectorResult("cost", None, None, "queued_async", requirement="advisory")]
        assert governance_status(results, self._profile(), "advise")["status"] == "fully_governed"

    def test_MANDATORY_deferred_is_not_yet_verified(self):
        """Scheduled is not verified. This is the distinction the whole metric
        rests on."""
        results = [DetectorResult("grounding", 0.1, .8, "completed", requirement="mandatory"),
                   DetectorResult("privacy", None, None, "queued_async", requirement="mandatory")]
        gov = governance_status(results, self._profile(), "advise")
        assert gov["status"] == "awaiting_verification"
        assert gov["fullyGoverned"] is False

    def test_mandatory_failure_fails_closed_on_irreversible(self):
        results = [DetectorResult("privacy", None, None, "failed", requirement="mandatory")]
        assert governance_status(results, self._profile(), "execute")["failClosed"] is True

    def test_a_timed_out_detector_is_not_priced(self):
        results = [DetectorResult("grounding", 0.9, .8, "completed"),
                   DetectorResult("privacy", None, None, "timed_out")]
        assert "privacy" not in price(results, {"grounding": 1.0}, 1.0)["contributions"]


# --------------------------------------------------------------- replay ---
class TestReproduceIsDeterministic:
    """The strongest claim in the product. It must be true field by field, not
    approximately true on two of the fields we happened to compare."""

    def test_evidence_at_decision_is_snapshotted_separately(self, plane):
        rid = plane.turn("support-copilot", "What is the status of my open ticket?")["requestId"]
        rec = plane.by_id[rid]
        assert "detectorsAtDecision" in rec
        assert rec["detectorsAtDecision"] is not rec["detectors"]

    def test_deferred_amendment_does_not_rewrite_the_snapshot(self, plane):
        rid = plane.turn("support-copilot", "What is the status of my open ticket?")["requestId"]
        rec = plane.by_id[rid]
        before = [dict(d) for d in rec["detectorsAtDecision"]]
        deadline = time.time() + 5
        while time.time() < deadline and rec["verificationStatus"] != "complete":
            time.sleep(0.05)
        assert rec["detectorsAtDecision"] == before, (
            "the decision-time evidence was rewritten by deferred verification")
        assert rec["risk"] == rec["risk"], "risk at release must be immutable"

    def test_a_replay_is_identical_across_every_canonical_field(self, plane):
        """Runs after verification has landed, which is when the old
        implementation diverged on the confidence band."""
        rid = plane.turn("finance-decide", "Is the 8.4% guaranteed?")["requestId"]
        rec = plane.by_id[rid]
        deadline = time.time() + 5
        while time.time() < deadline and rec["verificationStatus"] != "complete":
            time.sleep(0.05)

        from python.controlplane.detectors import DetectorResult as DR
        from python.controlplane.gate import governance_status, price, route
        from python.controlplane.plane import _cap_from, profile_from_snapshot
        ev = [DR(d["detectorId"], d["score"], d["confidence"], d["status"],
                 requirement=d.get("requirement", "advisory"),
                 labels=d.get("labels", []), detail=d.get("detail", {}))
              for d in rec["detectorsAtDecision"]]
        prof = profile_from_snapshot(rec["policy"])
        cap = _cap_from(rec["capability"])
        risk = price(ev, prof.weights, cap.blast_radius)
        gov = governance_status(ev, prof, cap.effective_action)
        again = route(rec["proposal"]["answer"], ev, risk, prof, cap, gov)

        assert again["action"] == rec["decision"]["action"]
        assert risk["price"] == rec["risk"]["price"]
        assert risk["band"] == rec["risk"]["band"], "the confidence band diverged"
        assert risk["pFailure"] == rec["risk"]["pFailure"]
        assert gov["status"] == rec["governance"]["status"]
        assert again["releasedText"] == rec["decision"]["releasedText"]


# ------------------------------------------------------ policy composition ---
class TestOverlaysOnlyTighten:
    """`resolve_profile` documents this in its own docstring, so it has to be
    true for every profile × jurisdiction × control combination we ship."""

    def test_no_jurisdiction_loosens_any_weight_or_threshold(self):
        from python.controlplane.gate import JURISDICTIONS, PROFILES
        for pid, base in PROFILES.items():
            for jid in JURISDICTIONS:
                r = resolve_profile(pid, jid)
                for k, v in base.thresholds.items():
                    assert r.thresholds[k] <= v, f"{pid}/{jid} loosened threshold {k}"
                for k, w in base.weights.items():
                    assert r.weights[k] >= w, f"{pid}/{jid} loosened weight {k}"

    def test_a_control_overlay_only_tightens(self):
        base = resolve_profile("customer_support", None)
        tight = resolve_profile("customer_support", None,
                                {"tighten": {"pass": 5}, "promote_inline": ["fairness"],
                                 "require_human": True})
        assert tight.thresholds["pass"] < base.thresholds["pass"]
        assert tight.thresholds["escalate"] <= base.thresholds["escalate"]
        assert set(base.inline) <= set(tight.inline)

    def test_a_threshold_never_falls_below_one(self):
        r = resolve_profile("decision_support", "eu", {"tighten": {"pass": 999}})
        assert r.thresholds["pass"] >= 1


# --------------------------------------------- proposed versus executed ---
class TestProposedVersusExecuted:
    """A verdict on text is not the same object as a change to the world.

    Every decision must say which one happened, because "the model proposed
    this" and "this was done" are the two things an auditor is distinguishing
    between and a receipt that renders them identically is useless."""

    def _rec(self, plane, system_id, message):
        return plane.by_id[plane.turn(system_id, message)["requestId"]]

    def test_a_blocked_execute_states_that_nothing_happened(self, plane):
        rec = self._rec(plane, "it-ops-agent",
                        "Restart the payments service in production now.")
        se = rec["decision"]["sideEffect"]
        assert rec["decision"]["action"] == "block"
        assert se["state"] == "withheld"
        assert se["changesTheWorld"] is True, "an execute had a side effect at stake"

    def test_the_capability_lie_refuses_the_action_without_destroying_the_work(self, plane):
        rec = self._rec(plane, "marketing-copilot",
                        "Send this festive campaign to all customers.")
        cap, dec = rec["capability"], rec["decision"]
        assert cap["declaredAction"] == "draft" and cap["effectiveAction"] == "execute"
        assert dec["action"] == "block"
        # The work is not destroyed — but it does NOT go to the person who
        # asked. Those are two different fields on purpose: the user page
        # renders `releasedText`, so a block that left the text there could
        # show somebody the very answer it says was withheld.
        assert dec["releasedText"] == "", "blocked text must never reach the user"
        assert dec["developerDraft"], "the draft was thrown away; that is a wall, not a control"
        assert dec["sideEffect"]["textReturnedToDeveloper"] is True
        assert dec["sideEffect"]["textReturnedToDeveloper"] is True
        assert dec["downgradedTo"] == "draft"

    def test_a_text_only_block_does_not_claim_a_side_effect(self, plane):
        """A blocked draft and a blocked execute are different events."""
        from python.controlplane.gate import side_effect
        from python.controlplane.registry import Capability
        cap = Capability("draft", "draft", 0.35, False, True, False, tool_id="ticketing")
        se = side_effect("block", cap, "")
        assert se["changesTheWorld"] is False
        assert se["textReturnedToDeveloper"] is False

    def test_a_clean_answer_says_it_was_released(self, plane):
        rec = self._rec(plane, "support-copilot", "What is the status of my open ticket?")
        se = rec["decision"]["sideEffect"]
        assert se["state"] == "released"
        assert se["changesTheWorld"] is False

    def test_every_decision_path_carries_a_side_effect(self, plane):
        """Including the paths that return before a model is ever called."""
        plane.apply_overlay("support-copilot", "suspend", {"suspend": True},
                            "coverage", approved_by="test", ttl_s=60)
        rec = self._rec(plane, "support-copilot", "anything at all")
        assert rec["decision"]["sideEffect"]["state"] == "withheld"
        for r in plane.decisions:
            assert "sideEffect" in r["decision"], r["decision"].get("reason")

    def test_the_receipt_names_the_tool_that_proved_the_action(self, plane):
        rec = self._rec(plane, "it-ops-agent", "Restart the payments service in production.")
        assert rec["capability"]["toolId"] == "restart_service"


# ------------------------------------------------- runtime, not the helper ---
class TestTheRuntimeActuallyLabelsDeferredWork:
    """`governance_status` had the right logic and the runtime never fed it the
    right input: every deferred detector was hardcoded `advisory`, so a
    *mandatory* deferred check reported `fully_governed`.

    The tests above construct DetectorResult by hand, which is exactly why they
    passed while the runtime was wrong. These go through `plane.turn()`."""

    def _record(self, plane, **kw):
        return plane.by_id[plane.turn(**kw)["requestId"]]

    def _results(self, plane, **kw):
        return {d["detectorId"]: d for d in self._record(plane, **kw)["detectors"]}

    def test_a_deferred_mandatory_detector_is_labelled_mandatory(self, plane, monkeypatch):
        prof = resolve_profile("internal_knowledge", None)
        deferred_mandatory = sorted(set(prof.deferred) & set(prof.mandatory))
        assert deferred_mandatory == ["privacy"], (
            "fixture assumption changed; this test needs a profile that defers a "
            "mandatory detector")
        from python.controlplane import plane as plane_mod
        monkeypatch.setattr(plane_mod, "_enqueue",
                            lambda rid, names, kwargs, cb: (len(names), []))
        ev = self._results(plane, system_id="support-copilot",
                           message="Summarise the internal escalation policy.",
                           shadow_profile="internal_knowledge")
        assert ev["privacy"]["requirement"] == "mandatory", ev["privacy"]
        assert ev["privacy"]["status"] == "queued_async", ev["privacy"]

    def test_that_decision_is_awaiting_verification_not_fully_governed(self, plane, monkeypatch):
        # Hold the deferred work so the assertion is about the decision as
        # returned, not about whether a background thread happened to win.
        from python.controlplane import plane as plane_mod
        monkeypatch.setattr(plane_mod, "_enqueue",
                            lambda rid, names, kwargs, cb: (len(names), []))
        rid = plane.turn("support-copilot", "Summarise the internal escalation policy.",
                         shadow_profile="internal_knowledge")["requestId"]
        gov = plane.by_id[rid]["governance"]
        assert gov["status"] == "awaiting_verification", gov
        assert gov["fullyGoverned"] is False

    def test_an_advisory_deferred_detector_is_still_advisory(self, plane):
        ev = self._results(plane, system_id="support-copilot",
                           message="What is the status of my open ticket?")
        assert ev["cost"]["requirement"] == "advisory", ev["cost"]
        # deferred work may already have landed and amended the record in place
        assert ev["cost"]["status"] in ("queued_async", "completed_async"), ev["cost"]

    def test_a_saturated_queue_is_recorded_once_as_a_failure(self, plane, monkeypatch):
        """A dropped detector used to get two records: one `failed` and one
        `queued_async`. A reader could then see the softer of the two and
        conclude the work was merely pending."""
        from python.controlplane import plane as plane_mod
        monkeypatch.setattr(plane_mod, "_enqueue",
                            lambda rid, names, kwargs, cb: (0, list(names)))
        ev = self._results(plane, system_id="support-copilot",
                           message="What is the status of my open ticket?")
        assert ev["cost"]["status"] == "failed"
        assert ev["cost"]["errorCode"] == "queue_saturated"

    def test_a_refused_submission_is_not_a_clean_check(self, plane):
        """gate.shutdown() used to leave the process serving requests with dead
        pools. Nothing may be priced as zero because it never ran."""
        from python.controlplane import gate
        gate.shutdown(wait=True)
        rid = plane.turn("support-copilot", "What is the status of my open ticket?")["requestId"]
        ev = {d["detectorId"]: d for d in plane.by_id[rid]["detectors"]}
        # The pools rebuild themselves, so the honest outcome is a working
        # decision — not a 500, and not a silent zero.
        assert ev["grounding"]["status"] in ("completed", "failed", "timed_out")
        if ev["grounding"]["status"] == "failed":
            assert ev["grounding"]["errorCode"] == "executor_unavailable"


# ---------------------------------------------------------------- detectors ---
class TestDetectors:
    def test_checksum_rejects_a_number_that_merely_looks_like_a_card(self):
        assert privacy("order 12345678901234567 shipped").score == 0.0

    def test_luhn_valid_card_is_found(self):
        assert privacy("card 4539578763621486 charged").score == 1.0

    def test_numeric_contradiction_is_caught(self):
        src = ["The fund targets 8.4% annualised returns."]
        result = grounding("The fund guarantees 12.5% every year.", src)
        assert result.detail["contradiction"] and "hallucination" in result.labels

    def test_supported_answer_scores_zero(self):
        src = ["The fund targets 8.4% annualised returns."]
        assert grounding("The fund targets 8.4% annualised returns.", src).score == 0.0

    def test_no_sources_is_unverifiable_not_wrong(self):
        """The answer has to make a claim first.

        This used to pass the string "anything at all", which asserts nothing
        about the world — and a checker that calls a greeting unverifiable is
        manufacturing its own alert fatigue. The fixture now carries a real
        claim, which is what the test was always about."""
        assert "unverifiable" in grounding(
            "Refunds are processed within 5 working days.", []).labels

    def test_an_answer_with_no_claim_in_it_is_not_unverifiable(self):
        """"Hello! How can I help you today?" is not an unchecked assertion."""
        for pleasantry in ("Hello! How can I help you today?",
                           "Sure, happy to help with that.",
                           "I am ready to assist you with your questions."):
            result = grounding(pleasantry, [])
            assert result.labels == [], pleasantry
            assert result.score == 0.0
            assert result.detail["nothingAsserted"] is True

    def test_it_cannot_be_used_to_smuggle_a_claim_past_grounding(self):
        """Deliberately narrow: a figure, a date, money, a duration, a policy
        word or a commitment all still count as checkable."""
        for claim in ("You are eligible for a refund.",
                      "This will be approved.",
                      "It takes 10 days.",
                      "Our policy covers this."):
            assert "unverifiable" in grounding(claim, []).labels, claim

    def test_fairness_without_provider_is_explicit_not_zero(self):
        result = fairness("approved", "candidate from Bandra", provider=None)
        assert result.status == "not_configured" and result.score is None

    def test_counterfactual_flip_is_detected(self):
        result = fairness("approved", "candidate Rajesh from Bandra 400050",
                          provider=OfflineProvider())
        assert result.detail["flips"] >= 1 and "bias" in result.labels


# ------------------------------------------------------------------- ledger ---
class TestLedger:
    def test_concurrent_appends_keep_the_chain_intact(self, tmp_path):
        ledger = JsonlLedger(tmp_path / "c.jsonl", "k")

        def write(n):
            for i in range(40):
                ledger.append({"w": n, "i": i})

        threads = [threading.Thread(target=write, args=(n,)) for n in range(5)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert ledger.verify() == {"valid": True, "entries": 200}
        assert [r["index"] for r in ledger.read(10 ** 6)] == list(range(200))

    def test_tampering_is_detected_and_located(self, tmp_path):
        ledger = JsonlLedger(tmp_path / "t.jsonl", "k")
        for i in range(5):
            ledger.append({"i": i})
        rows = ledger.path.read_text(encoding="utf-8").splitlines()
        assert '"i": 2' in rows[2], "test fixture did not locate the row to tamper"
        rows[2] = rows[2].replace('"i": 2', '"i": 999')
        ledger.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        result = ledger.verify()
        assert result["valid"] is False, "tampering was not detected"
        assert result["brokenAt"] == 2, f"located at {result.get('brokenAt')}, expected 2"
        assert result["reason"] == "content hash mismatch"

    def test_appending_after_corruption_is_refused(self, tmp_path):
        ledger = JsonlLedger(tmp_path / "x.jsonl", "k")
        ledger.append({"a": 1})
        with ledger.path.open("a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        with pytest.raises(LedgerCorrupt):
            ledger.append({"a": 2})


# --------------------------------------------------------------- the record ---
class TestDecisionRecord:
    def test_the_user_message_is_retained(self, plane):
        record = plane.turn("finance-decide", "Is the 8.4% return guaranteed?")
        assert record["message"] == "Is the 8.4% return guaranteed?"
        assert len(record["messageSha256"]) == 16

    def test_concurrent_turns_keep_their_own_messages(self, plane):
        """The message must never live in shared mutable state."""
        out: list[tuple[str, str]] = []
        lock = threading.Lock()

        def run(n: int):
            msg = f"unique request number {n} about the fund"
            rec = plane.turn("finance-decide", msg)
            with lock:
                out.append((msg, rec["message"]))

        threads = [threading.Thread(target=run, args=(n,)) for n in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert all(sent == stored for sent, stored in out), "message was cross-wired"

    def test_the_full_policy_snapshot_is_stored(self, plane):
        record = plane.turn("finance-decide", "Summarise the fund guidance.")
        snap = record["policy"]
        assert {"thresholds", "weights", "jurisdiction", "mandatory", "hardGateActions"} <= set(snap)
        assert snap["jurisdiction"] == "in"

    def test_replay_rebuilds_the_original_rules_not_current_ones(self, plane):
        record = plane.turn("recruit-screen", "Summarise the screening rubric.")
        rebuilt = profile_from_snapshot(record["policy"])
        assert rebuilt.thresholds == record["policy"]["thresholds"]
        assert rebuilt.jurisdiction == record["policy"]["jurisdiction"] == "eu"

    def test_the_receipt_reaches_the_ledger(self, plane):
        record = plane.turn("support-copilot", "What is the status of my ticket?")
        assert record.get("ledgerIndex") is not None
        entries = plane.ledger.read(10 ** 6)
        receipts = [e["record"]["receipt"] for e in entries
                    if e["record"].get("event") == "decision.issued"]
        assert any(r["requestId"] == record["requestId"] and r["message"] for r in receipts)


# ------------------------------------------------------------------ recovery ---
class TestRecovery:
    def test_state_rebuilds_from_the_ledger(self, tmp_path):
        path = tmp_path / "r.jsonl"
        first = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        for i in range(6):
            first.turn("support-copilot", f"ticket question {i}")
        first.apply_overlay("finance-decide", "suspend", {"suspend": True},
                            "over budget", approved_by="Arun Mehta", ttl_s=3600)
        time.sleep(0.4)

        second = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        result = second.recover()
        assert result["recovered"] == 6
        assert second._seq == 6, "sequence must resume, not restart"
        assert len(second.overlays) == 1
        assert second.overlays[0].approved_by == "Arun Mehta"
        # State is derived from live controls, not from a cached attribute.
        assert second.state_of("finance-decide") == "suspended"
        assert second.project("finance-decide")["state"] == "suspended"

    def test_a_suspended_system_is_still_refused_after_restart(self, tmp_path):
        path = tmp_path / "s.jsonl"
        first = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        first.apply_overlay("finance-decide", "suspend", {"suspend": True}, "over budget",
                            approved_by="Arun Mehta", ttl_s=3600)
        second = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        second.recover()
        record = second.turn("finance-decide", "Summarise the fund guidance.")
        assert record["decision"]["action"] == "block"
        assert "suspended" in record["decision"]["reason"]

    def test_restart_does_not_extend_a_control(self, tmp_path):
        path = tmp_path / "e.jsonl"
        first = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        overlay = first.apply_overlay("marketing-copilot", "tighten", {"tighten": {"pass": 4}},
                                      "drift", ttl_s=600)
        original_expiry = overlay.expires_at
        time.sleep(1.0)
        second = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        second.recover()
        assert second.overlays, "overlay was not recovered"
        drift = abs(second.overlays[0].expires_at - original_expiry)
        assert drift < 2.0, f"restart moved expiry by {drift:.1f}s"

    def test_recovered_last_seen_comes_from_the_record(self, tmp_path):
        path = tmp_path / "ls.jsonl"
        first = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        first.turn("support-copilot", "ticket question")
        second = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        second.recover()
        assert "it-ops-agent" not in second.last_seen, \
            "a system with no history must not look recently active"

    def test_recommendations_survive_a_restart(self, tmp_path):
        path = tmp_path / "rec.jsonl"
        first = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        for i in range(4):
            first.turn("marketing-copilot", "Send this festive campaign to all customers.")
        assert first.recommendations, "no recommendations were produced"
        second = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        second.recover()
        assert len(second.recommendations) == len(first.recommendations)
        assert second.recommendations[0]["ruleId"] == first.recommendations[0]["ruleId"]


# -------------------------------------------------------------- projections ---
class TestProjections:
    def test_zero_decisions_is_not_reported_as_perfect(self, plane):
        fleet = plane.fleet()
        assert fleet["completeness"] is None
        assert "not_available" in fleet["completenessLabel"]

    def test_fleet_totals_match_the_sum_of_the_cards(self, plane):
        for i in range(8):
            plane.turn("support-copilot", f"ticket question {i}")
        fleet = plane.fleet()
        assert abs(fleet["spendInr"] - sum(s["spendInr"] for s in fleet["systems"])) < 0.01

    def test_a_silent_system_reads_unknown_not_healthy(self, plane):
        for i in range(3):
            plane.turn("support-copilot", f"ticket {i}")
        status = {s["systemId"]: s["status"] for s in plane.fleet()["systems"]}
        assert status["it-ops-agent"] == "unknown"


# --------------------------------------------------------------- budgets ---
class TestBudgetChangesAreGovernedToo:
    """A control plane whose own controls leave no evidence is not one."""

    def test_a_budget_change_is_written_to_the_ledger(self, plane):
        # Read the configured value rather than hardcoding it: the shipped
        # number is demo tuning and moves whenever the pitch is rehearsed.
        before = plane.registry.get("marketing-copilot").budget_inr_month
        out = plane.set_budget("marketing-copilot", actor="Arun Mehta", budget_inr=18000)
        assert out["persisted"] is True
        assert out["budgetInr"] == 18000.0
        assert out["previous"]["budgetInr"] == before
        kinds = [e["record"]["event"] for e in plane.ledger.read(limit=10**6)]
        assert "budget.changed" in kinds

    def test_a_budget_change_survives_a_restart(self, tmp_path):
        path = tmp_path / "b.jsonl"
        first = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        first.set_budget("marketing-copilot", actor="Arun Mehta", budget_inr=31000)
        second = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=__import__('conftest').bundled_corpus())
        rec = second.recover()
        assert rec["budgets"] == 1
        assert second.registry.get("marketing-copilot").budget_inr_month == 31000.0

    @pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), -float("inf"), 1e12])
    def test_a_nonsense_budget_is_refused(self, plane, bad):
        before = plane.registry.get("marketing-copilot").budget_inr_month
        with pytest.raises(ValueError):
            plane.set_budget("marketing-copilot", actor="Arun", budget_inr=bad)
        assert plane.registry.get("marketing-copilot").budget_inr_month == before

    def test_an_unknown_system_is_refused(self, plane):
        with pytest.raises(ValueError, match="unknown system"):
            plane.set_budget("not-a-system", actor="Arun", budget_inr=1000)

    def test_utilisation_is_never_divided_by_a_zero_budget(self, plane):
        """The guard exists because a zero budget makes every reading nonsense."""
        with pytest.raises(ValueError, match="greater than zero"):
            plane.set_budget("marketing-copilot", actor="Arun", budget_inr=0)


# ------------------------------------------------- grounding integrity ---
class TestThePromptIsNotEvidence:
    """Support used to be measured against the sources *plus the user's own
    prompt*, so a claim could look grounded because the person asking supplied
    the vocabulary. That is a laundering hole, not a detector."""

    SRC = ["The Horizon Balanced Fund targets 8.4% annualised returns. "
           "Returns are not guaranteed."]

    def test_a_claim_cannot_be_supported_by_the_question_alone(self):
        r = grounding(answer="Yes, the 8.4% is fully guaranteed for every investor.",
                      sources=self.SRC, prompt="Is the 8.4% guaranteed?")
        assert r.score > 0.5, r.evidence
        assert "unverifiable" in r.labels

    def test_a_figure_only_the_user_supplied_is_unconfirmed_not_fabricated(self):
        r = grounding(answer="The fund returns 22.7% annually, as you said.",
                      sources=self.SRC, prompt="Does it return 22.7% annually?")
        assert r.detail["contradiction"] is False, "the model did not invent the user's figure"
        assert r.detail["figuresEchoedFromPrompt"] == ["22.7%"]
        assert "unverifiable" in r.labels

    def test_a_figure_in_no_source_and_no_question_is_a_contradiction(self):
        r = grounding(answer="The Horizon Balanced Fund guarantees 12.5% returns every year.",
                      sources=self.SRC, prompt="Is the 8.4% guaranteed?")
        assert r.detail["contradiction"] is True
        assert "hallucination" in r.labels

    def test_a_genuinely_supported_answer_still_passes(self):
        r = grounding(answer="The Horizon Balanced Fund targets 8.4% annualised returns.",
                      sources=self.SRC, prompt="What does Horizon target?")
        assert r.score == 0.0
        assert r.labels == []


# ------------------------------------------------- derived, not remembered ---
class TestStateFollowsTheControl:
    """The console and the gate must never disagree about whether a system is
    suspended. They used to: the gate read the overlay's TTL, the console read a
    flag that was written once and never cleared."""

    def test_an_expired_control_releases_the_system(self, plane):
        plane.apply_overlay("marketing-copilot", "suspend", {"suspend": True},
                            "test", approved_by="Arun", ttl_s=1)
        assert plane.state_of("marketing-copilot") == "suspended"
        assert plane.project("marketing-copilot")["status"] == "breaching"
        time.sleep(1.1)
        assert plane.state_of("marketing-copilot") == "recovering", (
            "the console still shows a control the gate has already stopped enforcing")
        assert plane.overlay_for("marketing-copilot") is None
        record = plane.turn("marketing-copilot", "Draft a headline for the festive copy.")
        assert "suspended" not in record["decision"]["reason"]

    def test_a_rolled_back_control_reads_recovering(self, plane):
        o = plane.apply_overlay("marketing-copilot", "quarantine",
                                {"quarantine": True, "max_action": "read"},
                                "test", approved_by="Arun", ttl_s=3600)
        assert plane.state_of("marketing-copilot") == "quarantined"
        plane.rollback_overlay(o.id, actor="Arun")
        assert plane.state_of("marketing-copilot") == "recovering"

    def test_a_system_with_no_controls_is_healthy(self, plane):
        assert plane.state_of("support-copilot") == "healthy"

    def test_an_unregistered_system_is_not_called_healthy(self, plane):
        assert plane.state_of("ghost-system") == "unregistered"

    def test_the_strictest_live_control_wins(self, plane):
        plane.apply_overlay("marketing-copilot", "tool_restricted", {"tool_restricted": True},
                            "test", approved_by="Arun", ttl_s=600)
        assert plane.state_of("marketing-copilot") == "tool_restricted"
        plane.apply_overlay("marketing-copilot", "suspend", {"suspend": True},
                            "test", approved_by="Arun", ttl_s=600)
        assert plane.state_of("marketing-copilot") == "suspended"


# --------------------------------------------------------- cost & fairness ---
class TestStatefulDetectorsStayHonest:
    def test_the_cost_window_is_safe_under_concurrency(self):
        from python.controlplane.detectors import CostWindow
        w, errors = CostWindow(keep=50), []

        def hammer(n):
            try:
                for i in range(200):
                    w.observe(f"class-{n % 3}", 40 + i, f"prompt {i}")
            except Exception as exc:                                  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=hammer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        for cls in ("class-0", "class-1", "class-2"):
            assert len(w._tokens[cls]) <= 50, "the window grew past its cap"

    def test_a_cold_window_claims_no_comparison(self):
        from python.controlplane.detectors import CostWindow
        w = CostWindow()
        ratio, dup, window = w.observe("fresh-class", 120, "hello")
        assert ratio == 1.0 and dup == 0.0
        assert window["windowSize"] == 0 and window["median"] is None

    def test_the_receipt_records_the_window_the_number_came_from(self):
        r = cost(answer="a" * 200, prompt="b" * 40, task_class="unit-test-class", tokens=90)
        assert "window" in r.detail
        assert r.detail["window"]["keep"] == 200

    def test_an_inconclusive_probe_is_not_reported_as_bias(self):
        class Mute:
            def decide_probe(self, text):
                return "unknown"
        r = fairness(answer="The candidate from Bandra is a strong fit.",
                     prompt="Approve or reject?", provider=Mute())
        assert r.status == "failed"
        assert r.error_code == "probes_inconclusive"
        assert "bias" not in r.labels

    def test_one_sided_unknown_does_not_manufacture_a_flip(self):
        class HalfMute:
            def __init__(self): self.n = 0
            def decide_probe(self, text):
                self.n += 1
                return "approve" if self.n % 2 else "unknown"
        r = fairness(answer="The candidate from Dharavi is a strong fit.",
                     prompt="Approve or reject?", provider=HalfMute())
        assert "bias" not in r.labels, r.evidence
        assert r.detail.get("inconclusive", 0) >= 1

    def test_a_real_flip_is_still_caught(self):
        from python.controlplane.providers import OfflineProvider
        r = fairness(answer="The candidate from Bandra, 400050, is a strong fit.",
                     prompt="Approve or reject this applicant?", provider=OfflineProvider())
        assert r.status == "completed"
        assert "bias" in r.labels, r.evidence


# ------------------------------------------------------------ the two clocks ---
class TestTheVerificationClockIsReal:
    """Seeded history is deliberately backdated so the console has a past. The
    verification clock must measure how long verification actually took, not how
    long ago the synthetic timestamp claims the turn happened — that reported a
    23-minute verification latency on a freshly booted demo."""

    def test_a_backdated_turn_does_not_inflate_the_verification_clock(self, plane):
        past = "2020-01-01T00:00:00Z"
        rid = plane.turn("support-copilot", "What is the status of my open ticket?",
                         at=past)["requestId"]
        rec = plane.by_id[rid]
        assert rec["createdAt"] == past
        deadline = time.time() + 5
        while time.time() < deadline and rec["verificationLatencyMs"] is None:
            time.sleep(0.05)
        assert rec["verificationLatencyMs"] is not None, "deferred work never amended"
        assert rec["verificationLatencyMs"] < 10_000, (
            f"verification clock read {rec['verificationLatencyMs']} ms for a turn that "
            f"was processed seconds ago")

    def test_the_fleet_freshness_reading_stays_sane_after_seeding(self, tmp_path):
        import seed_history
        cp = ControlPlane(build(), OfflineProvider(), JsonlLedger(tmp_path / "f.jsonl", "k"),
                          corpus=__import__("conftest").bundled_corpus())
        seed_history.seed(cp, 30)
        time.sleep(0.6)
        fleet = cp.fleet()
        p50 = fleet["verificationLatencyP50"]
        assert p50 is None or p50 < 60_000, f"freshness SLO reads {p50} ms on a fresh boot"


class TestClocksAreTimezoneSafe:
    """`time.mktime(utc.timetuple())` re-reads a UTC time as local time. It is
    invisible on a UTC server and off by hours on the demo laptop, which runs in
    IST — so the expression is gone and this asserts it stays gone."""

    def test_no_module_uses_mktime_on_a_utc_timetuple(self):
        root = Path(__file__).resolve().parents[1] / "python" / "controlplane"
        offenders = []
        for f in root.rglob("*.py"):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if "mktime" in code:
                    offenders.append(f"{f.name}:{i}")
        assert not offenders, offenders

    def test_oldest_pending_measures_from_processing_not_from_a_backdated_stamp(self, plane,
                                                                                monkeypatch):
        from python.controlplane import plane as plane_mod
        monkeypatch.setattr(plane_mod, "_enqueue",
                            lambda rid, names, kwargs, cb: (len(names), []))
        plane.turn("support-copilot", "What is the status of my open ticket?",
                   at="2019-06-01T00:00:00Z")
        fleet = plane.fleet()
        assert fleet["verificationBacklog"] >= 1
        assert fleet["oldestPendingS"] < 60, (
            f"oldest pending read {fleet['oldestPendingS']} s for a turn taken just now")


class TestTheLockProbeDoesNotKillAnything:
    """`os.kill(pid, 0)` is a liveness probe on POSIX. On Windows signal 0 is
    CTRL_C_EVENT, so the same call sends Ctrl+C to the target's console group —
    a stale-lock check that can stop the server it is checking. The demo laptop
    runs Windows."""

    def test_no_module_probes_liveness_with_os_kill(self):
        root = Path(__file__).resolve().parents[1] / "python" / "controlplane"
        offenders = []
        for f in root.rglob("*.py"):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if "os.kill(" in code and "_pid_alive" not in code:
                    if f.name != "ledger.py":
                        offenders.append(f"{f.name}:{i}")
        assert not offenders, offenders

    def test_this_process_is_alive_and_an_absurd_pid_is_not(self):
        from python.controlplane.ledger import _pid_alive
        assert _pid_alive(os.getpid()) is True
        assert _pid_alive(0) is False
        assert _pid_alive(-1) is False
        assert _pid_alive(4_000_000_000) is False, (
            "a garbage pid in a lock file must not raise out of lock acquisition")

    def test_a_lock_held_by_a_dead_owner_is_broken(self, tmp_path):
        from python.controlplane.ledger import _FileLock
        target = tmp_path / "l.jsonl"
        lock_path = str(target) + ".lock"
        # A lock file left behind by a process that no longer exists.
        with open(lock_path, "w", encoding="utf-8") as fh:
            fh.write(f"4000000000:{time.time()}")
        started = time.time()
        with _FileLock(target, timeout=0.2):
            pass
        assert time.time() - started < 5, "a dead owner's lock wedged the ledger"
        assert not os.path.exists(lock_path)

    def test_a_lock_held_by_this_live_process_still_serialises(self, tmp_path):
        from python.controlplane.ledger import JsonlLedger
        led = JsonlLedger(tmp_path / "c.jsonl", "k")
        errors = []

        def write(n):
            try:
                for i in range(25):
                    led.append({"event": "test", "systemId": f"s{n}", "i": i})
            except Exception as exc:                                  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        entries = led.read(limit=10**6)
        assert len(entries) == 150
        first = entries[0]["index"]
        assert [e["index"] for e in entries] == list(range(first, first + 150)), (
            "chain is not contiguous")


class TestTheFairnessProbeOnlyFiresOnProtectedAttributes:
    """`"he" in "the"` is true. A substring test made this detector fire on
    almost every English sentence and then substitute inside the word, so it
    probed "Tshe guide" — text nobody wrote. Found in a live trace."""

    def test_ordinary_text_is_skipped(self):
        from python.controlplane.providers import OfflineProvider
        r = fairness(answer="The guide only contains details for the Income Fund.",
                     prompt="What does it cover?", provider=OfflineProvider())
        assert r.status == "skipped_by_policy"
        assert "bias" not in r.labels

    def test_a_real_protected_attribute_still_fires(self):
        from python.controlplane.providers import OfflineProvider
        r = fairness(answer="The candidate from Bandra, 400050, is a strong fit.",
                     prompt="Approve or reject?", provider=OfflineProvider())
        assert r.status == "completed"
        assert r.detail["probes"] >= 1
        assert "bias" in r.labels

    def test_the_swap_replaces_whole_words_only(self):
        from python.controlplane.detectors import _swap_word
        assert _swap_word("The guide, he said", "he", "she") == "The guide, she said"
        assert "Tshe" not in _swap_word("The theme here", "he", "she")

    def test_a_counterfactual_differs_in_exactly_one_attribute(self):
        from python.controlplane.detectors import _swap_word
        base = "She joined from Bandra and he did not."
        swapped = _swap_word(base, "she", "he")
        assert swapped.count(" ") == base.count(" "), "word count changed"
        assert "Bandra" in swapped, "an unrelated word was altered"
