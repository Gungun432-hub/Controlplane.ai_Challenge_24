"""The governed decision.

Three guarantees this file exists to keep:

1. The inline deadline is a deadline, not a label. Work that misses it is
   abandoned by the request path and continued on a separate pool.
2. Deferred work amends evidence. It never mutates a response already returned.
3. Absence is explicit. A check that did not run is recorded as not having run,
   and is never priced as if it had returned zero.
"""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable

from .detectors import DETECTORS, DetectorResult, PRIVACY, UNVERIFIABLE
from .registry import Capability, IRREVERSIBLE

# Two pools, deliberately. Python cannot kill a running thread, so abandoned work
# keeps a slot. If it shared the inline pool it would starve the request path and
# the deadline would stop being enforceable under load.
_POOL_LOCK = threading.Lock()
_POOLS: dict[str, ThreadPoolExecutor] = {}
_DEFERRED_Q: queue.Queue = queue.Queue(maxsize=512)

_POOL_SPEC = {"inline": (8, "cp-inline"), "deferred": (4, "cp-deferred")}


def pool(which: str) -> ThreadPoolExecutor:
    """Pools are created on demand and rebuilt after a shutdown.

    They used to be module-level singletons, which meant that once anything
    called shutdown() the process could still serve requests but every
    detector submission raised. A governance runtime that answers without
    checking anything is precisely the failure mode this product exists to
    make impossible, so the pools are now recoverable."""
    ex = _POOLS.get(which)
    if ex is not None:
        return ex
    with _POOL_LOCK:
        ex = _POOLS.get(which)
        if ex is None:
            workers, prefix = _POOL_SPEC[which]
            ex = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=prefix)
            _POOLS[which] = ex
        return ex

PASS, REPAIR, ESCALATE, BLOCK = "pass", "repair", "escalate", "block"


MANDATORY_DEFAULT = {"grounding", "privacy"}


@dataclass
class Profile:
    id: str
    name: str
    thresholds: dict[str, int]
    weights: dict[str, float]
    latency_budget_ms: int
    inline: list[str]
    deferred: list[str]
    hard_gate_actions: list[str] = field(default_factory=list)
    audience: str = "internal"
    mandatory: list[str] = field(default_factory=lambda: sorted(MANDATORY_DEFAULT))
    jurisdiction: str | None = None
    overlay: dict | None = None


PROFILES = {
    "customer_support": Profile("customer_support", "Customer support",
        {"pass": 22, "repair": 40, "escalate": 62}, {"grounding": 1.0, "privacy": 1.2,
        "fairness": 0.8, "cost": 0.4, "purpose": 1.1, "adjudication": 1.0,
        "abstention": 1.2, "certainty": 1.0, "toxicity": 1.4}, 800,
        ["privacy", "grounding", "purpose", "abstention", "certainty", "toxicity"],
        ["fairness", "cost"]),
    "internal_knowledge": Profile("internal_knowledge", "Internal knowledge",
        {"pass": 38, "repair": 58, "escalate": 78}, {"grounding": 1.0, "privacy": 0.9,
        "fairness": 0.5, "cost": 0.9, "purpose": 0.9, "adjudication": 1.0,
        "abstention": 1.2, "certainty": 0.9, "toxicity": 1.4}, 2500,
        ["grounding", "purpose", "abstention", "certainty", "toxicity"],
        ["privacy", "fairness", "cost"]),
    "decision_support": Profile("decision_support", "Decision support",
        {"pass": 12, "repair": 28, "escalate": 44}, {"grounding": 1.2, "privacy": 1.1,
        "fairness": 1.4, "cost": 0.5, "purpose": 1.3, "adjudication": 1.1,
        "abstention": 1.3, "certainty": 1.3, "toxicity": 1.4}, 6000,
        ["grounding", "privacy", "fairness", "purpose", "abstention", "certainty",
         "toxicity"], ["cost"],
        hard_gate_actions=["execute"], audience="external"),
}

JURISDICTIONS = {
    "eu": {"delta": {"pass": 6, "repair": 6, "escalate": 14},
           "weights": {"privacy": 1.3, "fairness": 1.3}, "retention_days": 2555},
    "in": {"delta": {"pass": 3, "repair": 4, "escalate": 4},
           "weights": {"privacy": 1.0}, "retention_days": 1825},
}


