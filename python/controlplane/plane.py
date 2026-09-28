"""The control plane: one governed turn, and the projections built from them.

Order matters here. The agent proposes, the registry decides what the proposal
can actually do, detectors gather evidence under a real deadline, the price is
computed from what actually ran, and only then is a route chosen. The model is
upstream of all of it and authoritative over none of it.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from . import gate
from .adjudicator import (adjudicate, extract_claims, judge_required,
                          should_adjudicate, to_detector)
from .detectors import DetectorResult, redact
from .plain import verdict as plain_verdict
from .supervisors import review as supervisor_review
from .gate import (BLOCK, ESCALATE, INR_PER_1K_TOKENS, INR_PER_REVIEW_MINUTE, PASS,
                   REPAIR, REVIEW_MINUTES, deferred_depth, governance_status, price,
                   resolve_profile, route, _enqueue, _run, pool)
from .providers.base import AgentProposal, ProposalError
from .registry import (ACTION_RADIUS, IRREVERSIBLE, NO_TOOL, Application,
                       Registry, ToolBinding)

RETRIEVAL_TOP_K = 6

# Whether a decision receipt keeps the prompt verbatim. Default on: the receipt
# goes to the ledger, and the ledger is append-only.
REDACT_RECEIPTS = os.getenv("CONTROLPLANE_RECEIPT_RAW_PROMPT") != "1"

# What kind of evidence is behind this answer?
#   A  authoritative  — a chunk of a document the organisation owns
#   B  system_of_record — a live lookup, verifiable at query time (adapter)
#   C  parametric     — the model's own memory. Unverifiable by construction.
TIER_A, TIER_B, TIER_C = "authoritative", "system_of_record", "parametric"

# An irreversible action may not rest on the model's memory. Ever.
REQUIRED_TIER = {"read": TIER_C, "draft": TIER_C, "advise": TIER_B,
                 "decide": TIER_A, "execute": TIER_A}
_TIER_RANK = {TIER_C: 0, TIER_B: 1, TIER_A: 2}


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def evidence_tier(sources: list[str], retrieval: dict[str, Any]) -> dict[str, Any]:
    """Grade the evidence, and say plainly when there is none."""
    if sources:
        return {"tier": TIER_A, "label": "authoritative",
                "detail": f"{len(sources)} chunk(s) from documents this system owns",
                "citedChunks": len(sources)}
    if retrieval.get("hits"):
        return {"tier": TIER_C, "label": "parametric",
                "detail": f"{retrieval['hits']} relevant chunk(s) were retrieved and "
                          f"the agent cited none of them; the answer rests on the "
                          f"model's own memory",
                "citedChunks": 0}
    return {"tier": TIER_C, "label": "parametric",
            "detail": "no supporting document was found for this question; the answer "
                      "rests on the model's own memory and cannot be verified",
            "citedChunks": 0}


def tier_satisfied(tier: str, action: str) -> bool:
    need = REQUIRED_TIER.get(action, TIER_A)
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK.get(need, 2)


EMPTY_RISK = {"price": 0, "pFailure": 0.0, "blastRadius": 0.0,
              "confidence": 0.0, "band": [0, 0], "dominant": None,
              "labels": [], "contributions": {}}

TERNARY = ("governed", "breaching", "unknown")


# How long a reviewer's week is, and where a billing month starts. Both stated
# once, here, because the bug they fix was a labelling bug: the cards said "this
# month" and "reviewer time" while the numbers behind them summed every decision
# the process had ever seen. On a long-running instance that quietly turns
# history into current usage, and every percentage, forecast and piece of owner
# advice downstream inherits the error.
REVIEW_WINDOW_S = 7 * 24 * 3600


def _period_bounds(now: float | None = None) -> tuple[float, float]:
    """(start of the current UTC billing month, start of the rolling 7 days)."""
    now = now if now is not None else time.time()
    stamp = datetime.fromtimestamp(now, tz=timezone.utc)
    month_start = stamp.replace(day=1, hour=0, minute=0, second=0,
                                microsecond=0).timestamp()
    return month_start, now - REVIEW_WINDOW_S


def verification_summary(results: list[Any], tier: dict[str, Any],
                         retrieval: dict[str, Any],
                         adjudication: dict[str, Any] | None) -> dict[str, Any]:
    """One authoritative answer to "was this checked, and what came back?"

    This exists because of the worst inconsistency our reviewers found, and it
    was on screen in four separate screenshots:

        ✓ grounded in 1 source
        Accuracy: 0 of 2 claims supported by 1 source(s)

    Both lines were true and together they were a lie. The first counted
    **citations**; the second counted **verification**. Finding a source is not
    the same act as checking a claim against it, and a product whose whole
    argument is "we tell you what is wrong rather than quietly handing it to
    you" cannot afford to blur them.

    So the receipt now carries one block, computed once, that every surface
    renders — and it distinguishes all five states that actually occur:
    nothing was asserted, everything checked out, something is contradicted,
    something is simply not settled by anything we hold, and nothing was
    checked at all."""
    grounding = next((r for r in results if r.detector_id == "grounding"), None)
    adj = adjudication or {}
    detail = (grounding.detail if grounding is not None else {}) or {}

    cited = int((tier or {}).get("citedChunks", 0) or 0)
    retrieved = int((retrieval or {}).get("hits", 0) or 0)
    total = int(detail.get("claims", 0) or 0)
    supported = int(detail.get("claimsSupported", 0) or 0)
    contradicted = len(detail.get("numericContradictions") or [])
    unsettled = max(0, total - supported)
    abstained = bool(detail.get("abstention"))

    # The judge is a second reader on exactly the claims the lexical check could
    # not settle, so its verdicts refine these counts rather than replacing them.
    judged = bool(adj.get("ran"))
    if judged:
        verdicts = [v for v in (adj.get("verdicts") or []) if v.get("needsEvidence")]
        if verdicts:
            contradicted = max(contradicted, sum(
                1 for v in verdicts if v.get("verdict") == "contradicted"))
            unsettled = max(unsettled, sum(
                1 for v in verdicts if v.get("verdict") == "uncovered"))
            total = max(total, len(verdicts))
            supported = max(0, total - unsettled - contradicted)

    if grounding is None or not grounding.ran:
        status = "not_checked"
        label = "this answer was not checked"
    elif abstained or total == 0:
        status = "nothing_asserted"
        label = "the assistant declined — nothing was asserted, so there is nothing to verify"
    elif contradicted:
        status = "contradicted"
        label = (f"{contradicted} claim(s) contradict the source of record")
    elif unsettled and supported:
        status = "partly_verified"
        label = (f"{supported} of {total} claims check out against our documents; "
                 f"{unsettled} is not settled by anything we hold"
                 if unsettled == 1 else
                 f"{supported} of {total} claims check out against our documents; "
                 f"{unsettled} are not settled by anything we hold")
    elif unsettled:
        status = "unverified"
        label = (f"none of the {total} claim(s) here are settled by anything we hold"
                 if total > 1 else
                 "the claim here is not settled by anything we hold")
    else:
        status = "verified"
        label = (f"all {total} claim(s) check out against the documents cited"
                 if total else "nothing to verify")

    return {"status": status, "label": label,
            "sourcesCited": cited, "sourcesRetrieved": retrieved,
            "claimsTotal": total, "claimsSupported": supported,
            "claimsContradicted": contradicted, "claimsUnsettled": unsettled,
            "abstained": abstained,
            "secondOpinion": judged,
            "evidenceTier": (tier or {}).get("tier", ""),
            # Said plainly, because "we retrieved six documents" has been read as
            # "we verified this answer" by every reviewer who has seen it.
            "sourcesNote": (f"{cited} source(s) cited out of {retrieved} retrieved — "
                            f"finding a source is not the same as checking a claim "
                            f"against it")}


def _occurred_at(record: dict[str, Any]) -> float:
    """When this decision *happened*, in business time.

    Deliberately not `processedAtEpochS`, which is real wall-clock and exists so
    verification latency is measured from when work actually ran. Seeded history
    is backdated across fourteen days: attributing all of it to the moment the
    process started would drop every seeded decision into "this week", which is
    exactly the mislabelling the period windows are there to prevent. Two
    clocks, two jobs — the same discipline we already apply to decision latency
    versus verification latency."""
    raw = record.get("occurredAtEpochS")
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    created = record.get("createdAt")
    if isinstance(created, str) and created:
        try:
            return datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return _processed_at(record)


def _processed_at(record: dict[str, Any]) -> float:
    """Real wall-clock epoch seconds for when this decision was processed."""
    started = record.get("processedAtEpochS")
    if started is not None:
        return float(started)
    try:
        # `.timestamp()` on a tz-aware datetime. Never mktime(timetuple()),
        # which discards the offset and re-reads the value as local time.
        return datetime.fromisoformat(
            record["createdAt"].replace("Z", "+00:00")).timestamp()
    except Exception:                                                # noqa: BLE001
        return time.time()


def _detector_from_dict(d: dict[str, Any]) -> DetectorResult:
    """Rebuild a recorded detector result so it can be re-priced under another
    policy. The evidence is fixed; only the arithmetic over it changes."""
    return DetectorResult(
        detector_id=d.get("detectorId", "?"), score=d.get("score"),
        confidence=d.get("confidence"), status=d.get("status", "completed"),
        execution_mode=d.get("executionMode", "inline"),
        latency_ms=d.get("latencyMs", 0.0) or 0.0,
        labels=list(d.get("labels") or []), evidence=list(d.get("evidence") or []),
        detail=dict(d.get("detail") or {}), error_code=d.get("errorCode"),
        requirement=d.get("requirement", "advisory"))


def _cap_from(d: dict[str, Any]):
    from .registry import Capability
    return Capability(d.get("declaredAction", "advise"), d.get("effectiveAction", "advise"),
                      d.get("blastRadius", 0.0), d.get("capabilityMismatch", False),
                      d.get("reversible", True), d.get("approvalRequired", False),
                      d.get("denied"), list(d.get("reasons", [])),
                      d.get("capabilitySnapshotHash", ""))


def profile_from_snapshot(snap: dict[str, Any] | None):
    """Rebuild the exact profile a decision was made under. Never re-resolve from
    current policy — that is how a record silently changes meaning."""
    from .gate import Profile, resolve_profile
    if not snap:
        return resolve_profile("customer_support", None)
    return Profile(snap.get("id", "customer_support"), snap.get("id", ""),
                   dict(snap.get("thresholds", {})), dict(snap.get("weights", {})),
                   int(snap.get("latencyBudgetMs", 800)), list(snap.get("inline", [])),
                   list(snap.get("deferred", [])), list(snap.get("hardGateActions", [])),
                   snap.get("audience", "internal"), list(snap.get("mandatory", [])),
                   snap.get("jurisdiction"), snap.get("overlay"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Overlay:
    id: str
    system_id: str
    kind: str
    payload: dict[str, Any]
    reason: str
    rule_id: str | None = None
    requested_by: str = "supervisor"
    approved_by: str | None = None
    created_at: str = field(default_factory=_now)
    expires_at: float = field(default_factory=lambda: time.time() + 3600)
    rollback_of: str | None = None
    active: bool = True
    rolled_back_at: float | None = None
    version: int = 1
    expected_effect: dict[str, Any] = field(default_factory=dict)
    observed_effect: dict[str, Any] = field(default_factory=dict)

    @property
    def live(self) -> bool:
        return self.active and time.time() < self.expires_at

    @property
    def ended_at(self) -> float | None:
        """When this control stopped applying — rolled back, or simply expired."""
        if self.rolled_back_at is not None:
            return min(self.rolled_back_at, self.expires_at)
        return None if self.live else self.expires_at

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "systemId": self.system_id, "kind": self.kind,
                "payload": self.payload, "reason": self.reason, "ruleId": self.rule_id,
                "requestedBy": self.requested_by, "approvedBy": self.approved_by,
                "createdAt": self.created_at,
                "expiresAtUtc": datetime.fromtimestamp(self.expires_at, timezone.utc
                                                       ).isoformat().replace("+00:00", "Z"),
                "expiresInS": max(0, round(self.expires_at - time.time())),
                "active": self.live, "version": self.version,
                "expectedEffect": self.expected_effect,
                "observedEffect": self.observed_effect}


class ControlPlane:
    def __init__(self, registry: Registry, provider: Any, ledger: Any = None, corpus: Any = None) -> None:
        self.registry = registry
        self.provider = provider
        self.ledger = ledger
        # The evidence layer. Documents in, citable chunks out.
        from .ingest import Corpus
        self.corpus = corpus or Corpus(os.getenv("CORPUS_PATH", "data/corpus"))
        # Subject scope, derived from the corpus rather than hand-written, so an
        # assistant's remit follows the evidence its owner gave it. Rebuilt on
        # every ingest; see `rebuild_scope`.
        from .scope import ScopeIndex
        self.scope = ScopeIndex()
        # Questions stopped at ingress, waiting on a human.
        self.held: dict[str, dict[str, Any]] = {}
        self.chats: dict[str, list[dict[str, Any]]] = {}
        self.decisions: deque[dict[str, Any]] = deque(maxlen=4000)
        self.by_id: dict[str, dict[str, Any]] = {}
        self.overlays: list[Overlay] = []
        self.recommendations: list[dict[str, Any]] = []
        self.last_seen: dict[str, float] = {}
        self.ledger_errors: list[dict[str, Any]] = []
        self.dropped_verification: list[dict[str, Any]] = []
        # Questions turned away at the subject-scope gate. Zero tokens each, and
        # worth counting: a system being asked the wrong questions all day is a
        # fact its owner needs, not something to discard silently.
        self.redirected: deque[dict[str, Any]] = deque(maxlen=200)
        # Questions refused because the department has no reviewer capacity left
        # this week. Zero tokens, and the owner can lift it in one click.
        self.capacity_refusals: deque[dict[str, Any]] = deque(maxlen=200)
        # Reviewer minutes held for questions currently in flight, so concurrent
        # requests cannot each pass the same pre-flight check.
        self._reserved: dict[str, float] = {}
        self._reserved_spend: dict[str, float] = {}
        # Questions refused before the model because they asked for help harming
        # somebody. A governance incident, unlike a wrong-assistant redirect.
        self.harm_refusals: deque[dict[str, Any]] = deque(maxlen=200)
        # Questions refused because they are personal errands rather than work.
        # Counted, not filed: a routing mistake, not a governance incident — but
        # a work assistant used as a personal one all day is a fact its owner
        # needs and an auditor will ask about.
        self.out_of_purpose: deque[dict[str, Any]] = deque(maxlen=200)
        self._lock = threading.Lock()
        self._seq = 0
        self._rec_seq = 0
        self.rebuild_scope()

    def rebuild_scope(self) -> dict[str, Any]:
        """Re-derive every system's signature vocabulary from what it now holds.

        Called at boot and after every upload or deletion, because a scope check
        that lags the corpus is worse than none: it refuses questions the
        organisation has just published the answer to."""
        return self.scope.build(self.corpus, self.registry)

    # ------------------------------------------------------------- recovery ---
    def recover(self) -> dict[str, Any]:
        """Rebuild state from the ledger. The ledger is authoritative; everything
        held in memory is a projection of it, and must be able to prove it."""
        if self.ledger is None:
            return {"recovered": 0, "source": "none"}
        try:
            entries = self.ledger.read(limit=10 ** 7)
        except Exception as exc:                                     # noqa: BLE001
            self.ledger_errors.append({"at": _now(), "event": "recover",
                                       "error": f"{type(exc).__name__}: {exc}"[:200]})
            return {"recovered": 0, "source": "error"}

        decisions, overlays, rolled, amendments = 0, {}, set(), {}
        held_restored = 0
        chats_restored = 0
        budgets: dict[str, dict[str, float]] = {}
        owners: dict[str, dict[str, str]] = {}
        with self._lock:
            for entry in entries:
                rec = entry.get("record") or {}
                kind = rec.get("event")
                if kind == "decision.issued" and isinstance(rec.get("receipt"), dict):
                    receipt = rec["receipt"]
                    receipt["ledgerIndex"] = entry.get("index")
                    receipt["ledgerHash"] = entry.get("hash")
                    self.decisions.append(receipt)
                    self.by_id[receipt["requestId"]] = receipt
                    self._seq = max(self._seq, int(receipt.get("sequence") or 0))
                    try:
                        seen = datetime.fromisoformat(
                            receipt["createdAt"].replace("Z", "+00:00")).timestamp()
                    except Exception:                                # noqa: BLE001
                        seen = 0.0
                    self.last_seen[receipt["systemId"]] = max(
                        self.last_seen.get(receipt["systemId"], 0.0), seen)
                    decisions += 1
                elif kind == "control.applied":
                    overlays[rec.get("id")] = rec
                elif kind == "control.rolled_back":
                    rolled.add(rec.get("overlayId"))
                elif kind == "budget.changed":
                    # Last write wins, and it is replayed from the ledger rather
                    # than lost on restart. An operator action with no receipt is
                    # exactly the hole this product exists to close.
                    sid = rec.get("systemId")
                    if sid:
                        budgets[sid] = {"budgetInr": rec.get("budgetInr"),
                                        "reviewMinutesWeek": rec.get("reviewMinutesWeek")}
                elif kind == "owner.changed":
                    sid = rec.get("systemId")
                    if sid:
                        owners[sid] = {"owner": rec.get("owner"),
                                       "ownerEmail": rec.get("ownerEmail")}
                elif kind == "recommendation.created" and isinstance(
                        rec.get("recommendation"), dict):
                    r = rec["recommendation"]
                    self.recommendations.append(r)
                    try:
                        self._rec_seq = max(self._rec_seq,
                                            int(str(r.get("id", "0")).split("_")[-1]))
                    except Exception:                                # noqa: BLE001
                        pass
                elif kind == "verification.completed" and isinstance(
                        rec.get("amendment"), dict):
                    amendments[rec["amendment"].get("requestId")] = rec["amendment"]
                elif kind == "question.held" and rec.get("heldId"):
                    self.held[rec["heldId"]] = {
                        "id": rec["heldId"], "systemId": rec.get("systemId"),
                        "system": rec.get("system") or rec.get("systemId"),
                        "department": rec.get("department", "-"),
                        "user": rec.get("user", "someone"),
                        "sessionId": rec.get("sessionId", ""),
                        "question": rec.get("questionRedacted", "(not recorded)"),
                        "askedAt": rec.get("askedAt") or entry.get("timestamp", ""),
                        "status": "held" if rec.get("route") == "hold" else "refused",
                        "ingress": rec.get("ingress") or {"findings": [], "intent":
                                                          rec.get("intent", ""),
                                                          "latencyMs": 0},
                        "severity": rec.get("severity", "medium"),
                        "toolHint": None, "amountInr": None,
                        "reviewedBy": None, "reviewedAt": None, "reviewNote": "",
                        "requestId": None,
                        # Said on the card, so nobody reads a redacted question
                        # as the exact text the person typed.
                        "restored": True}
                    held_restored += 1
                elif kind == "question.reviewed" and rec.get("heldId") in self.held:
                    item = self.held[rec["heldId"]]
                    item["reviewedBy"] = rec.get("actor")
                    item["reviewNote"] = rec.get("note", "")
                    item["status"] = ("released" if rec.get("decision") == "pass"
                                      else "blocked")
                elif kind == "chat.turn" and rec.get("sessionId"):
                    turns = self.chats.setdefault(rec["sessionId"], [])
                    turns.append({
                        "at": rec.get("at") or entry.get("timestamp", ""),
                        "systemId": rec.get("systemId"),
                        "user": rec.get("user", "someone"),
                        "question": rec.get("questionRedacted", "(not recorded)"),
                        "outcome": dict(rec.get("outcome") or {}),
                        "restored": True})
                    del turns[:-80]
                    chats_restored += 1
                elif kind == "question.redirected":
                    self.redirected.append({
                        "at": entry.get("timestamp", ""),
                        "systemId": rec.get("systemId"), "user": rec.get("user", ""),
                        "to": rec.get("to"), "toName": rec.get("toName", ""),
                        "question": rec.get("questionRedacted", "(not recorded)"),
                        "sessionId": "", "epochS": 0.0})
            # C3: the sealed verification result is reapplied, so a recovered
            # record is the FINAL record, not just the release record.
            for sid, b in budgets.items():
                app = self.registry.get(sid)
                if app is None:
                    continue
                if b.get("budgetInr") is not None:
                    app.budget_inr_month = float(b["budgetInr"])
                if b.get("reviewMinutesWeek") is not None:
                    app.review_minutes_week = float(b["reviewMinutesWeek"])
            for sid, o in owners.items():
                app = self.registry.get(sid)
                if app is None:
                    continue
                if o.get("owner"):
                    app.owner = o["owner"]
                if o.get("ownerEmail") is not None:
                    app.owner_email = o["ownerEmail"]
            for rid, am in amendments.items():
                rec = self.by_id.get(rid)
                if rec:
                    rec.update(am)
            for oid, data in overlays.items():
                if oid in rolled or not data:
                    continue
                # Absolute, from the persisted timestamp. A relative countdown
                # would silently extend every control at every restart.
                raw = data.get("expiresAtUtc")
                if raw:
                    expires = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
                else:
                    expires = time.time() + max(0, int(data.get("expiresInS") or 0))
                if expires <= time.time():
                    continue
                o = Overlay(oid, data.get("systemId", ""), data.get("kind", ""),
                            data.get("payload", {}), data.get("reason", ""),
                            rule_id=data.get("ruleId"),
                            approved_by=data.get("approvedBy"), expires_at=expires,
                            version=int(data.get("version") or 1))
                self.overlays.append(o)
        return {"recovered": decisions, "budgets": len(budgets),
                "owners": len(owners), "overlays": len(self.overlays),
                # Work waiting on a human survives a restart now. An empty queue
                # has to mean "nothing to do", not "the process was restarted".
                "heldQuestions": held_restored,
                "openForReview": sum(1 for h in self.held.values()
                                     if h["status"] in ("held", "refused")),
                "redirects": len(self.redirected),
                "chatTurns": chats_restored,
                "chatSessions": len(self.chats),
                "ledgerUnreadableLines": getattr(self.ledger, "unreadable", 0),
                "source": "ledger", "sequence": self._seq}

    # ------------------------------------------------------------- overlays ---
    STATE_BY_KIND = {"suspend": "suspended", "quarantine": "quarantined",
                     "tool_restricted": "tool_restricted"}
    RECOVERING_WINDOW_S = 900.0

    def state_of(self, system_id: str) -> str:
        """Derived from live controls, never cached.

        It used to be an attribute written when a control was applied and never
        unwritten. When the TTL expired, traffic started flowing again — the gate
        reads `live` — while the console still showed the system suspended and
        red. The runtime and the picture of the runtime disagreed, which is the
        one failure mode this product cannot have."""
        mine = [o for o in self.overlays if o.system_id == system_id]
        live_kinds = {o.kind for o in mine if o.live}
        for kind, label in self.STATE_BY_KIND.items():
            if kind in live_kinds:
                return label
        ended = [o.ended_at for o in mine
                 if o.kind in self.STATE_BY_KIND and not o.live and o.ended_at is not None]
        if ended and (time.time() - max(ended)) <= self.RECOVERING_WINDOW_S:
            return "recovering"
        app = self.registry.get(system_id)
        return "healthy" if app else "unregistered"

    def overlay_for(self, system_id: str) -> dict[str, Any] | None:
        live = [o for o in self.overlays if o.system_id == system_id and o.live]
        if not live:
            return None
        merged: dict[str, Any] = {}
        for o in sorted(live, key=lambda x: x.version):
            for key, value in o.payload.items():
                if isinstance(value, dict):
                    merged.setdefault(key, {}).update(value)
                elif isinstance(value, list):
                    merged.setdefault(key, []).extend(value)
                else:
                    merged[key] = value
        return merged

    # ----------------------------------------------------------------- ask ---
    def ask(self, system_id: str, message: str, *, session_id: str = "",
            user: str = "user", tool_hint: str | None = None,
            amount_inr: float | None = None) -> dict[str, Any]:
        """A person asks a question. The entry point the user page calls.

        Two gates, not one. The question is checked *before* the model is called,
        which is the only point at which a bad prompt costs nothing — and the
        only point at which pasted personal data can be stopped from reaching a
        third-party provider at all. Whatever survives that goes through the
        ordinary decision path, where the answer is checked."""
        from .ingress import ALLOW, HOLD, inspect

        app = self.registry.get(system_id)
        if app is None:
            raise ValueError(f"unknown system '{system_id}'")

        # ---- Gate zero: is this a request to harm somebody? -------------
        #
        # Before capacity, before ingress, before scope, before the model. The
        # case that put it here was real and the screenshot is in our review
        # folder: *"I hate my customer. How do I irritate him step by step?"*
        # The model refused, and refused well — but by then we had paid for the
        # call, and the control plane's whole argument is that the cheapest
        # governance runs before you pay for anything.
        from .harm import inspect as harm_inspect, message as harm_message

        harm = harm_inspect(message, blocklist=list(app.blocked_terms))
        if harm.refuse:
            out = {"status": "refused_harmful", "systemId": system_id,
                   "tokensSpent": 0, "harm": harm.as_dict(),
                   "detail": harm_message(harm, app.name)}
            with self._lock:
                self.harm_refusals.append({
                    "at": _now(), "systemId": system_id, "system": app.name,
                    "user": user, "family": harm.family,
                    "question": redact(message)[:200], "epochS": time.time(),
                    "matched": harm.findings[0].matched if harm.findings else ""})
            self._event("question.refused_harmful", system_id, {
                "user": user, "family": harm.family,
                "questionSha256": _sha(message),
                "questionRedacted": redact(message),
                "matched": [f.as_dict() for f in harm.findings],
                "latencyMs": round(harm.latency_ms, 3)})
            self._append_chat(session_id, system_id, user, message, out)
            return out

        # ---- Gate zero-b: is this anybody's business here? ----------------
        #
        # Different boundary from the three around it. Ingress asks whether the
        # question is an attack; the harm gate asks whether it is a request to
        # hurt somebody; subject scope asks whether it is *another department's*
        # subject. A birthday invite is none of those — it belongs to no corpus
        # anywhere, which scores `uncovered` everywhere and is deliberately let
        # through. So it was answered, from an unrelated line of the refunds SOP.
        #
        # This enforces the **declared purpose** boundary instead: every
        # application here is registered to do a job. It is a routing refusal,
        # not a governance incident — nobody is accused of anything and nothing
        # reaches a reviewer — and it costs zero tokens. See `personal.py`.
        from .personal import inspect as personal_inspect, message as personal_message

        purpose_check = personal_inspect(message)
        if purpose_check.out_of_purpose:
            out = {"status": "out_of_purpose", "systemId": system_id,
                   "tokensSpent": 0, "purposeCheck": purpose_check.as_dict(),
                   "detail": personal_message(purpose_check, app.name,
                                              app.department)}
            with self._lock:
                self.out_of_purpose.append({
                    "at": _now(), "systemId": system_id, "system": app.name,
                    "user": user, "family": purpose_check.family,
                    "label": purpose_check.label,
                    "question": redact(message)[:200], "epochS": time.time(),
                    "matched": purpose_check.matched})
            self._event("question.out_of_purpose", system_id, {
                "user": user, "family": purpose_check.family,
                "questionSha256": _sha(message),
                "questionRedacted": redact(message),
                "matched": purpose_check.matched,
                "latencyMs": round(purpose_check.latency_ms, 3)})
            self._append_chat(session_id, system_id, user, message, out)
            return out

        # ---- Gate one: can this department afford another question? -------
        #
        # Check and reserve in one atomic operation — see `admit()` for why
        # doing those separately was a cap you could walk through by arriving
        # at the same time as somebody else.
        verdict = self.admit(system_id)
        if not verdict["admitted"]:
            out = {"status": ("capacity_exhausted"
                              if verdict["reason"] == "review_capacity"
                              else "budget_exhausted"),
                   "systemId": system_id, "tokensSpent": 0,
                   "capacity": verdict.get("capacity"),
                   "spend": verdict.get("spend")}
            with self._lock:
                self.capacity_refusals.append({
                    "at": _now(), "systemId": system_id, "system": app.name,
                    "user": user, "question": redact(message)[:160],
                    "reason": verdict["reason"],
                    "usedPct": (verdict.get("capacity") or verdict.get("spend")
                                or {}).get("usedPct", 0),
                    "epochS": time.time()})
            self._event("question.refused_no_budget", system_id, {
                "user": user, "reason": verdict["reason"],
                "questionSha256": _sha(message)})
            self._append_chat(session_id, system_id, user, message, out)
            return out
        hold = verdict["hold"]

        ing = inspect(message, system_id=system_id,
                      allowed_intents=list(app.allowed_intents) or None,
                      allow_prompt_pii=app.allow_prompt_pii)

        if ing.route == ALLOW:
            # Second gate, still before a single token: is this question even
            # this assistant's business? Intent and subject are different
            # questions — "what is Chipotle's share price" is a perfectly
            # ordinary lookup and still has no business being answered by a
            # food-delivery bot. The answer comes from the corpus, not a list.
            scope_verdict = self.scope.check(system_id, message)
            if not scope_verdict.allowed:
                self.release(hold)
                out = {"status": "redirected", "ingress": ing.as_dict(),
                       "scope": scope_verdict.as_dict(), "systemId": system_id,
                       "tokensSpent": 0,
                       "redirectTo": scope_verdict.best_other,
                       "redirectName": scope_verdict.best_other_name}
                with self._lock:
                    self.redirected.append({
                        "at": _now(), "systemId": system_id, "user": user,
                        "to": scope_verdict.best_other, "toName": scope_verdict.best_other_name,
                        "question": message[:160], "sessionId": session_id,
                        "epochS": time.time()})
                self._event("question.redirected", system_id, {
                    "user": user, "to": scope_verdict.best_other,
                    "toName": scope_verdict.best_other_name,
                    "questionRedacted": redact(message),
                    "questionSha256": _sha(message),
                    "matched": scope_verdict.foreign_matched[:6],
                    "scopeScore": round(scope_verdict.score, 4),
                    "otherScore": round(scope_verdict.best_other_score, 4)})
                self._append_chat(session_id, system_id, user, message, out)
                return out

            # A question a person actually typed is interactive work: it goes to
            # the live model where one is configured. Seeded history and ambient
            # traffic do not, so the dashboards cost nothing and cannot fail.
            interactive = getattr(self.provider, "interactive", None)
            if interactive is not None:
                with interactive(True):
                    record = self.turn(system_id, message, tool_hint=tool_hint,
                                       amount_inr=amount_inr, origin="user",
                                       scope=scope_verdict, hold=hold)
            else:
                record = self.turn(system_id, message, tool_hint=tool_hint,
                                   amount_inr=amount_inr, origin="user",
                                   scope=scope_verdict, hold=hold)
            out = {"status": "answered", "ingress": ing.as_dict(),
                   "scope": scope_verdict.as_dict(),
                   "requestId": record["requestId"], "decision": record["decision"],
                   # Which provider actually spoke, carried to the user page.
                   # Not a debugging detail: an answer from the deterministic
                   # stand-in must never look like an answer from the model.
                   "answeredBy": record.get("answeredBy") or {},
                   # Carried across from the full receipt, never recomputed here.
                   # This reply is a trimmed view of the record, and recomputing
                   # the wording from the trimmed view produced a second, milder
                   # verdict for the same decision — "there was nothing in your
                   # own documents to check this against" on a decision whose
                   # receipt said "it points at 3 of your own documents". Two
                   # verdicts for one decision is the exact failure plain.py was
                   # written to end.
                   "plain": record.get("plain"),
                   "systemId": system_id}
            self._append_chat(session_id, system_id, user, message, out)
            return out

        # Held at ingress: nothing will be generated, so give the budget back.
        self.release(hold)
        held_id = f"hq_{uuid.uuid4().hex[:8]}"
        held = {
            "id": held_id, "systemId": system_id, "system": app.name,
            "department": app.department, "user": user, "sessionId": session_id,
            "question": message, "askedAt": _now(),
            "status": "held" if ing.route == HOLD else "refused",
            "ingress": ing.as_dict(),
            "severity": ("high" if any(f.severity == "high" for f in ing.findings)
                         else "medium"),
            "toolHint": tool_hint, "amountInr": amount_inr,
            "reviewedBy": None, "reviewedAt": None, "reviewNote": "",
            "requestId": None,
        }
        with self._lock:
            self.held[held_id] = held
        self._event("question.held", system_id, {
            "heldId": held_id, "user": user, "route": ing.route,
            "checks": [f.check for f in ing.findings],
            "intent": ing.intent, "questionSha256": _sha(message),
            "ingressLatencyMs": round(ing.latency_ms, 3),
            # Enough to rebuild the reviewer's queue after a restart, and no
            # more. The queue used to live only in memory, so a process restart
            # silently emptied a page that tells a human there is work waiting —
            # and the honest reading of an empty queue is "nothing to do", which
            # was false.
            #
            # The text is written REDACTED, deterministically, by the same
            # routine the repair route uses. A held question is very often held
            # precisely because somebody pasted a card number into it; persisting
            # that verbatim to an append-only log that is never rewritten would
            # be creating the exact problem the privacy detector exists to stop.
            # The reviewer sees what the question was about, the digest above
            # still proves which question it was, and the identifier never lands
            # on disk.
            "questionRedacted": redact(message),
            "system": app.name, "department": app.department,
            "severity": held["severity"], "askedAt": held["askedAt"],
            "sessionId": session_id, "ingress": ing.as_dict()})

        out = {"status": held["status"], "heldId": held_id,
               "ingress": ing.as_dict(), "systemId": system_id,
               "tokensSpent": 0}
        self._append_chat(session_id, system_id, user, message, out)
        return out

    def _append_chat(self, session_id: str, system_id: str, user: str,
                     message: str, outcome: dict[str, Any]) -> None:
        # Every outcome carries its own plain-English verdict, including the ones
        # that never reached a model — a refusal, a redirect and a paused budget
        # are the outcomes a colleague is *most* likely to misread, so they are
        # the last place to leave the wording to a page's JavaScript.
        if isinstance(outcome, dict) and not outcome.get("plain"):
            try:
                outcome["plain"] = plain_verdict(outcome)
            except Exception:                                        # noqa: BLE001
                # A phrasing helper must never be able to lose somebody's turn.
                outcome["plain"] = {"headline": "", "because": [], "doThis": "",
                                    "register": ""}
        if not session_id:
            return
        # A transcript is the only place a person can see what happened to their
        # own question. Keeping it solely in memory meant a restart silently
        # emptied it while the decisions it referred to survived — so the user
        # page went blank and the receipts it linked to did not. Written
        # redacted, like everything else that persists.
        self._event("chat.turn", system_id, {
            "sessionId": session_id, "user": user,
            "questionRedacted": redact(message),
            "outcome": {k: outcome.get(k) for k in
                        ("status", "requestId", "heldId") if outcome.get(k)},
            "at": _now()})
        with self._lock:
            turns = self.chats.setdefault(session_id, [])
            turns.append({"at": _now(), "systemId": system_id, "user": user,
                          "question": message, "outcome": outcome})
            del turns[:-80]

    def chat(self, session_id: str) -> list[dict[str, Any]]:
        """The conversation, with each turn resolved to its current state.

        A question that was held and has since been released shows its answer
        here without the user doing anything — which is the point of the review
        loop closing."""
        out = []
        for turn in list(self.chats.get(session_id, [])):
            item = dict(turn)
            outcome = dict(item["outcome"])
            held_id = outcome.get("heldId")
            if held_id and held_id in self.held:
                held = self.held[held_id]
                outcome["status"] = ("answered" if held.get("requestId")
                                     else held["status"])
                outcome["reviewNote"] = held.get("reviewNote", "")
                outcome["reviewedBy"] = held.get("reviewedBy")
                if held.get("requestId"):
                    outcome["requestId"] = held["requestId"]
            rid = outcome.get("requestId")
            if rid and rid in self.by_id:
                rec = self.by_id[rid]
                outcome["decision"] = rec["decision"]
                outcome["risk"] = rec["risk"]
                outcome["evidence"] = rec.get("evidence", {})
                outcome["retrieval"] = rec.get("retrieval", {})
                outcome["capability"] = rec.get("capability", {})
                outcome["governance"] = rec.get("governance", {})
                outcome["findings"] = [
                    d for d in rec["detectors"]
                    if (d.get("score") or 0) > 0 or d.get("labels")]
                outcome["answer"] = rec["decision"].get("releasedText") or ""
                outcome["proposedAnswer"] = (rec.get("proposal") or {}).get("answer", "")
                # What the second model said, shown to the person who asked. If a
                # judge raised a doubt about the answer they are reading, they are
                # the one who needs to know it.
                outcome["adjudication"] = rec.get("adjudication", {})
                outcome["verification"] = rec.get("verification", {})
                # Which provider actually produced the bytes being governed.
                # Rebuilt transcripts need it as much as a fresh reply does.
                outcome["answeredBy"] = rec.get("answeredBy", {})
                # And the seam back to the control plane: this question is now
                # part of the portfolio's cost and exposure, and the user page
                # says so rather than leaving it to be believed.
                outcome["accounting"] = {
                    "systemId": rec["systemId"],
                    "system": (self.registry.get(rec["systemId"]).name
                               if self.registry.get(rec["systemId"]) else
                               rec["systemId"]),
                    "price": rec["risk"].get("price", 0),
                    "spendInr": rec.get("spendInr", 0.0),
                    "oversightCostInr": rec.get("oversightCostInr", 0.0),
                    "reviewMinutes": rec.get("reviewMinutes", 0.0),
                    "ledgerIndex": rec.get("ledgerIndex"),
                    "tokens": rec.get("tokens", 0)}
            item["outcome"] = outcome
            out.append(item)
        return out

    # -------------------------------------------------------------- review ---
    def review_queue(self, status: str = "held") -> list[dict[str, Any]]:
        rows = [h for h in self.held.values()
                if status == "all" or h["status"] == status]
        rank = {"high": 0, "medium": 1, "low": 2}
        return sorted(rows, key=lambda h: (rank.get(h["severity"], 9),
                                           h["askedAt"]), reverse=False)

    def review_question(self, held_id: str, decision: str, *, actor: str,
                        note: str = "") -> dict[str, Any]:
        """A human decides. Pass releases the question to the model; block
        confirms the refusal. Either way the reviewer's name is on it."""
        held = self.held.get(held_id)
        if held is None:
            raise ValueError(f"unknown held question '{held_id}'")
        if decision not in ("pass", "block"):
            raise ValueError("decision must be 'pass' or 'block'")
        if held["status"] not in ("held", "refused"):
            raise ValueError(f"this question was already {held['status']}")

        with self._lock:
            held["reviewedBy"] = actor
            held["reviewedAt"] = _now()
            held["reviewNote"] = note[:400]
            held["status"] = "released" if decision == "pass" else "blocked"

        self._event("question.reviewed", held["systemId"], {
            "heldId": held_id, "decision": decision, "actor": actor,
            "note": note[:400], "checks": [f["check"] for f in
                                           held["ingress"]["findings"]]})

        if decision == "pass":
            # Released: it now runs the ordinary path, and the user's chat
            # updates without them asking again.
            interactive = getattr(self.provider, "interactive", None)
            verdict = self.scope.check(held["systemId"], held["question"])
            kwargs = {"tool_hint": held.get("toolHint"),
                      "amount_inr": held.get("amountInr"),
                      # Still a person's question, and it must land in the
                      # portfolio's live-traffic numbers as one.
                      "origin": "user", "scope": verdict}
            if interactive is not None:
                with interactive(True):
                    record = self.turn(held["systemId"], held["question"], **kwargs)
            else:
                record = self.turn(held["systemId"], held["question"], **kwargs)
            with self._lock:
                held["requestId"] = record["requestId"]
                held["status"] = "answered"
            return {"heldId": held_id, "decision": decision, "actor": actor,
                    "status": "answered", "requestId": record["requestId"],
                    "answer": record["decision"].get("releasedText", ""),
                    "route": record["decision"]["action"]}

        return {"heldId": held_id, "decision": decision, "actor": actor,
                "status": "blocked",
                "detail": "the question was refused and the user has been told"}

    # -------------------------------------------------------------- owners ---
    def set_owner(self, system_id: str, *, actor: str, owner: str | None = None,
                  owner_email: str | None = None) -> dict[str, Any]:
        """Change who a system belongs to, and where their briefings go.

        Recorded like any other operator action. Ownership is the field every
        advisory is addressed to, so changing it quietly would make the whole
        notification trail unverifiable."""
        from .notify import valid_address

        app = self.registry.get(system_id)
        if app is None:
            raise ValueError(f"unknown system '{system_id}'")

        before = {"owner": app.owner, "ownerEmail": app.owner_email}
        name = (owner or "").strip()
        email = (owner_email or "").strip()

        if owner is not None:
            if not name:
                raise ValueError("owner name cannot be empty")
            if len(name) > 80:
                raise ValueError("owner name is too long")
        if owner_email is not None and email and not valid_address(email):
            raise ValueError(f"'{email}' is not a valid email address")

        with self._lock:
            if owner is not None:
                app.owner = name
            if owner_email is not None:
                app.owner_email = email

        entry = self._event("owner.changed", system_id, {
            "actor": actor, "owner": app.owner, "ownerEmail": app.owner_email,
            "previous": before})
        return {"systemId": system_id, "owner": app.owner,
                "ownerEmail": app.owner_email, "previous": before,
                "actor": actor, "ledgerIndex": (entry or {}).get("index"),
                "persisted": entry is not None}

    # ------------------------------------------------------------- budgets ---
    MAX_BUDGET_INR = 10_000_000_000.0
    MAX_REVIEW_MINUTES = 60 * 24 * 7 * 1000.0

    def set_budget(self, system_id: str, *, actor: str, budget_inr: float | None = None,
                   review_minutes_week: float | None = None,
                   reason: str = "adjusted from the operations console") -> dict[str, Any]:
        """A budget change is an operator action, so it gets a receipt.

        It used to be an in-memory attribute write: unvalidated, unattributed and
        silently reverted by the next restart. A control plane whose own controls
        leave no evidence is not one."""
        import math

        app = self.registry.get(system_id)
        if app is None:
            raise ValueError(f"unknown system '{system_id}'")

        def clean(value: float | None, ceiling: float, label: str) -> float | None:
            if value is None:
                return None
            try:
                v = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{label} must be a number") from None
            if math.isnan(v) or math.isinf(v):
                raise ValueError(f"{label} must be finite")
            if v <= 0:
                raise ValueError(f"{label} must be greater than zero; a zero budget would "
                                 f"make every utilisation reading meaningless")
            if v > ceiling:
                raise ValueError(f"{label} exceeds the sane ceiling of {ceiling:,.0f}")
            return round(v, 2)

        new_budget = clean(budget_inr, self.MAX_BUDGET_INR, "budgetInr")
        new_review = clean(review_minutes_week, self.MAX_REVIEW_MINUTES, "reviewMinutesWeek")
        if new_budget is None and new_review is None:
            raise ValueError("nothing to change")

        before = {"budgetInr": app.budget_inr_month,
                  "reviewMinutesWeek": app.review_minutes_week}
        with self._lock:
            if new_budget is not None:
                app.budget_inr_month = new_budget
            if new_review is not None:
                app.review_minutes_week = new_review
        entry = self._event("budget.changed", system_id, {
            "actor": actor, "reason": reason,
            "budgetInr": app.budget_inr_month,
            "reviewMinutesWeek": app.review_minutes_week,
            "previous": before})
        return {"systemId": system_id, "actor": actor,
                "budgetInr": app.budget_inr_month,
                "reviewMinutesWeek": app.review_minutes_week,
                "previous": before,
                "ledgerIndex": (entry or {}).get("index"),
                "persisted": entry is not None}

    def apply_overlay(self, system_id: str, kind: str, payload: dict[str, Any], reason: str,
                      *, rule_id: str | None = None, approved_by: str | None = None,
                      ttl_s: int = 3600, expected: dict[str, Any] | None = None) -> Overlay:
        prior = [o for o in self.overlays if o.system_id == system_id and o.kind == kind]
        overlay = Overlay(f"ctl_{uuid.uuid4().hex[:8]}", system_id, kind, payload, reason,
                          rule_id=rule_id, approved_by=approved_by,
                          expires_at=time.time() + ttl_s,
                          version=(prior[-1].version if prior else 0) + 1,
                          expected_effect=expected or {})
        self.overlays.append(overlay)
        self._event("control.applied", system_id, overlay.as_dict())
        return overlay

    def rollback_overlay(self, overlay_id: str, actor: str = "operator") -> Overlay | None:
        for o in self.overlays:
            if o.id == overlay_id and o.active:
                o.active = False
                o.rolled_back_at = time.time()
                self._event("control.rolled_back", o.system_id,
                            {"overlayId": overlay_id, "actor": actor})
                return o
        return None

    # ----------------------------------------------------------------- turn ---
    def turn(self, system_id: str, message: str, *, tool_hint: str | None = None,
             amount_inr: float | None = None, context: list[str] | None = None,
             shadow_profile: str | None = None, at: str | None = None,
             origin: str = "ambient", scope: Any = None,
             hold: tuple[str, float, float] | None = None) -> dict[str, Any]:
        """One governed turn.

        `origin` records where the traffic came from — a person typing on the user
        page, ambient background load, a demo scenario, or the seeded history.
        Everything downstream is the same, deliberately: the point of one control
        plane is that a real user's question is priced by exactly the code that
        priced the seeded history, and the portfolio can then say which of its
        numbers came from a live human."""
        t0 = time.perf_counter()
        request_id = uuid.uuid4().hex[:12]
        app = self.registry.get(system_id)
        overlay = self.overlay_for(system_id)
        # Admission. `ask()` has already reserved for the questions a person
        # types; every other route — the operator turn endpoint, the surge
        # bench, the seeder — reserves here, so there is no way into the
        # request path that skips the budget.
        own_hold = hold
        if own_hold is None and origin != "seed":
            verdict = self.admit(system_id)
            if not verdict["admitted"]:
                return self._finish(
                    request_id, system_id, t0, None, None, [], dict(EMPTY_RISK),
                    {"action": BLOCK, "scored": False,
                     "reason": f"refused before generation: this system is at its "
                               f"{'reviewer capacity' if verdict['reason'] == 'review_capacity' else 'spend budget'} "
                               f"for the period",
                     "releasedText": "",
                     "sideEffect": {"state": "withheld",
                                    "detail": "no model call was made at all",
                                    "textReturnedToDeveloper": False,
                                    "changesTheWorld": False},
                     "detail": {"refusedOn": "budget", "budget": verdict}},
                    {"status": "fully_governed", "fullyGoverned": True,
                     "mandatoryMissing": [], "mandatoryPending": [],
                     "advisoryMissing": [], "failClosed": False},
                    None, message=message, at=at, origin=origin)
            own_hold = verdict["hold"]

        # A suspended system is refused before a single token is spent.
        if overlay and overlay.get("suspend"):
            return self._finish(request_id, system_id, t0, None, None, [], dict(EMPTY_RISK),
                                {"action": BLOCK, "reason": "this system is suspended by an "
                                 "active control; a human must lift it before it can send "
                                 "traffic", "releasedText": "",
                                 "sideEffect": {"state": "withheld",
                                                "detail": "no model call was made at all",
                                                "textReturnedToDeveloper": False,
                                                "changesTheWorld": False},
                                 "detail": {"control": "suspend"}},
                                {"status": "ungoverned_due_to_failure", "fullyGoverned": False,
                                 "mandatoryMissing": [], "advisoryMissing": [],
                                 "failClosed": True}, None, hold=own_hold,
                                origin=origin)

        # Every application is offered its own tools plus `none`. See NO_TOOL for
        # why "I did not need a tool" has to be something the agent can say.
        tools = [NO_TOOL.as_dict()] + [t.as_dict()
                                       for t in (app.tools.values() if app else [])]

        # Retrieval, not a hardcoded list. BM25 over this system's own documents,
        # scoped so a support copilot can never cite an HR file. The agent is
        # shown ids and text; it may cite only the ids.
        hits = self.corpus.search(system_id, message, top_k=RETRIEVAL_TOP_K)
        ctx = [{"id": c.chunk_id, "text": c.text, "title": c.title} for c, _ in hits]
        retrieval = {"query": message[:200], "hits": len(ctx),
                     "topScore": round(hits[0][1], 4) if hits else 0.0,
                     "chunkIds": [c.chunk_id for c, _ in hits],
                     "documents": sorted({c.title for c, _ in hits}),
                     "corpusChunks": len(self.corpus._by_system.get(system_id, [])),
                     "method": "bm25"}

        # 1 · the agent proposes
        proposal: AgentProposal | None = None
        proposal_error: str | None = None
        proposal_code: str | None = None
        try:
            # The agent call is upstream generation, not governed detection. It
            # gets its own budget; the policy latency budget governs detectors,
            # which is the thing we make promises about.
            proposal = self.provider.propose(
                message, tools=tools, context=ctx,
                deadline_s=float(os.getenv("CONTROLPLANE_AGENT_TIMEOUT_S", "20")))
        except ProposalError as exc:
            proposal_error = f"the agent's proposal was malformed and was rejected: {exc}"
            proposal_code = "proposal_schema_error"
        except Exception as exc:                                    # noqa: BLE001
            # Classified, never raw. An upstream error body has no business in a
            # governance receipt.
            proposal_code = getattr(exc, "code", "provider_unavailable")
            proposal_error = f"the agent could not be reached ({proposal_code})"

        if proposal is None:
            cap = self.registry.resolve_capability(system_id, tool_hint, "execute")
            gov = {"status": "ungoverned_due_to_failure", "fullyGoverned": False,
                   "mandatoryMissing": ["agent_proposal"], "mandatoryPending": [],
                   "advisoryMissing": [], "failClosed": True}
            return self._finish(request_id, system_id, t0, None, cap, [], dict(EMPTY_RISK),
                                {"action": BLOCK, "reason": proposal_error or "no proposal",
                                 "releasedText": "",
                                 "sideEffect": {"state": "withheld",
                                                "detail": "the agent produced nothing that "
                                                          "could be governed",
                                                "textReturnedToDeveloper": False,
                                                "changesTheWorld": False},
                                 "detail": {"proposalRejected": True,
                                            "errorCode": proposal_code,
                                            "error": proposal_error}},
                                gov, None, message=message, at=at,
                                hold=own_hold, origin=origin)

        # The model cited IDs. Only the server can turn an ID into text, so the
        # evidence grounding is measured against cannot be authored by the agent.
        proposal.sources, proposal.unresolved_ids = self.corpus.resolve(
            proposal.source_ids)

        # The evidence tier is the honest answer to "there is no reliable
        # real-time ground truth". We do not pretend to have one — we grade what
        # we do have, and let the required tier rise with the action class.
        tier = evidence_tier(proposal.sources, retrieval)

        # 2 · what can this proposal actually do?
        cap = self.registry.resolve_capability(
            system_id, tool_hint or proposal.tool_id, proposal.declared_action,
            amount_inr=amount_inr)

        profile = resolve_profile(shadow_profile or (app.policy_profile if app else
                                                    "customer_support"),
                                 app.jurisdiction if app else None, overlay)

        # 3 · evidence, under a deadline that is actually enforced
        kwargs = {"answer": proposal.answer, "prompt": message, "sources": proposal.sources,
                  # Grounding measures the answer against what the agent CITED.
                  # The omission check has to measure it against everything
                  # retrieval surfaced, because the failure it looks for is
                  # precisely that the governing line was retrieved and then
                  # walked past. Measuring an omission only against the sources
                  # the agent chose to cite would ask the agent to mark its own
                  # homework.
                  "retrieved": [c["text"] for c in ctx],
                  # What the registry actually grants this application, so an
                  # answer promising the reader an ability it does not have can
                  # be caught without asking a model anything.
                  "capabilities": sorted({c for tool in (app.tools.values() if app
                                                         else [])
                                          for c in (tool.capabilities or [])}),
                  "provider": self.provider, "task_class": system_id,
                  "tokens": (proposal.usage.get("promptTokens", 0)
                             + proposal.usage.get("outputTokens", 0)) or None}
        futures, unsubmitted = {}, []
        inline_pool = pool("inline")
        for name in profile.inline:
            try:
                futures[inline_pool.submit(_run, name, kwargs, "inline")] = name
            except RuntimeError:
                # The pool refused the work. This must never read as a clean
                # check: an unrun detector is recorded as not having run.
                unsubmitted.append(name)
        done, pending = wait_compat(futures, profile.latency_budget_ms / 1000.0)

        from .gate import safe_result
        results: list[DetectorResult] = [
            safe_result(f, futures[f], "inline") for f in done]
        for name in unsubmitted:
            results.append(DetectorResult(
                name, status="failed", execution_mode="inline",
                error_code="executor_unavailable",
                requirement="mandatory" if name in profile.mandatory else "advisory",
                detail={"reason": "the detector pool refused the submission; this "
                                  "check never started"}))
        abandoned = [futures[f] for f in pending]
        for name in abandoned:
            results.append(DetectorResult(name, status="timed_out", execution_mode="inline",
                                          latency_ms=profile.latency_budget_ms,
                                          requirement="mandatory" if name in
                                          profile.mandatory else "advisory",
                                          detail={"reason": f"exceeded the "
                                                  f"{profile.latency_budget_ms} ms budget"}))

        queued, dropped = _enqueue(request_id, abandoned + profile.deferred, kwargs,
                                   self._amend)
        if dropped:
            # Capacity was breached. The record says so rather than implying the
            # work is merely pending.
            self.dropped_verification.append(
                {"requestId": request_id, "systemId": system_id, "detectors": dropped,
                 "at": _now()})
            for name in dropped:
                results.append(DetectorResult(
                    name, status="failed", execution_mode="deferred",
                    error_code="queue_saturated",
                    requirement="mandatory" if name in profile.mandatory else "advisory",
                    detail={"reason": "deferred verification queue was full; this check "
                                      "was never scheduled"}))
        for name in profile.deferred:
            if name in dropped:
                # already recorded as a capacity failure; a second, softer record
                # of the same detector would let the failure be read as pending
                continue
            results.append(DetectorResult(name, status="queued_async",
                                          execution_mode="deferred",
                                          requirement="mandatory" if name in
                                          profile.mandatory else "advisory"))

        if proposal.unresolved_ids:
            results.append(DetectorResult(
                "citation", score=1.0, confidence=0.95, requirement="mandatory",
                labels=["unverifiable"],
                evidence=[f"agent cited {len(proposal.unresolved_ids)} source id(s) that do "
                          f"not exist: {', '.join(proposal.unresolved_ids[:3])}"],
                detail={"unresolved": proposal.unresolved_ids}))

        # 4 · price, on evidence that actually exists
        # A provisional price, only to decide whether a second opinion is worth
        # buying. Cheap, deterministic, and it means a clean grounded answer
        # never pays for one.
        provisional = price(results, profile.weights, cap.blast_radius)
        grounding_result = next((r for r in results if r.detector_id == "grounding"), None)
        purpose_result = next((r for r in results if r.detector_id == "purpose"), None)
        scope_verdict = getattr(scope, "verdict", "") if scope is not None else ""
        want_judge, judge_why = should_adjudicate(
            tier=tier["tier"], price=provisional["price"],
            pass_threshold=profile.thresholds["pass"],
            grounding=grounding_result, already_blocked=bool(cap.denied),
            claims=extract_claims(proposal.answer), scope=scope_verdict,
            purpose_flagged=bool(purpose_result
                                 and purpose_result.detail.get("omittedCondition")))

        adjudication: dict[str, Any] = {"ran": False, "reason": judge_why}
        if want_judge:
            # Where nothing authoritative backs the answer and the action advises
            # or worse, an absent judgement is a governance gap rather than a
            # missing nicety — recorded mandatory so routing has a floor for it.
            required = judge_required(tier=tier["tier"],
                                      effective_action=cap.effective_action,
                                      scope=scope_verdict)
            adj = adjudicate(proposal.answer, proposal.sources, self.provider,
                             timeout_s=float(os.getenv("CONTROLPLANE_JUDGE_TIMEOUT_S",
                                                       "6")),
                             question=message, domain=system_id)
            adjudication = {**adj.as_dict(), "trigger": judge_why,
                            "required": required}
            results.append(to_detector(adj, required=required))

        risk = price(results, profile.weights, cap.blast_radius)
        gov = governance_status(results, profile, cap.effective_action)
        decision = route(proposal.answer, results, risk, profile, cap, gov)

        # The evidence floor. An irreversible action resting on the model's own
        # memory is refused whatever it scored, because a low risk price on
        # unverifiable evidence is a confident guess, not a safe answer.
        if not tier_satisfied(tier["tier"], cap.effective_action):
            decision = {
                "action": BLOCK,
                "reason": f"'{cap.effective_action}' requires "
                          f"{REQUIRED_TIER.get(cap.effective_action, TIER_A)} evidence "
                          f"and this answer is {tier['label']}: {tier['detail']}",
                # Withheld from the user, kept for the developer. Same rule as
                # every other block: `releasedText` is only ever what the person
                # who asked may see.
                "releasedText": "",
                "developerDraft": proposal.answer,
                "scored": False,
                "downgradedTo": "draft",
                "sideEffect": {"state": "withheld",
                               "detail": "the tool call was not issued; the drafted text "
                                         "was returned to the developer, not to the audience",
                               "textReturnedToDeveloper": True,
                               "changesTheWorld": cap.effective_action in IRREVERSIBLE},
                "detail": {"evidenceFloor": True, "tier": tier["tier"],
                           "required": REQUIRED_TIER.get(cap.effective_action, TIER_A)}}

        return self._finish(request_id, system_id, t0, proposal, cap, results, risk,
                            decision, gov, profile, queued=queued, message=message,
                            dropped=dropped, at=at, retrieval=retrieval, tier=tier,
                            adjudication=adjudication, origin=origin, hold=own_hold,
                            scope=(scope.as_dict() if scope is not None else {}))

    # --------------------------------------------------------------- record ---
    def _finish(self, request_id: str, system_id: str, t0: float,
                proposal: AgentProposal | None, cap: Any, results: list[DetectorResult],
                risk: dict[str, Any], decision: dict[str, Any], gov: dict[str, Any],
                profile: Any, queued: int = 0, message: str = "",
                dropped: list[str] | None = None, at: str | None = None,
                retrieval: dict[str, Any] | None = None,
                tier: dict[str, Any] | None = None,
                adjudication: dict[str, Any] | None = None,
                origin: str = "ambient",
                scope: dict[str, Any] | None = None,
                hold: tuple[str, float, float] | None = None) -> dict[str, Any]:
        decision_latency = (time.perf_counter() - t0) * 1000
        usage = (proposal.usage if proposal else {}) or {}
        agent_tokens = usage.get("promptTokens", 0) + usage.get("outputTokens", 0)
        # The judge is a model call this turn made, so it is part of what this
        # turn cost. Leaving it out understated exactly the decisions that spend
        # the most — the ones weak enough to need a second opinion — which is
        # the wrong direction for a number the cost story rests on.
        judge_tokens = int((adjudication or {}).get("tokens", 0) or 0)
        tokens = agent_tokens + judge_tokens
        spend = round(tokens / 1000 * INR_PER_1K_TOKENS, 4)
        # The cost almost every AI budget leaves out. An escalation buys four
        # minutes of a reviewer's attention and a block buys eight; at eight
        # rupees a minute that is thousands of times the model call that caused
        # it. Kept as its own line rather than folded into model spend, because
        # the two budgets are held by different people — and because it is the
        # number that makes a noisy detector visibly expensive.
        review_minutes = REVIEW_MINUTES.get(decision["action"], 0.0)
        oversight = round(review_minutes * INR_PER_REVIEW_MINUTE, 2)
        app = self.registry.get(system_id)
        # The real cost is known now, so give back what this turn did not use.
        self.release(hold)

        with self._lock:
            self._seq += 1
            record = {
                "requestId": request_id, "sequence": self._seq, "systemId": system_id,
                "owner": app.owner if app else None,
                "department": app.department if app else None,
                "createdAt": at or _now(),
                # The prompt, with validated identifiers masked. A receipt is
                # written to an append-only log nobody can go back and edit, so
                # a card number in one is permanent by construction. The digest
                # below still proves which question this was, and replay does
                # not need the identifier — it needs the bytes to be stable,
                # and a deterministic mask is stable.
                "message": redact(message) if REDACT_RECEIPTS else message,
                "messageRedacted": REDACT_RECEIPTS,
                "messageSha256": __import__("hashlib").sha256(
                    (message or "").encode()).hexdigest()[:16],
                "proposal": proposal.as_dict() if proposal else None,
                # One small block every surface can render without digging
                # through the proposal. `live` is true only when the live model
                # actually produced these bytes.
                "answeredBy": ({
                    "provider": proposal.provider,
                    "live": proposal.provider not in ("offline", ""),
                    "model": (os.getenv("CONTROLPLANE_AGENT_MODEL",
                                        "gemini-3.1-flash-lite")
                              if proposal.provider == "gemini" else ""),
                    "latencyMs": round(proposal.latency_ms, 1),
                    "fellBackFrom": proposal.fell_back_from,
                    "fallbackCode": proposal.fallback_code,
                    "fallbackDetail": proposal.fallback_detail,
                } if proposal else {"provider": "", "live": False,
                                    "fellBackFrom": "", "fallbackCode": "",
                                    "fallbackDetail": ""}),
                "capability": cap.as_dict() if cap else None,
                # The immutable snapshot the decision was made under. Deferred
                # verification and replay both reconstruct from exactly this, so
                # a later result cannot be judged by rules that were not in force.
                "policy": ({"id": profile.id, "thresholds": dict(profile.thresholds),
                            "weights": dict(profile.weights),
                            "latencyBudgetMs": profile.latency_budget_ms,
                            "inline": list(profile.inline),
                            "deferred": list(profile.deferred),
                            "hardGateActions": list(profile.hard_gate_actions),
                            "mandatory": list(profile.mandatory),
                            "jurisdiction": profile.jurisdiction,
                            "audience": profile.audience,
                            "overlay": profile.overlay}
                           if profile else None),
                "retrieval": retrieval or {},
                "evidence": tier or {},
                # One block, computed once, rendered by every surface. See
                # `verification_summary` for why this had to stop being two
                # numbers on two different lines.
                "verification": verification_summary(results, tier or {},
                                                     retrieval or {}, adjudication),
                # Recorded so a judged decision replays against the judgement
                # that was made at the time, not a fresh call.
                "adjudication": adjudication or {"ran": False},
                "detectors": [r.as_dict() for r in results],
                # The evidence exactly as it stood when the decision was made.
                # `detectors` above is a living list — deferred verification
                # amends it — so replaying from it would compare a decision
                # against evidence that did not exist when it was taken. This
                # snapshot is never written again, which is what makes
                # "reproduce this decision" deterministic by construction.
                "detectorsAtDecision": [r.as_dict() for r in results],
                "risk": risk, "governance": gov, "decision": decision,
                "decisionLatencyMs": round(decision_latency, 2),
                # The real wall-clock moment this decision was processed. It is
                # NOT `createdAt`, which seeded history deliberately backdates:
                # measuring verification latency from a synthetic timestamp
                # reported a 23-minute verification clock on a fresh boot.
                "processedAtEpochS": time.time(),
                # Business time: what period this decision belongs to. Seeded
                # history is backdated and must land in the month and week it
                # claims, not the moment the process booted.
                "occurredAtEpochS": (
                    datetime.fromisoformat((at or _now()).replace("Z", "+00:00"))
                    .timestamp()),
                "verificationLatencyMs": None,
                "verificationStatus": ("verification_incomplete_due_to_capacity"
                                       if dropped else
                                       "pending" if queued else "complete"),
                "deferredQueued": queued, "droppedVerification": list(dropped or []),
                "tokens": tokens, "spendInr": spend,
                "tokensBreakdown": {"agent": agent_tokens, "judge": judge_tokens},
                "reviewMinutes": review_minutes,
                "oversightCostInr": oversight,
                "totalCostInr": round(spend + oversight, 2),
                # Where this turn came from: "user" is a person typing on /chat,
                # "ambient" is background load, "scenario" a demo button, "seed"
                # the replayed history. One code path, four sources.
                "origin": origin,
                "scope": scope or {},
            }
            # One wording, computed once, rendered by the user page, the
            # reviewer queue and the owner's briefing. See `plain.py` for what
            # went wrong when each surface wrote its own.
            record["plain"] = plain_verdict(record)
            # Which supervisor saw what, who decided, and under which rule. An
            # attribution of a decision the gate already took deterministically —
            # see `supervisors.py` for why that is honest and a negotiation
            # between two model-based supervisors would not be.
            record["supervisors"] = supervisor_review(record)
            self.decisions.append(record)
            self.by_id[request_id] = record
            try:
                self.last_seen[system_id] = max(
                    self.last_seen.get(system_id, 0.0),
                    datetime.fromisoformat(
                        record["createdAt"].replace("Z", "+00:00")).timestamp())
            except Exception:                                        # noqa: BLE001
                self.last_seen[system_id] = time.time()
        entry = self._event("decision.issued", system_id, {"receipt": record})
        if entry:
            record["ledgerIndex"] = entry.get("index")
            record["ledgerHash"] = entry.get("hash")
        else:
            record["persistence"] = "failed"
            record["governance"] = dict(record["governance"])
            record["governance"]["status"] = "ungoverned_due_to_failure"
            record["governance"]["fullyGoverned"] = False
        self._recommend(record)
        return record

    def _amend(self, request_id: str, result: DetectorResult) -> None:
        """Deferred evidence amends the record. It never changes a returned response."""
        with self._lock:
            record = self.by_id.get(request_id)
            if record is None:
                return
            record["detectors"] = [d for d in record["detectors"]
                                   if not (d["detectorId"] == result.detector_id
                                           and d["status"] in ("queued_async", "timed_out"))]
            record["detectors"].append(result.as_dict())
            if record.get("processedAtEpochS") is None:
                record["verificationLatencyBasis"] = "createdAt"
            record["verificationLatencyMs"] = round(
                max(0.0, (time.time() - _processed_at(record)) * 1000), 1)
            if not any(d["status"] in ("queued_async",) for d in record["detectors"]):
                record["verificationStatus"] = "complete"
            # Deferred evidence can only ever improve or confirm the record; it
            # never rewrites the response that was already returned.
            from .detectors import DetectorResult, redact as _DR
            rehydrated = [_DR(d["detectorId"], d["score"], d["confidence"], d["status"],
                              requirement=d.get("requirement", "advisory"),
                              labels=d.get("labels", []), detail=d.get("detail", {}))
                          for d in record["detectors"]]
            prof = profile_from_snapshot(record.get("policy"))
            record["governance"] = governance_status(
                rehydrated, prof,
                (record.get("capability") or {}).get("effectiveAction", "advise"))
            # The response already went out and is untouched. What is amended is
            # the record: a sealed verification result that states whether the
            # completed evidence would have changed the assessment.
            reprice = price(rehydrated, prof.weights,
                            (record.get("capability") or {}).get("blastRadius", 0.0))
            record["verifiedRisk"] = reprice
            record["verificationDelta"] = {
                "priceAtRelease": record["risk"].get("price"),
                "priceVerified": reprice["price"],
                "changed": reprice["price"] != record["risk"].get("price"),
                "wouldHaveRouted": route(
                    (record.get("proposal") or {}).get("answer", ""), rehydrated, reprice,
                    prof, _cap_from(record.get("capability") or {}),
                    record["governance"])["action"],
                "routedAtRelease": record["decision"]["action"]}
        self._event("verification.completed", record["systemId"], {
            "requestId": request_id, "detector": result.detector_id,
            "status": result.status,
            # The full sealed amendment, so a restart recovers the FINAL record
            # rather than only what was known at release.
            "amendment": {"requestId": request_id,
                          "detectors": record["detectors"],
                          "governance": record["governance"],
                          "verifiedRisk": record.get("verifiedRisk"),
                          "verificationDelta": record.get("verificationDelta"),
                          "verificationLatencyMs": record.get("verificationLatencyMs"),
                          "verificationStatus": record.get("verificationStatus")}})

    def _event(self, kind: str, system_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Persist. A governance system that silently loses its own evidence is
        worse than one that admits it did."""
        if self.ledger is None:
            self.ledger_errors.append({"at": _now(), "event": kind,
                                       "error": "no ledger configured"})
            return None
        try:
            return self.ledger.append({"event": kind, "systemId": system_id,
                                       "at": _now(), **data})
        except Exception as exc:                                     # noqa: BLE001
            self.ledger_errors.append({"at": _now(), "event": kind,
                                       "error": f"{type(exc).__name__}: {exc}"[:200]})
            return None

    # -------------------------------------------------------------- advisor ---
    # ------------------------------------------------------------ briefing ---
    def advisories(self, system_id: str) -> dict[str, Any]:
        """Everything the owner of one system needs, in their language.

        The recommendations engine writes for the platform team. An owner in
        Recruiting does not act on "promote the missing detectors inline" — they
        act on "you run out of budget on Thursday, and here is what to change."
        This compiles the same deterministic rules into a briefing addressed to
        the person whose name is on the system."""
        app = self.registry.get(system_id)
        if app is None:
            raise ValueError(f"unknown system '{system_id}'")
        fleet = self.project(system_id)
        burn = self.burn_rate(system_id)
        rank = {"high": 0, "medium": 1, "low": 2}
        items = [r for r in self.recommendations
                 if r["systemId"] == system_id and r.get("status") == "open"]

        # One per rule id — the newest. A briefing that repeats the same finding
        # eleven times is a briefing nobody reads to the end.
        latest: dict[str, dict[str, Any]] = {}
        for r in items:
            latest[r["ruleId"]] = r
        advisories = sorted(latest.values(),
                            key=lambda r: (rank.get(r.get("severity"), 9),
                                           r.get("createdAt", "")))

        return {
            "systemId": system_id, "name": app.name,
            "owner": app.owner, "ownerEmail": app.owner_email,
            "department": app.department,
            "status": fleet["status"], "statusReason": fleet["statusReason"],
            "spendInr": fleet["spendInr"], "budgetInr": fleet["budgetInr"],
            "budgetUsedPct": fleet["budgetUsedPct"],
            "reviewMinutes": fleet["reviewMinutes"],
            "reviewBudgetMinutes": fleet["reviewBudgetMinutes"],
            "reviewUsedPct": fleet["reviewUsedPct"],
            "decisions": fleet["decisions"], "routes": fleet["routes"],
            "exposure": fleet["exposure"], "exposurePer100": fleet["exposurePer100"],
            "completeness": fleet["completeness"],
            "activeControls": fleet["activeControls"],
            "forecast": burn,
            "advisories": advisories,
            "generatedAt": _now(),
        }

    def notify_owner(self, system_id: str, recipients: list[str], *, actor: str,
                     note: str = "") -> dict[str, Any]:
        """Send the briefing, and record that we did — or that we could not.

        The notification is itself a governed action: who sent it, to whom, what
        it said, and whether it was delivered all land in the ledger. A warning
        that silently failed to arrive is worse than no warning."""
        from . import notify as notify_mod
        from .briefing import render

        brief = self.advisories(system_id)
        brief["note"] = note
        subject, html, text = render(brief, note=note)
        result = notify_mod.send(recipients, subject, html, text)

        entry = self._event(
            "notification.sent" if result.get("ok") else "notification.failed",
            system_id,
            {"actor": actor,
             "recipients": result.get("recipients", recipients),
             "subject": subject,
             "transport": result.get("transport"),
             "delivered": bool(result.get("ok")),
             "detail": result.get("detail"),
             "advisoryIds": [a["id"] for a in brief["advisories"]],
             "ruleIds": [a["ruleId"] for a in brief["advisories"]]})

        return {"ok": bool(result.get("ok")), "systemId": system_id,
                "owner": brief["owner"], "actor": actor,
                "recipients": result.get("recipients", []),
                "rejected": result.get("rejected", []),
                "transport": result.get("transport"),
                "detail": result.get("detail"),
                "subject": subject, "html": html, "text": text,
                "advisories": len(brief["advisories"]),
                "ledgerIndex": (entry or {}).get("index"),
                "recorded": entry is not None}

    # ------------------------------------------------------------ forecast ---
    def burn_rate(self, system_id: str) -> dict[str, Any]:
        """How fast this system is spending, and when that runs out.

        Telling an owner they are at 104% of budget is a fact about the past.
        Telling them they run out on Thursday is something they can act on
        *before* it happens.

        The rate is month-to-date spend over days elapsed in the billing month,
        and the total is **the same number the portfolio card shows** — a
        forecast that disagrees with the figure above it is worse than no
        forecast. The direction of travel comes from the observed decision
        window, and that window is reported, because a rate projected from forty
        minutes of traffic is a guess with a decimal point on it."""
        app = self.registry.get(system_id)
        rows = [d for d in self.decisions if d["systemId"] == system_id]
        budget = (app.budget_inr_month if app else 0.0) or 0.0
        spend = round(sum(d.get("spendInr", 0.0) for d in rows)
                      + (app.spend_baseline_inr if app else 0.0), 2)
        review = round(sum(d.get("reviewMinutes", 0.0) for d in rows)
                       + (app.review_baseline_minutes if app else 0.0), 1)

        now = datetime.now(timezone.utc)
        days_elapsed = now.day - 1 + now.hour / 24.0
        if days_elapsed < 3.0:
            # Early in a billing month there is not enough of it to project from.
            # Dividing a standing month-to-date figure by a few hours would
            # report every system as critical on the first of the month.
            return {"systemId": system_id, "observable": False,
                    "state": "unknown", "trend": "unknown",
                    "reason": f"only {days_elapsed:.1f} days into the billing month; too "
                              f"early to project a monthly rate",
                    "spendInr": spend, "budgetInr": budget,
                    "daysElapsed": round(days_elapsed, 1), "decisions": len(rows)}
        if now.month == 12:
            month_end = now.replace(year=now.year + 1, month=1, day=1)
        else:
            month_end = now.replace(month=now.month + 1, day=1)
        days_in_month = (month_end - now.replace(day=1)).days

        per_day = spend / days_elapsed
        remaining = budget - spend
        projected_month = per_day * days_in_month

        if remaining <= 0:
            days_left, state = 0.0, "exhausted"
        elif per_day <= 0:
            days_left, state = None, "idle"
        else:
            days_left = remaining / per_day
            state = ("critical" if days_left <= 3 else
                     "warning" if days_left <= 7 else "comfortable")

        exhausts_on = None
        if days_left:
            exhausts_on = (now + timedelta(days=days_left)).strftime("%d %b")

        # Direction of travel, from the decisions we actually observed.
        stamps = []
        for d in rows:
            try:
                stamps.append(datetime.fromisoformat(
                    d["createdAt"].replace("Z", "+00:00")).timestamp())
            except Exception:                                        # noqa: BLE001
                stamps.append(0.0)
        window_days, trend = 0.0, "unknown"
        if len(stamps) >= 4 and max(stamps) > min(stamps):
            window_days = (max(stamps) - min(stamps)) / 86400.0
            cutoff = max(stamps) - (max(stamps) - min(stamps)) / 3.0
            recent = [d for d, t in zip(rows, stamps) if t >= cutoff]
            older = [d for d, t in zip(rows, stamps) if t < cutoff]
            if recent and older:
                r = len(recent) / max(1e-9, window_days / 3.0)
                o = len(older) / max(1e-9, window_days * 2 / 3.0)
                trend = "rising" if r > o * 1.25 else "falling" if r < o * 0.8 else "flat"

        return {
            "systemId": system_id, "observable": True, "state": state, "trend": trend,
            "spendInr": spend, "budgetInr": budget,
            "remainingInr": round(remaining, 2),
            "perDayInr": round(per_day, 2),
            "projectedMonthInr": round(projected_month, 2),
            "projectedPct": round(projected_month / budget * 100, 1) if budget else None,
            "daysLeft": round(days_left, 1) if days_left is not None else None,
            "exhaustsOn": exhausts_on,
            "daysElapsed": round(days_elapsed, 1), "daysInMonth": days_in_month,
            "reviewMinutes": review,
            "reviewBudgetMinutes": (app.review_minutes_week if app else 0.0) or 0.0,
            "observedWindowDays": round(window_days, 2),
            "decisions": len(rows),
        }

    def _recommend(self, record: dict[str, Any]) -> None:
        """Deterministic, versioned, numerically cited. A model may phrase one of
        these; it may never derive one."""
        system_id = record["systemId"]
        fleet = self.project(system_id)
        rules: list[dict[str, Any]] = []
        cap = record.get("capability") or {}
        dets = {d["detectorId"]: d for d in record["detectors"]}

        if cap.get("capabilityMismatch"):
            rules.append({"ruleId": "CAPABILITY.ACTION_MISMATCH", "ruleVersion": "1.0",
                          "severity": "high",
                          "evidence": {"declared": cap.get("declaredAction"),
                                       "effective": cap.get("effectiveAction"),
                                       "blastRadius": cap.get("blastRadius")},
                          "suggestedControl": "tool_restricted",
                          "text": f"This application declared '{cap.get('declaredAction')}' "
                                  f"while the tool binding proves "
                                  f"'{cap.get('effectiveAction')}'.",
                          "fix": f"In your code, declare the action the tool actually "
                                 f"performs — '{cap.get('effectiveAction')}' — or bind a tool "
                                 f"that only does what you declared.",
                          "fixDetail": "A tool that can send, pay or restart is an "
                                       "irreversible action however the request is worded. "
                                       "If the draft genuinely should not act, call the "
                                       "draft-only tool instead.",
                          "impact": "Until this is corrected every request through this tool "
                                    "is priced at the full blast radius of the action it can "
                                    "actually perform."})

        cost = dets.get("cost", {})
        dup = (cost.get("detail") or {}).get("duplicateShare") or 0
        if dup >= 0.5:
            saving = round(fleet["spendInr"] * dup * 0.55, 2)
            rules.append({"ruleId": "COST.DUPLICATE_PROMPTS", "ruleVersion": "1.0",
                          "severity": "medium",
                          "evidence": {"duplicateShare": dup,
                                       "spendInr": round(fleet["spendInr"], 2)},
                          "suggestedControl": "enable_cache",
                          "text": f"{dup*100:.0f}% of recent prompts for this system are "
                                  f"near-duplicates.",
                          "fix": "Turn on response caching, and prompt caching for the "
                                 "system preamble that is identical on every call.",
                          "fixDetail": "Hash the normalised prompt and serve the stored "
                                       "answer on a hit. The repeated portion of your prompt "
                                       "— instructions, schema, few-shot examples — can be "
                                       "cached by the provider so you stop paying to send it "
                                       "every time.",
                          "impact": f"About ₹{saving:,.0f} a month at the current rate."})

        if fleet["budgetUsedPct"] >= 100:
            rules.append({"ruleId": "COST.BUDGET_EXCEEDED", "ruleVersion": "1.0",
                          "severity": "high",
                          "evidence": {"spendInr": round(fleet["spendInr"], 2),
                                       "budgetInr": fleet["budgetInr"],
                                       "usedPct": fleet["budgetUsedPct"]},
                          "suggestedControl": "suspend",
                          "text": f"This system is at {fleet['budgetUsedPct']:.0f}% of its "
                                  f"monthly budget.",
                          "fix": "Either raise the budget or reduce what each call costs — "
                                 "shorten the system prompt, cap the output length, and route "
                                 "the simple requests to a smaller model.",
                          "fixDetail": "Most overspend in copilots of this shape is a long "
                                       "static preamble sent on every call and an unbounded "
                                       "max_tokens. Both are one-line changes.",
                          "impact": "Left alone, the system is suspended when the budget is "
                                    "enforced, and the team loses the tool entirely."})

        if fleet["completeness"] is not None and fleet["completeness"] < 0.9:
            rules.append({"ruleId": "GOVERNANCE.LOW_COMPLETENESS", "ruleVersion": "1.0",
                          "severity": "high",
                          "evidence": {"completeness": fleet["completeness"],
                                       "decisions": fleet["decisions"]},
                          "suggestedControl": "promote_inline",
                          "text": f"Only {fleet['completeness']*100:.1f}% of this system's "
                                  f"consequence-weighted decisions were fully governed.",
                          "fix": "Promote the missing checks inline for this system, or raise "
                                 "its latency budget so they finish inside the request.",
                          "fixDetail": "A check that is still queued when the answer is "
                                       "released has not verified anything yet. On "
                                       "irreversible actions that gap is the whole risk.",
                          "impact": "Decisions in that gap cannot be described as governed if "
                                    "an auditor asks."})

        fair = dets.get("fairness", {})
        if (fair.get("detail") or {}).get("flips"):
            rules.append({"ruleId": "SAFETY.COUNTERFACTUAL_FLIP", "ruleVersion": "1.0",
                          "severity": "high",
                          "evidence": fair.get("detail", {}),
                          "suggestedControl": "require_human",
                          "text": "A counterfactual probe changed the outcome when only a "
                                  "protected attribute changed — same candidate, different "
                                  "locality, different answer.",
                          "fix": "Remove the proxy attributes from what you send the model. "
                                 "Locality, pincode, school and surname are income and caste "
                                 "proxies; strip them before the call rather than asking the "
                                 "model to ignore them.",
                          "fixDetail": "Instructing a model not to consider an attribute does "
                                       "not reliably work. Not sending it does. If the field "
                                       "is genuinely needed downstream, keep it in your own "
                                       "record and out of the prompt.",
                          "impact": "This is the failure that becomes a news story, and it is "
                                    "invisible to a content filter because every word is "
                                    "polite."})

        priv = dets.get("privacy", {})
        pdet = priv.get("detail") or {}
        if pdet.get("findings"):
            kinds = pdet.get("kinds", [])
            rules.append({"ruleId": "PRIVACY.UNMASKED_IDENTIFIERS", "ruleVersion": "1.0",
                          "severity": "high",
                          "evidence": {"kinds": kinds, "findings": pdet["findings"]},
                          "suggestedControl": "require_human",
                          "text": f"Responses from this system carry format-valid personal "
                                  f"identifiers in clear text"
                                  + (f" ({', '.join(kinds)})." if kinds else "."),
                          "fix": "Mask or tokenise personal data before it goes to the model, "
                                 "and again before it reaches the customer.",
                          "fixDetail": "Send the last four digits, or a token you can resolve "
                                       "on your own side. If the model genuinely needs the "
                                       "full value to do its job, keep the response internal "
                                       "and mask on the way out instead.",
                          "impact": "Every unmasked identifier in a customer-facing response "
                                    "is a disclosure you would have to report."})

        # The mentor's point, made mechanical: a warning before the money is gone,
        # not a report afterwards.
        burn = self.burn_rate(system_id)
        over_projection = (burn.get("projectedPct") or 0) > 100 and (
            burn.get("remainingInr") or 0) > 0
        if burn.get("observable") and burn.get("daysLeft") is not None and (
                burn.get("state") in ("critical", "warning") or over_projection):
            rules.append({"ruleId": "COST.BURN_RATE_PROJECTION", "ruleVersion": "1.0",
                          "severity": "high" if burn["state"] == "critical" else "medium",
                          "evidence": {"perDayInr": burn["perDayInr"],
                                       "daysLeft": burn["daysLeft"],
                                       "projectedMonthInr": burn["projectedMonthInr"],
                                       "projectedPct": burn["projectedPct"],
                                       "budgetInr": burn["budgetInr"]},
                          "suggestedControl": "enable_cache",
                          "text": f"At ₹{burn['perDayInr']:,.0f} a day this system runs out of "
                                  f"budget in {burn['daysLeft']:.0f} days"
                                  + (f", on {burn['exhaustsOn']}." if burn['exhaustsOn']
                                     else ".")
                                  + f" Projected month-end spend is "
                                    f"₹{burn['projectedMonthInr']:,.0f} against a "
                                    f"₹{burn['budgetInr']:,.0f} budget.",
                          "fix": "Act now rather than at the limit: turn on response caching, "
                                 "trim the system prompt, and cap output length.",
                          "fixDetail": f"The rate is month-to-date spend over "
                                       f"{burn['daysElapsed']:.0f} days elapsed. The trend "
                                       f"over the observed window is {burn['trend']}.",
                          "impact": f"Doing nothing means the system stops "
                                    f"{burn['daysLeft']:.0f} days from now, mid-month."})

        for rule in rules:
            self._rec_seq += 1
            rule.update({"id": f"rec_{self._rec_seq:04d}", "systemId": system_id,
                         "requestId": record["requestId"], "derivation": "deterministic",
                         "evidenceRefs": [f"decision:{record['requestId']}"],
                         "status": "open", "createdAt": _now()})
            self.recommendations.append(rule)
            self._event("recommendation.created", system_id, {"recommendation": rule})
        del self.recommendations[:-60]

    # ----------------------------------------------------------- projection ---
    # ------------------------------------------------------- capacity ---
    WARN_AT = 0.85

    def capacity(self, system_id: str) -> dict[str, Any]:
        """Reviewer attention used against what this system is allowed each week.

        **This is a budget that is actually enforced, and the choice is
        deliberate.** A token budget cannot be enforced meaningfully in real
        time: one question costs a fraction of a rupee against a monthly
        allowance in the tens of thousands, so a spend cap that bit would take
        thousands of questions and one that bit quickly would be a fiction.
        Reviewer capacity is the opposite — small, real, and it moves on a single
        question. You do not run out of tokens. You run out of people.

        Spend can be capped too (`spend_mode="hard"`), and one system runs that
        way so the behaviour is demonstrable rather than described. Both caps go
        through `admit()`, which checks and reserves atomically."""
        app = self.registry.get(system_id)
        if app is None:
            return {"systemId": system_id, "mode": "soft", "exhausted": False}
        with self._lock:
            used, _spend = self._usage(system_id)
            reserved = float(self._reserved.get(system_id, 0.0))
        return self._capacity_view(app, used, reserved)

    def _capacity_view(self, app: Any, used: float, reserved: float) -> dict[str, Any]:
        budget = app.review_minutes_week or 1.0
        committed = used + reserved
        pct = committed / budget
        state = ("exhausted" if pct >= 1.0 else
                 "warning" if pct >= self.WARN_AT else "ok")
        return {
            "systemId": app.system_id, "name": app.name, "owner": app.owner,
            "mode": app.review_mode,
            "usedMinutes": round(used, 1), "reservedMinutes": round(reserved, 1),
            "budgetMinutes": budget, "usedPct": round(pct * 100, 1),
            "remainingMinutes": round(max(0.0, budget - committed), 1),
            "state": state,
            "exhausted": state == "exhausted" and app.review_mode == "hard",
            "window": "rolling 7 days", "enforced": app.review_mode == "hard",
            "note": ("reviewer capacity is a hard cap on this system: when it is "
                     "gone, new questions are refused until the owner raises it"
                     if app.review_mode == "hard" else
                     "reviewer capacity is advisory on this system; it warns but "
                     "does not refuse"),
        }

    def _usage(self, system_id: str) -> tuple[float, float]:
        """(reviewer minutes this week, spend this month). Caller holds the lock."""
        app = self.registry.get(system_id)
        _month, week_start = _period_bounds()
        month_start, _ = _period_bounds()
        review = app.review_baseline_minutes if app else 0.0
        spend = app.spend_baseline_inr if app else 0.0
        for d in self.decisions:
            if d["systemId"] != system_id:
                continue
            when = _occurred_at(d)
            if when >= week_start:
                review += d.get("reviewMinutes", 0.0)
            if when >= month_start:
                spend += d.get("spendInr", 0.0)
        return review, spend

    # The worst case a single turn can cost us, used as the reservation. A block
    # buys eight minutes of somebody's day; the spend figure is a deliberately
    # generous ceiling for one interactive turn.
    WORST_CASE_REVIEW_MIN = 8.0
    WORST_CASE_SPEND_INR = 2.0

    def admit(self, system_id: str) -> dict[str, Any]:
        """Check the budgets and hold the worst case, in ONE lock acquisition.

        This is the fix for the defect a reviewer found in the first version of
        the cap, and it is worth being precise about what was wrong. `ask()`
        *checked* capacity, then `turn()` *reserved* it a few lines later. Ten
        questions arriving together all ran the check before any of them reached
        the reservation, all ten saw room, and all ten were admitted. A cap you
        can walk through by arriving at the same time is not a cap.

        Check-and-reserve is now a single atomic operation, and it is the only
        way in. Every route that can cost money — the user page, the operator
        turn endpoint, the surge bench — goes through here, so there is one
        admission decision rather than one per caller.

        Returns a verdict carrying a `hold` the caller MUST release in
        `_finish`, whatever happens to the request afterwards."""
        app = self.registry.get(system_id)
        if app is None:
            return {"admitted": False, "reason": "unknown system", "hold": None}

        with self._lock:
            review_used, spend_used = self._usage(system_id)
            review_held = self._reserved.get(system_id, 0.0)
            spend_held = self._reserved_spend.get(system_id, 0.0)

            review_budget = app.review_minutes_week or 1.0
            spend_budget = app.budget_inr_month or 1.0
            review_after = review_used + review_held + self.WORST_CASE_REVIEW_MIN
            spend_after = spend_used + spend_held + self.WORST_CASE_SPEND_INR

            # Refuse only where the budget is declared HARD. A soft budget warns
            # on the portfolio and in the owner's briefing; it never turns a
            # colleague away.
            if app.review_mode == "hard" and review_after > review_budget:
                return {"admitted": False, "reason": "review_capacity",
                        "capacity": self._capacity_view(app, review_used, review_held),
                        "hold": None}
            if app.spend_mode == "hard" and spend_after > spend_budget:
                return {"admitted": False, "reason": "spend_budget",
                        "spend": {"usedInr": round(spend_used, 2),
                                  "budgetInr": spend_budget,
                                  "usedPct": round(spend_used / spend_budget * 100, 1),
                                  "reservedInr": round(spend_held, 4),
                                  "owner": app.owner, "name": app.name,
                                  "window": "current calendar month"},
                        "hold": None}

            self._reserved[system_id] = review_held + self.WORST_CASE_REVIEW_MIN
            self._reserved_spend[system_id] = spend_held + self.WORST_CASE_SPEND_INR
            return {"admitted": True, "reason": "within budget",
                    "hold": (system_id, self.WORST_CASE_REVIEW_MIN,
                             self.WORST_CASE_SPEND_INR)}

    def release(self, hold: tuple[str, float, float] | None) -> None:
        """Give back what the turn did not use. Always called, even on failure."""
        if not hold:
            return
        system_id, minutes, spend = hold
        with self._lock:
            self._reserved[system_id] = max(
                0.0, self._reserved.get(system_id, 0.0) - minutes)
            self._reserved_spend[system_id] = max(
                0.0, self._reserved_spend.get(system_id, 0.0) - spend)

    # Kept for the tests and the console, which reserve directly.
    def _reserve_review(self, system_id: str, minutes: float) -> None:
        with self._lock:
            self._reserved[system_id] = self._reserved.get(system_id, 0.0) + minutes

    def _release_review(self, system_id: str, minutes: float) -> None:
        with self._lock:
            left = self._reserved.get(system_id, 0.0) - minutes
            self._reserved[system_id] = max(0.0, left)

    # ------------------------------------------------------ policy A/B ---
    def policy_ab(self, system_id: str, message: str,
                  variants: list[dict[str, Any]]) -> dict[str, Any]:
        """One answer, judged under two policies.

        This was the strongest thing in our Round 2 submission and it belongs
        back, because it is the most direct answer we have to the problem
        statement's own complexity:

        > *"Different AI use cases have very different risk tolerance and
        > latency budgets — a single, one-size-fits-all checking approach rarely
        > works well everywhere."*

        The demonstration only means something if the answer is held fixed. So
        there is **exactly one model call**: the agent proposes once, the
        detectors run once against those bytes, and then the same evidence is
        priced and routed under each policy in turn. Nothing about the text
        changes between the two columns — the weights, the thresholds and the
        hard gates do. An email address heading to a customer is repaired on the
        customer-facing profile and passes on the internal one; the EU overlay
        escalates what the India overlay repairs.

        Running the model twice would have been easier and would have proved
        nothing, because any difference could have been the model."""
        app = self.registry.get(system_id)
        if app is None:
            raise ValueError(f"unknown system '{system_id}'")
        if len(variants) != 2:
            raise ValueError("policy A/B compares exactly two policies")

        # One turn, one model call. Its detector results are the shared evidence.
        record = self.turn(system_id, message, origin="scenario")
        results = [_detector_from_dict(d) for d in record["detectorsAtDecision"]]
        cap = _cap_from(record["capability"] or {})
        overlay = self.overlay_for(system_id)

        columns = []
        for variant in variants:
            profile = resolve_profile(
                variant.get("profile") or app.policy_profile,
                variant.get("jurisdiction", app.jurisdiction), overlay)
            risk = price(results, profile.weights, cap.blast_radius)
            gov = governance_status(results, profile, cap.effective_action)
            decision = route(record["proposal"]["answer"] if record.get("proposal")
                             else "", results, risk, profile, cap, gov)
            columns.append({
                "label": variant.get("label") or profile.id,
                "profile": profile.id, "jurisdiction": profile.jurisdiction,
                "thresholds": dict(profile.thresholds),
                "weights": dict(profile.weights),
                "latencyBudgetMs": profile.latency_budget_ms,
                "hardGateActions": list(profile.hard_gate_actions),
                "risk": risk, "governance": gov, "decision": decision,
                "releasedText": decision.get("releasedText", ""),
                "repairs": decision.get("repairs", []),
            })

        a, b = columns
        same = a["decision"]["action"] == b["decision"]["action"]
        return {
            "systemId": system_id, "system": app.name,
            "requestId": record["requestId"],
            "question": record["message"],
            "answer": (record.get("proposal") or {}).get("answer", ""),
            "modelCalls": 1,
            "detectorsShared": [r.detector_id for r in results],
            "columns": columns,
            "identical": same,
            "verdict": ("both policies reach the same decision on these bytes"
                        if same else
                        f"the same answer is {a['decision']['action']} under "
                        f"{a['label']} and {b['decision']['action']} under "
                        f"{b['label']} — the bytes never changed, the policy did"),
        }

    def live_traffic(self, window_s: float = 1800.0, limit: int = 14) -> dict[str, Any]:
        """What the people using the assistants have just done to the numbers.

        The seam that makes this one system rather than two products in a folder.
        Every question typed on the user page is priced by exactly the code that
        priced the seeded history — same detectors, same profile, same ledger —
        so the portfolio can attribute part of its own cost and exposure to live
        human traffic and point at the receipts.

        A word about scale, because it is the honest part. One question costs a
        fraction of a rupee in tokens against a monthly budget in the tens of
        thousands: it will never move a budget bar on its own, and a demo that
        pretended otherwise would be lying. Three things do move immediately and
        are reported here instead — the **exposure** each question adds, the
        **oversight cost** of any escalation or block it causes, and the route
        mix. A single blocked question is enough to change a system's status,
        which is exactly the sensitivity an operator wants."""
        now = time.time()
        with self._lock:
            rows = [d for d in self.decisions if d.get("origin") == "user"]
            redirects = [r for r in self.redirected
                         if now - r.get("epochS", 0) <= window_s]
            held = [h for h in self.held.values()]
        recent_rows = [d for d in rows if now - _processed_at(d) <= window_s]
        routes = Counter(d["decision"]["action"] for d in recent_rows)
        model_spend = sum(d.get("spendInr", 0.0) for d in recent_rows)
        oversight = sum(d.get("oversightCostInr", 0.0) for d in recent_rows)
        exposure = sum(d["risk"].get("price", 0) for d in recent_rows)
        review = sum(d.get("reviewMinutes", 0.0) for d in recent_rows)
        judged = [d for d in recent_rows if (d.get("adjudication") or {}).get("ran")]
        total = model_spend + oversight

        by_system: dict[str, dict[str, Any]] = {}
        for d in recent_rows:
            row = by_system.setdefault(d["systemId"], {
                "systemId": d["systemId"],
                "name": (self.registry.get(d["systemId"]).name
                         if self.registry.get(d["systemId"]) else d["systemId"]),
                "turns": 0, "exposure": 0.0, "oversightCostInr": 0.0,
                "modelSpendInr": 0.0, "blocked": 0, "escalated": 0})
            row["turns"] += 1
            row["exposure"] += d["risk"].get("price", 0)
            row["oversightCostInr"] += d.get("oversightCostInr", 0.0)
            row["modelSpendInr"] += d.get("spendInr", 0.0)
            if d["decision"]["action"] == BLOCK:
                row["blocked"] += 1
            elif d["decision"]["action"] == ESCALATE:
                row["escalated"] += 1

        def summarise(d: dict[str, Any]) -> dict[str, Any]:
            app = self.registry.get(d["systemId"])
            adj = d.get("adjudication") or {}
            findings = [x["detectorId"] for x in d.get("detectors", [])
                        if (x.get("score") or 0) > 0 or x.get("labels")]
            return {"requestId": d["requestId"], "systemId": d["systemId"],
                    "name": app.name if app else d["systemId"],
                    "department": app.department if app else "-",
                    "at": d["createdAt"], "ageS": round(now - _processed_at(d), 1),
                    "route": d["decision"]["action"],
                    "price": d["risk"].get("price", 0),
                    "band": d["risk"].get("band", [0, 0]),
                    "evidence": (d.get("evidence") or {}).get("label", ""),
                    "scope": (d.get("scope") or {}).get("verdict", ""),
                    "judged": bool(adj.get("ran")),
                    "oversightCostInr": d.get("oversightCostInr", 0.0),
                    "spendInr": d.get("spendInr", 0.0),
                    "findings": findings,
                    "question": (d.get("message") or "")[:120]}

        return {
            "windowMinutes": int(round(window_s / 60)),
            "turns": len(recent_rows), "turnsAllTime": len(rows),
            "routes": dict(routes),
            "exposure": round(exposure, 1),
            "modelSpendInr": round(model_spend, 4),
            "oversightCostInr": round(oversight, 2),
            "totalCostInr": round(total, 2),
            "reviewMinutes": round(review, 1),
            # The number that actually answers "what would this cost us at
            # scale", which is the question a single-turn rupee figure cannot.
            "perThousandTurnsInr": (round(total / len(recent_rows) * 1000, 0)
                                    if recent_rows else 0.0),
            "judged": len(judged),
            "judgeShare": (round(len(judged) / len(recent_rows), 3)
                           if recent_rows else 0.0),
            "heldNow": sum(1 for h in held if h["status"] in ("held", "refused")),
            "blockedByReviewer": sum(1 for h in held if h["status"] == "blocked"),
            "redirected": len(redirects),
            "capacityRefusals": len([r for r in self.capacity_refusals
                                     if now - r.get("epochS", 0) <= window_s]),
            "capacityStates": {sid: self.capacity(sid)
                               for sid in self.registry.applications},
            "redirects": [{"at": r["at"], "systemId": r["systemId"],
                           "toName": r["toName"], "question": r["question"]}
                          for r in redirects[-4:][::-1]],
            "systems": sorted(by_system.values(), key=lambda r: -r["turns"]),
            "recent": [summarise(d) for d in recent_rows[-limit:][::-1]],
        }

    def project(self, system_id: str) -> dict[str, Any]:
        app = self.registry.get(system_id)
        rows = [d for d in self.decisions if d["systemId"] == system_id]
        month_start, week_start = _period_bounds()
        # Money is budgeted per calendar month; a reviewer's attention is
        # budgeted per week. Filtering each to its own window is the difference
        # between "93% of this month's budget" being a fact and being a label on
        # a lifetime total.
        month_rows = [d for d in rows if _occurred_at(d) >= month_start]
        week_rows = [d for d in rows if _occurred_at(d) >= week_start]
        routes = Counter(d["decision"]["action"] for d in rows)
        exposure = sum(d["risk"].get("price", 0) for d in rows)
        spend = (sum(d["spendInr"] for d in month_rows)
                 + (app.spend_baseline_inr if app else 0.0))
        review = (sum(d["reviewMinutes"] for d in week_rows)
                  + (app.review_baseline_minutes if app else 0.0))
        weight = sum((d["capability"] or {}).get("blastRadius", 0) or 0 for d in rows)
        governed = sum(((d["capability"] or {}).get("blastRadius", 0) or 0)
                       for d in rows if d["governance"]["fullyGoverned"])
        completeness = (governed / weight) if weight else None
        stale = sum((d["capability"] or {}).get("blastRadius", 0) or 0
                    for d in rows if d["verificationStatus"] == "pending")
        # What part of all this a person actually caused. Same rows, same code —
        # the only difference is where the question came from.
        user_rows = [d for d in rows if d.get("origin") == "user"]
        oversight = sum(d.get("oversightCostInr", 0.0) for d in month_rows)
        budget = (app.budget_inr_month if app else 1.0) or 1.0
        review_budget = (app.review_minutes_week if app else 1.0) or 1.0
        silent_for = time.time() - self.last_seen.get(system_id, 0)

        app_state = self.state_of(system_id)
        if app_state in ("suspended", "quarantined"):
            status, why = "breaching", f"under an active {app_state} control"
        elif not rows or silent_for > 7200:
            status, why = "unknown", ("no traffic yet" if not rows else
                                      f"no signal for {int(silent_for // 60)} min")
        elif (spend / budget) > 1.0 or (review / review_budget) > 1.0:
            status, why = "breaching", "over budget"
        elif routes[BLOCK] or (completeness is not None and completeness < 0.9):
            status, why = "breaching", ("blocked actions present" if routes[BLOCK]
                                        else "governance incomplete")
        elif (spend / budget) > 0.7 or (review / review_budget) > 0.7:
            status, why = "governed", "approaching budget"
        else:
            status, why = "governed", "within limits"

        return {"systemId": system_id, "name": app.name if app else system_id,
                "owner": app.owner if app else "unregistered",
                "department": app.department if app else "-",
                "state": app_state,
                "status": status, "statusReason": why,
                "decisions": len(rows), "routes": dict(routes),
                "exposure": exposure,
                "exposurePer100": round(exposure / len(rows) * 100, 1) if rows else 0,
                "spendInr": spend, "budgetInr": budget,
                "budgetUsedPct": round(spend / budget * 100, 1),
                "reviewMinutes": review, "reviewBudgetMinutes": review_budget,
                "reviewUsedPct": round(review / review_budget * 100, 1),
                "oversightCostInr": round(oversight, 2),
                # What each figure above is actually counting, carried to every
                # surface so no card can silently relabel a lifetime total.
                "periods": {
                    "spend": "current calendar month (UTC)",
                    "review": "rolling 7 days",
                    "monthStartEpochS": round(month_start),
                    "weekStartEpochS": round(week_start),
                    "decisionsThisMonth": len(month_rows),
                    "decisionsThisWeek": len(week_rows),
                    "decisionsLifetime": len(rows),
                    "spendCarriedForwardInr": (app.spend_baseline_inr if app else 0.0),
                    "reviewCarriedForwardMinutes": (app.review_baseline_minutes
                                                    if app else 0.0),
                    "carriedForwardIsSynthetic": True,
                    "syntheticDecisionsThisMonth": sum(
                        1 for d in month_rows if d.get("origin") == "seed"),
                    "liveDecisionsThisMonth": sum(
                        1 for d in month_rows if d.get("origin") != "seed")},
                "reviewMode": (app.review_mode if app else "soft"),
                "capacity": self.capacity(system_id),
                "userTurns": len(user_rows),
                "userExposure": round(sum(d["risk"].get("price", 0)
                                          for d in user_rows), 1),
                "userOversightCostInr": round(sum(d.get("oversightCostInr", 0.0)
                                                  for d in user_rows), 2),
                "userBlocked": sum(1 for d in user_rows
                                   if d["decision"]["action"] == BLOCK),
                "userEscalated": sum(1 for d in user_rows
                                     if d["decision"]["action"] == ESCALATE),
                "completeness": round(completeness, 4) if completeness is not None else None,
                "staleExposure": round(stale, 3),
                "activeControls": [o.as_dict() for o in self.overlays
                                   if o.system_id == system_id and o.live],
                "silentForS": round(silent_for) if rows else None}

    def fleet(self) -> dict[str, Any]:
        systems = [self.project(sid) for sid in self.registry.applications]
        rows = list(self.decisions)
        # Fleet totals are the sum of the per-system projections, so a card and
        # the strip below it can never disagree.
        spend_total = sum(s["spendInr"] for s in systems)
        review_total = sum(s["reviewMinutes"] for s in systems)
        weight = sum((d["capability"] or {}).get("blastRadius", 0) or 0 for d in rows)
        governed = sum(((d["capability"] or {}).get("blastRadius", 0) or 0)
                       for d in rows if d["governance"]["fullyGoverned"])
        pending = [d for d in rows if d["verificationStatus"] == "pending"]
        latencies = sorted(d["decisionLatencyMs"] for d in rows) or [0]
        verif = sorted(d["verificationLatencyMs"] for d in rows
                       if d["verificationLatencyMs"] is not None) or [0]

        def pct(values: list[float], q: float) -> float:
            return round(values[min(len(values) - 1, int(len(values) * q))], 1)

        completeness = (governed / weight) if weight else None
        stale = round(sum((d["capability"] or {}).get("blastRadius", 0) or 0
                          for d in pending), 3)
        return {
            "systems": systems, "decisions": len(rows),
            "completeness": round(completeness, 4) if completeness is not None else None,
            "completenessLabel": ("not_available — no eligible decisions"
                                  if completeness is None else f"{completeness*100:.1f}%"),
            "decisionLatencyP50": pct(latencies, .5), "decisionLatencyP95": pct(latencies, .95),
            "verificationLatencyP50": pct(verif, .5),
            "verificationBacklog": len(pending), "deferredQueueDepth": deferred_depth(),
            "staleExposure": stale,
            # Measured from when the decision was actually processed. Two bugs
            # lived in the old expression: it read `createdAt`, which seeded
            # history backdates, and `time.mktime(<UTC timetuple>)` reads a UTC
            # time as LOCAL time — invisible on a UTC server, off by 5h30m on a
            # laptop in IST, which is the laptop this runs on.
            "oldestPendingS": round(max(
                time.time() - _processed_at(d) for d in pending), 1) if pending else 0,
            "exposure": sum(d["risk"].get("price", 0) for d in rows),
            "spendInr": round(spend_total, 2),
            "reviewMinutes": round(review_total, 1),
            "ledgerErrors": self.ledger_errors[-5:],
            "droppedVerification": len(self.dropped_verification),
            "routes": dict(Counter(d["decision"]["action"] for d in rows)),
            # One system, not two: what the people on /chat have just done to
            # every number above.
            "liveTraffic": self.live_traffic(),
            "oversightCostInr": round(sum(d.get("oversightCostInr", 0.0)
                                          for d in rows), 2),
            "governanceHealth": (
                "degraded" if (len(pending) > 25 or stale > 8 or self.ledger_errors
                               or self.dropped_verification
                               or (completeness is not None and completeness < 0.9))
                else "ok"),
            "provider": {"name": getattr(self.provider, "name", "?"),
                         "live": getattr(self.provider, "live", False)},
            "recommendations": self.recommendations[-12:][::-1],
            "controls": [o.as_dict() for o in self.overlays if o.live],
        }


def wait_compat(futures: dict, timeout: float):
    from concurrent.futures import wait as _wait, FIRST_COMPLETED
    done, pending = _wait(list(futures), timeout=timeout)
    return done, pending
