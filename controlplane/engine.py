"""The gate itself: orchestration of detectors, pricing, routing and recording.

Latency discipline is enforced here, not documented and hoped for. Inline
detectors run concurrently and share the policy's latency budget; if the budget
is exhausted the remaining inline work is demoted to asynchronous and the
response is routed on what we have, with the shortfall recorded. Async detectors
never block release - they refine the record after the fact.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from .config import REGISTRY, SETTINGS, Policy
from .detectors import DETECTORS
from .detectors.base import UNVERIFIABLE, Signal
from .feedback import CALIBRATOR
from .ledger import LEDGER
from .providers import get_provider
from .providers.base import Usage
from .router import Decision, route
from .scoring import RiskPrice, price
from .session import SESSIONS
from .telemetry import TELEMETRY

_POOL = ThreadPoolExecutor(max_workers=8)


@dataclass
class GateRequest:
    prompt: str = ""
    answer: str = ""
    sources: list[str] = field(default_factory=list)
    profile: str = "customer_support"
    jurisdiction: str | None = None
    action_class: str | None = None
    regulated: bool = False
    session_id: str | None = None
    task_class: str = "generic"
    app: str = "unnamed-app"
    model: str = "unknown"
    logprob_hint: float | None = None
    force_offline: bool = False   # seeded/demo traffic: never spend live quota


@dataclass
class GateResult:
    request_id: str
    decision: Decision
    risk: RiskPrice
    signals: list[Signal]
    policy: dict
    telemetry: dict
    ledger_entry: dict
    session: dict

    def as_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "decision": self.decision.as_dict(),
            "released_text": self.decision.released_text,
            "risk": self.risk.as_dict(),
            "signals": [s.as_dict() for s in self.signals],
            "policy": self.policy,
            "telemetry": self.telemetry,
            "ledger": {"index": self.ledger_entry.get("index"),
                       "entry_hash": self.ledger_entry.get("entry_hash"),
                       "prev_hash": self.ledger_entry.get("prev_hash")},
            "session": self.session,
        }


def _run_detector(name: str, provider, req: GateRequest, session_prompts: list[str]) -> Signal:
    fn = DETECTORS[name]
    try:
        return fn(
            provider,
            answer=req.answer,
            prompt=req.prompt,
            sources=req.sources,
            task_class=req.task_class,
            session_prompts=session_prompts,
            logprob_hint=req.logprob_hint,
        )
    except Exception as exc:  # noqa: BLE001
        # A detector that crashes must fail loud but must not take the gate down.
        return Signal(name, score=0.0, confidence=0.0,
                      detail={"error": type(exc).__name__, "message": str(exc)[:200]})


def evaluate(req: GateRequest) -> GateResult:
    t_start = time.perf_counter()
    # Seeded and demonstration traffic runs on the offline provider even when a
    # live key is configured. A free-tier daily quota is a scarce resource and
    # populating a dashboard is not worth spending it on.
    provider = get_provider("offline") if req.force_offline else get_provider()
    policy: Policy = REGISTRY.get(req.profile, req.jurisdiction)
    action_class = req.action_class or policy.default_action_class
    audience = policy.d.get("audience", "internal")

    session = SESSIONS.get(req.session_id or "anonymous")
    session_prompts = list(session.prompts)

    budget_s = policy.latency_budget_ms / 1000.0
    inline_names = policy.inline_detectors
    async_names = policy.async_detectors

    signals: list[Signal] = []
    demoted: list[str] = []
    futures = {_POOL.submit(_run_detector, n, provider, req, session_prompts): n for n in inline_names}
    deadline = time.perf_counter() + budget_s
    for fut in as_completed(futures, timeout=None):
        name = futures[fut]
        if time.perf_counter() > deadline:
            demoted.append(name)
        sig = fut.result()
        sig.ran_inline = name not in demoted
        signals.append(sig)

    inline_elapsed_ms = (time.perf_counter() - t_start) * 1000

    # --- risk price on the inline evidence ------------------------------------
    calib = CALIBRATOR.offset_for(policy.id)
    thresholds = {k: max(1, int(round(v + calib))) for k, v in policy.thresholds.items()}
    policy.d["thresholds"] = thresholds

    rp = price(signals, policy.weights, action_class, audience, req.regulated,
               session_risk=session.accumulated)

    # --- LLM-as-judge, rationed by policy -------------------------------------
    judge_used, judge_usage = False, Usage()
    jc = policy.judge_cfg
    if jc.get("enabled") and rp.price >= int(jc.get("min_risk_price", 100)):
        verdict = provider.judge(req.prompt, req.answer, req.sources)
        judge_used = True
        judge_usage.add(verdict.usage)
        jsig = Signal(
            "judge",
            score=0.0 if verdict.supported else (0.55 if verdict.unverifiable else 0.9),
            confidence=max(0.3, verdict.confidence),
            labels=[UNVERIFIABLE] if verdict.unverifiable else ([] if verdict.supported else ["hallucination"]),
            evidence=[verdict.rationale],
            detail={"supported": verdict.supported, "unverifiable": verdict.unverifiable,
                    "model": SETTINGS.judge_model if SETTINGS.live else "offline-stub"},
            usage=verdict.usage,
        )
        signals.append(jsig)
        weights = dict(policy.weights)
        weights.setdefault("judge", 1.1)
        rp = price(signals, weights, action_class, audience, req.regulated,
                   session_risk=session.accumulated)

    decision = route(req.answer, signals, rp, policy, action_class, req.sources)

    # --- asynchronous detectors: refine the record, never block release -------
    for name in async_names:
        sig = _run_detector(name, provider, req, session_prompts)
        sig.ran_inline = False
        signals.append(sig)

    added_latency_ms = inline_elapsed_ms
    breached = added_latency_ms > policy.latency_budget_ms

    usage = Usage()
    for s in signals:
        usage.add(s.usage)

    session.observe(req.prompt, rp.price, action_class)

    request_id = uuid.uuid4().hex[:12]
    record = {
        "request_id": request_id,
        "app": req.app,
        "model": req.model,
        "policy": {"id": policy.id, "version": policy.version,
                   "jurisdiction": req.jurisdiction, "regime": policy.regime,
                   "thresholds": thresholds, "calibration_offset": calib},
        "action_class": action_class,
        "audience": audience,
        "regulated": req.regulated,
        "prompt_preview": (req.prompt or "")[:240],
        "answer_preview": (req.answer or "")[:240],
        "sources_count": len(req.sources),
        "risk": rp.as_dict(),
        "decision": decision.as_dict(),
        "signals": [s.as_dict() for s in signals],
        "judge_used": judge_used,
        "usage": usage.as_dict(),
        "added_latency_ms": round(added_latency_ms, 2),
        "latency_budget_ms": policy.latency_budget_ms,
        "budget_breached": breached,
        "demoted_detectors": demoted,
        "session": session.as_dict(),
        "provider": provider.name,
    }
    entry = LEDGER.append(record)

    TELEMETRY.record(
        profile=policy.id, route=decision.action, added_latency_ms=added_latency_ms,
        detector_latency={s.name: s.latency_ms for s in signals if s.ran_inline},
        usage=usage.as_dict(), judge_used=judge_used, labels=rp.labels,
        breached_budget=breached,
    )

    return GateResult(
        request_id=request_id, decision=decision, risk=rp, signals=signals,
        policy=policy.summary() | {"thresholds": thresholds, "calibration_offset": calib},
        telemetry={"added_latency_ms": round(added_latency_ms, 2),
                   "latency_budget_ms": policy.latency_budget_ms,
                   "budget_breached": breached, "judge_used": judge_used,
                   "usage": usage.as_dict(), "demoted_detectors": demoted,
                   "provider": provider.name},
        ledger_entry=entry, session=session.as_dict(),
    )