def resolve_profile(profile_id: str, jurisdiction: str | None,
                    overlay: dict[str, Any] | None = None) -> Profile:
    """base + jurisdiction overlay + approved control overlay = resolved snapshot.

    Overlays only ever tighten. The base profile is never mutated.
    """
    base = PROFILES.get(profile_id) or PROFILES["customer_support"]
    thresholds = dict(base.thresholds)
    weights = dict(base.weights)
    inline = list(base.inline)
    hard = list(base.hard_gate_actions)

    j = JURISDICTIONS.get((jurisdiction or "").lower())
    if j:
        for key, delta in j["delta"].items():
            thresholds[key] = max(1, thresholds[key] - delta)
        # A jurisdiction raises a weight; it never lowers one. `update()` used to
        # let an overlay *loosen* a base profile — India's privacy weight of 1.0
        # silently relaxed decision_support's 1.1 — which contradicts the
        # guarantee this function claims one line above.
        for key, w in j["weights"].items():
            weights[key] = max(weights.get(key, 0.0), float(w))

    if overlay:
        for key, delta in (overlay.get("tighten") or {}).items():
            if key in thresholds:
                thresholds[key] = max(1, thresholds[key] - int(delta))
        for name in overlay.get("promote_inline") or []:
            if name not in inline:
                inline.append(name)
        if overlay.get("require_human"):
            thresholds["escalate"] = 1
        for name in overlay.get("hard_gate") or []:
            if name not in hard:
                hard.append(name)

    return Profile(base.id, base.name, thresholds, weights, base.latency_budget_ms,
                   inline, [d for d in base.deferred if d not in inline], hard,
                   base.audience, list(base.mandatory), jurisdiction, overlay)


# --------------------------------------------------------------- execution ---
def safe_result(future, name: str, mode: str) -> DetectorResult:
    """A detector future must never be able to take the request down with it."""
    try:
        return future.result(timeout=0)
    except Exception as exc:                                        # noqa: BLE001
        return DetectorResult(name, status="failed", execution_mode=mode,
                              error_code=type(exc).__name__,
                              detail={"message": str(exc)[:200]})


def _run(name: str, kwargs: dict[str, Any], mode: str) -> DetectorResult:
    fn: Callable[..., DetectorResult] | None = DETECTORS.get(name)
    started = time.perf_counter()
    if fn is None:
        return DetectorResult(name, status="not_configured", execution_mode=mode)
    try:
        result = fn(**kwargs)
    except Exception as exc:                                        # noqa: BLE001
        return DetectorResult(name, status="failed", execution_mode=mode,
                              error_code=type(exc).__name__,
                              latency_ms=(time.perf_counter() - started) * 1000,
                              detail={"message": str(exc)[:200]})
    result.execution_mode = mode
    result.latency_ms = (time.perf_counter() - started) * 1000
    return result


def _enqueue(decision_id: str, names: list[str], kwargs: dict[str, Any],
             on_complete: Callable[[str, DetectorResult], None] | None) -> int:
    """Abandoned and deferred work. Bounded, and saturation is visible."""
    queued, dropped = 0, []
    for name in names:
        try:
            _DEFERRED_Q.put_nowait(1)
        except queue.Full:
            dropped.append(name)          # recorded, never silently discarded
            continue
        queued += 1
        enqueued_at = time.perf_counter()

        def task(n: str = name, t0: float = enqueued_at) -> None:
            try:
                res = _run(n, kwargs, "deferred")
                res.queue_delay_ms = (time.perf_counter() - t0) * 1000
                res.status = "completed_async" if res.ran else res.status
                if on_complete:
                    on_complete(decision_id, res)
            finally:
                try:
                    _DEFERRED_Q.get_nowait()
                except queue.Empty:
                    pass

        pool("deferred").submit(task)
    return queued, dropped


def deferred_depth() -> int:
    return _DEFERRED_Q.qsize()


# ----------------------------------------------------------------- scoring ---
def price(results: list[DetectorResult], weights: dict[str, float],
          blast_radius: float) -> dict[str, Any]:
    """Noisy-OR at half weight: a dominant signal sets the floor, the rest raise
    the price without counting one root cause twice. Only detectors that actually
    ran contribute."""
    scored = [r for r in results if r.ran and r.score is not None]
    contributions = {r.detector_id: min(1.0, r.score * weights.get(r.detector_id, 1.0))
                     for r in scored}
    if not contributions:
        return {"price": 0, "pFailure": 0.0, "blastRadius": round(blast_radius, 4),
                "confidence": 0.3, "band": [0, 0], "dominant": None,
                "labels": [], "contributions": {}}

    ordered = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)
    dominant_name, dominant = ordered[0]
    residual = 1.0
    for _, value in ordered[1:]:
        residual *= (1.0 - value)
    residual = 1.0 - residual
    p_failure = dominant + (1.0 - dominant) * 0.5 * residual

    value = int(round(min(100.0, p_failure * blast_radius * 100)))
    confidence = sum(r.confidence or 0.0 for r in scored) / len(scored)
    half = int(round((1.0 - confidence) * 22))
    labels = sorted({lab for r in scored for lab in r.labels})
    return {"price": value, "pFailure": round(p_failure, 4),
            "blastRadius": round(blast_radius, 4), "confidence": round(confidence, 3),
            "band": [max(0, value - half), min(100, value + half)],
            "dominant": dominant_name, "labels": labels,
            "contributions": {k: round(v, 4) for k, v in contributions.items()}}


# ------------------------------------------------------------- governance ---
def governance_status(results: list[DetectorResult], profile: Profile,
                      effective_action: str) -> dict[str, Any]:
    """"We checked and found nothing" is not "we released without checking"."""
    # An ADVISORY detector the policy deliberately defers is scheduled, not
    # missing. A MANDATORY detector that has not completed is not verified —
    # "scheduled" and "verified" are different states, and only the second one
    # can be called fully governed.
    scheduled = ("queued_async",)
    benign = ("skipped_by_policy", "completed_async")

    mandatory_missing, mandatory_pending, advisory_missing = [], [], []
    for r in results:
        if r.ran or r.status in benign:
            continue
        if r.requirement == "mandatory":
            (mandatory_pending if r.status in scheduled else mandatory_missing
             ).append(r.detector_id)
        elif r.status not in scheduled:
            advisory_missing.append(r.detector_id)

    if mandatory_missing:
        status = "ungoverned_due_to_failure" if any(
            r.status in ("failed",) for r in results
            if r.requirement == "mandatory" and r.detector_id in mandatory_missing
        ) else "ungoverned_due_to_timeout"
    elif mandatory_pending:
        # Released, but the record cannot yet claim it was fully checked.
        status = "awaiting_verification"
    elif advisory_missing:
        status = "partially_governed"
    else:
        status = "fully_governed"

    # "It is still running" is not "it came back clean". For an action that
    # cannot be undone, the promise has to be: no completed mandatory check, no
    # action. Counting only outright failures here meant a mandatory detector
    # sitting in the deferred queue let an irreversible action through, with the
    # receipt honestly recording `awaiting_verification` next to a side effect
    # that had already happened.
    fail_closed = (bool(mandatory_missing or mandatory_pending)
                   and effective_action in IRREVERSIBLE)
    return {"status": status, "fullyGoverned": status == "fully_governed",
            "mandatoryMissing": mandatory_missing,
            "mandatoryPending": mandatory_pending,
            "advisoryMissing": advisory_missing, "failClosed": fail_closed}


# ----------------------------------------------------------------- routing ---
def side_effect(action: str, cap: Capability, text: str = "") -> dict[str, Any]:
    """What the world will actually see.

    The gate sits *in front of* the tool call, so a decision is not only a
    verdict on text — for an action that changes something it is the difference
    between the side effect happening and not happening. Making that explicit
    on the receipt is the difference between "the model proposed this" and "this
    was done", which is the distinction an auditor is actually asking about.

    `changesTheWorld` records whether there was a side effect at stake at all.
    A blocked `draft` and a blocked `execute` are not the same event, and a
    receipt that renders them identically is hiding the thing that matters."""
    acts = cap.effective_action in IRREVERSIBLE
    if action == BLOCK:
        return {"state": "withheld",
                "detail": ("the tool call was not issued; the drafted text was returned "
                           "to the developer, not to the audience" if acts and text else
                           "the tool call was not issued" if acts else
                           "no text was released"),
                "textReturnedToDeveloper": bool(acts and text),
                "changesTheWorld": acts}
    if action == ESCALATE:
        # These are two genuinely different things and describing them with one
        # phrase was a contradiction a reviewer caught: the receipt said the
        # text was "held for review before release" while `releasedText` carried
        # it straight to the user.
        #
        # For TEXT, escalate means **released with the finding attached** — that
        # is the product's central claim, that the person who asked is told what
        # is wrong rather than quietly handed it. Withholding it would make this
        # a block by another name.
        #
        # For an ACTION, nothing is released: the tool call waits behind a
        # human approval.
        return {"state": "queued_for_approval" if acts else "released_with_warning",
                "detail": ("the tool call is queued behind a human approval and has "
                           "not been issued" if acts else
                           "the answer was released to the person who asked with the "
                           "finding attached, and a reviewer was notified"),
                "changesTheWorld": acts}
    if action == REPAIR:
        return {"state": "performed_after_repair" if acts else "released_after_repair",
                "detail": ("the tool call was issued with the repaired payload" if acts else
                           "a rewritten answer was released"),
                "changesTheWorld": acts}
    return {"state": "performed" if acts else "released",
            "detail": (f"the '{cap.tool_id}' tool was permitted to act" if acts else
                       "the answer was released unchanged"),
            "changesTheWorld": acts}


def route(answer: str, results: list[DetectorResult], risk: dict[str, Any],
          profile: Profile, cap: Capability, gov: dict[str, Any]) -> dict[str, Any]:
    th = profile.thresholds
    ran = [r for r in results if r.ran]
    unverifiable = any(UNVERIFIABLE in r.labels for r in ran)
    contradiction = any(r.detail.get("contradiction") for r in ran)
    price_value = risk["price"]

    def decision(action: str, reason: str, text: str = "", **extra: Any) -> dict[str, Any]:
        """One rule, enforced here so no caller can get it wrong:

        **`releasedText` is only ever text the person who asked may see.**

        A block that salvages the drafted text carries it as `developerDraft`
        instead. Both used to live in the same field, and the user page rendered
        whatever was in it — so a screen could say "this answer was blocked
        before it reached you" directly underneath the answer it had just shown
        them. Separating the two fields is what makes that impossible rather
        than merely unlikely."""
        released = "" if action == BLOCK else text
        out: dict[str, Any] = {
            "action": action, "reason": reason, "releasedText": released,
            "sideEffect": side_effect(action, cap, text), **extra}
        if action == BLOCK and text:
            out["developerDraft"] = text
        return out

    # 1 · capability refusal — before anything is spent
    if cap.denied:
        # Refused on what the tool is permitted to do, before the score meant
        # anything. Saying "risk price 0" next to this reads as "we found no
        # risk", which is the opposite of what happened.
        return decision(BLOCK, f"capability check refused the request: {cap.denied}",
                        scored=False,
                        detail={"capability": cap.as_dict(),
                                "refusedOn": "capability"})

    # 1b · the answer itself is abusive, or generalises about a group. This is
    # the one finding in the whole system that withholds text rather than
    # releasing it with the finding attached, and the asymmetry is deliberate:
    # everywhere else a warned reader is better served than a blocked one,
    # because the answer might be right. Here there is no version worth
    # releasing. It blocks at any price, on every profile, and the draft is kept
    # for the system's owner rather than shown to the person who asked.
    toxic = next((r for r in ran if r.detail.get("toxicAnswer")), None)
    if toxic is not None:
        return decision(BLOCK,
                        "the answer the model produced contains abusive language or a "
                        "generalisation about a group of people; there is no version of "
                        "that worth releasing with a warning attached",
                        text=answer,
                        surfacedUncertainty="",
                        detail={"floor": "toxic_answer",
                                "family": (toxic.labels[1] if len(toxic.labels) > 1
                                           else "abuse")})

    # 2 · mandatory evidence missing on an irreversible action — fail closed
    if gov["failClosed"]:
        missing = gov["mandatoryMissing"] or gov.get("mandatoryPending") or []
        return decision(BLOCK, "mandatory governance did not complete on an irreversible "
                               f"action ({', '.join(missing)})",
                        scored=False,
                        detail={"governance": gov, "refusedOn": "governance"})

    # 3 · hard gate
    if cap.effective_action in profile.hard_gate_actions and (
            unverifiable or price_value >= th["escalate"]):
        return decision(BLOCK, f"policy declares a hard gate on '{cap.effective_action}' "
                               f"actions and the response is "
                               f"{'unverifiable' if unverifiable else f'priced at {price_value}'}",
                        detail={"hardGate": True})

    # 4 · a declared/effective mismatch on an irreversible action
    if cap.mismatch and cap.effective_action in IRREVERSIBLE:
        # The side effect is refused, but the text itself may be perfectly good.
        # Returning it to the developer as a draft is the difference between a
        # control plane and a wall: the action is denied, the work is not
        # destroyed, and the audience still never sees it.
        return decision(BLOCK, "the application understated what this action does; "
                               f"declared '{cap.declared_action}', binding proves "
                               f"'{cap.effective_action}'. The side effect is refused and "
                               f"the text is downgraded to a draft for a human.",
                        text=answer,
                        scored=False,
                        downgradedTo=cap.declared_action,
                        detail={"capabilityMismatch": True, "reasons": cap.reasons,
                                "refusedOn": "capability"})

    # 5 · approval required
    if cap.approval_required:
        return decision(ESCALATE, "this tool requires human approval before it may act",
                        text=answer, surfacedUncertainty="Awaiting approval.",
                        detail={"approval": "required"})

    # 6a · the car-wash floor. An answer that leaves out a condition in the
    # organisation's own document and then invites the reader to act cannot pass
    # at any price, for exactly the reason a numeric contradiction cannot: it is
    # a fact about the text, not a probability. This is the failure class where
    # every sentence is true and the person is harmed anyway, and pricing alone
    # will never catch it because nothing in the answer is wrong.
    omitted = next((r for r in ran if r.detail.get("omittedCondition")), None)
    if omitted is not None and price_value < th["escalate"]:
        first = (omitted.detail.get("omissions") or [{}])[0]
        return decision(ESCALATE,
                        "the answer leaves out a condition in the source that changes "
                        "what the reader should do; an omission cannot pass at any price",
                        text=answer,
                        surfacedUncertainty=(
                            "Your own policy carries a condition this answer did not "
                            "mention: " + str(first.get("sentence", ""))[:180]),
                        detail={"floor": "omitted_condition",
                                "omission": first})

    # 6a-ii · the objective floor, and the one our mentor's example lands on.
    # Nothing here is false, no document was contradicted, and the person still
    # does not get what they came for. Like the omission above this is a fact
    # about the text — the question named something and the answer never came
    # back to it — so it cannot be priced away either.
    unserved = next((r for r in ran if r.detail.get("purposeUnserved")), None)
    if unserved is not None and price_value < th["escalate"]:
        missed = unserved.detail.get("unservedObjective") or {}
        return decision(ESCALATE,
                        "the answer does not serve something the person said they were "
                        "trying to do; every sentence in it can be true and it is still "
                        "not the answer they needed",
                        text=answer,
                        surfacedUncertainty=str(
                            unserved.detail.get("plainEnglish")
                            or "This answer may not cover everything you asked for."),
                        detail={"floor": "objective_unserved",
                                "unservedObjective": missed})

    # 6a-iii · confidently wrong — the problem statement's own phrase. An answer
    # that makes a flat promise nothing retrieved supports is not merely
    # unsupported: it has told the reader not to check. That is a fact about the
    # text in the same way an omission is, so it does not get to be priced away
    # by four careful sentences around it.
    overconfident = next((r for r in ran if r.detail.get("confidentlyWrong")), None)
    if overconfident is not None and price_value < th["escalate"]:
        worst = (overconfident.detail.get("overbought") or [{}])[0]
        return decision(ESCALATE,
                        "the answer states something as settled that nothing retrieved "
                        "supports; being wrong is survivable, and being confidently "
                        "wrong is what the reader acts on",
                        text=answer,
                        surfacedUncertainty=(
                            "One line here is firmer than the evidence behind it: "
                            + str(worst.get("text", ""))[:180]),
                        detail={"floor": "confidently_wrong",
                                "sentence": worst})

    # 6b · a second opinion was required and never arrived. An unchecked answer
    # is not a cleared answer, so it does not get to take the clean-pass route
    # just because the judge was unreachable.
    judge_failed = any(r.detector_id == "adjudication" and r.status == "failed"
                       and r.requirement == "mandatory" for r in results)
    if judge_failed and price_value < th["escalate"]:
        return decision(ESCALATE,
                        "a second opinion was required on this answer because nothing "
                        "authoritative covers it, and the adjudicator could not be "
                        "reached; an unchecked answer is not a cleared answer",
                        text=answer,
                        surfacedUncertainty="This answer was not independently checked. "
                                            "Treat it as unverified.",
                        detail={"floor": "judge_unavailable"})

    # 6c · contradiction floor — a fact about the text, not a probability
    if contradiction and price_value < th["escalate"]:
        return decision(ESCALATE, "a numeric claim contradicts the source of record; "
                                  "contradictions cannot pass at any price",
                        text=answer,
                        surfacedUncertainty="At least one figure here appears in no "
                                            "retrieved source. Treat it as unconfirmed.",
                        detail={"floor": "contradiction"})

    # 6d · the assistant declined, and that is the system working.
    #
    # An answer in which every sentence is the assistant describing its own
    # limits asserts nothing about the world. There is no claim to ground, no
    # figure to contradict and nothing for a judge to settle — so it must not be
    # dressed up in a warning panel. It still has to clear everything else:
    # nothing here bypasses the capability check, the fail-closed check, the hard
    # gate or the evidence floor, all of which are above this line.
    abstained = next((r for r in ran if r.detector_id == "abstention"), None)
    if (abstained is not None and abstained.detail.get("assertsNothing")
            and not unverifiable and not contradiction
            and price_value < th["escalate"]):
        return decision(PASS,
                        "the assistant declined and asserted nothing that needs a "
                        "source; there is nothing here to verify",
                        text=answer, abstention=True,
                        detail={"abstention": abstained.detail.get("posture"),
                                "declined": abstained.detail.get("declined", 0)})

    # 7 · clean pass
    if price_value < th["pass"] and not unverifiable and not contradiction:
        return decision(PASS, f"risk price {price_value} is below the pass threshold "
                              f"{th['pass']}", text=answer)

    # 8 · deterministic repair
    privacy_dominant = risk["dominant"] == "privacy" or PRIVACY in risk["labels"]
    if privacy_dominant and price_value < th["escalate"]:
        from .detectors import redact
        repaired = redact(answer)
        if repaired != answer:
            return decision(REPAIR, "a validated identifier was present and has a known "
                                    "deterministic fix, so the answer is repaired rather "
                                    "than withheld",
                            text=repaired, repairs=["redact_identifiers"])

    # 9 · above the pass line with nothing named — alert fatigue is a real cost
    if th["pass"] <= price_value < th["escalate"] and not unverifiable and not risk["labels"]:
        return decision(PASS, f"risk price {price_value} is above the pass line but no "
                              f"finding is named; released and sampled asynchronously",
                        text=answer)

    # 10 · block only where the action cannot be undone, and only with margin
    if (price_value >= th["escalate"] and cap.effective_action in IRREVERSIBLE
            and price_value >= th["escalate"] + 15):
        return decision(BLOCK, f"risk price {price_value} on an irreversible "
                               f"'{cap.effective_action}' action",
                        detail={"irreversible": True})

    note = ("No source material covers part of this answer, so it could not be verified "
            "either way." if unverifiable else
            f"Confidence is limited (price {price_value}, band {risk['band'][0]}–"
            f"{risk['band'][1]}). A reviewer has been notified.")
    # Say what actually happened. This line used to read "risk price 48 is at or
    # above the escalate threshold 62" — which is plainly false, and is the kind
    # of sentence that costs you a room. An answer reaches here for one of three
    # different reasons and they deserve three different sentences.
    if unverifiable:
        reason = "response contains unverifiable claims"
    elif price_value >= th["escalate"]:
        reason = (f"risk price {price_value} is at or above the escalate threshold "
                  f"{th['escalate']}")
    else:
        named = ", ".join(risk["labels"]) or "an unnamed finding"
        reason = (f"risk price {price_value} is above the pass threshold "
                  f"{th['pass']} and the response carries {named}")
    return decision(ESCALATE, reason,
                    text=answer, surfacedUncertainty=note, abstained=unverifiable)


REVIEW_MINUTES = {PASS: 0.0, REPAIR: 0.0, ESCALATE: 4.0, BLOCK: 8.0}
INR_PER_1K_TOKENS = 0.85

# What a minute of a human reviewer's attention costs the organisation. This is
# the number almost every AI cost model leaves out, and in a governed deployment
# it dominates: an escalation costs four minutes of somebody's day, which is
# roughly four thousand times the model call that caused it. Kept as a separate
# line from model spend rather than folded into it, because a budget for tokens
# and a budget for attention are held by different people.
INR_PER_REVIEW_MINUTE = 8.0


def shutdown(wait: bool = False) -> None:
    """Stop accepting work and release the pools. Called on application shutdown
    so a reload does not leave workers behind."""
    with _POOL_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for ex in pools:
        ex.shutdown(wait=wait, cancel_futures=True)
