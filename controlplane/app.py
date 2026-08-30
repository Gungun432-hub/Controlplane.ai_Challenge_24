"""HTTP surface.

Two kinds of endpoint:

  /v1/gate            the sidecar itself - score and route one model response
  /v1/proxy/chat      the same thing in proxy form: we call the model for you,
                      then gate the answer before returning it

  /api/*              operator surface: policies, ledger, telemetry, overrides

The proxy form is what an enterprise actually adopts, because it requires one
base-URL change in the calling application and nothing else. The gate form
exists for teams that already have the completion in hand.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .config import REGISTRY, SETTINGS
from .knowledge import CORPORA, retrieve
from .engine import GateRequest, evaluate
from .feedback import CALIBRATOR
from .ledger import LEDGER
from .providers import get_provider
from .providers.base import Usage
from .session import SESSIONS
from .telemetry import TELEMETRY

app = FastAPI(
    title="ControlPlane",
    version="0.3.0",
    description="Risk-priced oversight for enterprise AI. Model-agnostic sidecar.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"


class GateBody(BaseModel):
    prompt: str = ""
    answer: str
    sources: list[str] = Field(default_factory=list)
    profile: str = "customer_support"
    jurisdiction: str | None = None
    action_class: str | None = None
    regulated: bool = False
    session_id: str | None = None
    task_class: str = "generic"
    app: str = "unnamed-app"
    model: str = "unknown"
    logprob_hint: float | None = None


class ProxyBody(BaseModel):
    prompt: str
    sources: list[str] = Field(default_factory=list)
    profile: str = "customer_support"
    jurisdiction: str | None = None
    action_class: str | None = None
    regulated: bool = False
    session_id: str | None = None
    app: str = "unnamed-app"


class ChatBody(BaseModel):
    message: str
    use_case: str = "customer_support"      # also the policy profile id
    jurisdiction: str | None = None
    session_id: str = "chat"
    action_class: str | None = None


class CompareBody(BaseModel):
    prompt: str = ""
    answer: str
    sources: list[str] = Field(default_factory=list)
    left: dict = Field(default_factory=lambda: {"profile": "customer_support"})
    right: dict = Field(default_factory=lambda: {"profile": "internal_knowledge"})
    action_class: str | None = None
    regulated: bool = True


class OverrideBody(BaseModel):
    request_id: str
    reviewer_id: str
    verdict: str            # "confirmed" | "false_alarm"
    note: str = ""


@app.get("/health")
def health() -> dict:
    p = get_provider()
    inner = getattr(p, "_inner", p)
    lim = getattr(inner, "limiter", None)
    return {"status": "ok", "provider": p.name, "live": SETTINGS.live,
            "judge_model": getattr(inner, "_resolved_model", None) or (
                SETTINGS.judge_model if SETTINGS.live else None),
            "config": SETTINGS.status,
            "quota": lim.stats() if lim else None}


@app.post("/v1/gate")
def gate(body: GateBody) -> dict:
    try:
        result = evaluate(GateRequest(**body.model_dump()))
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.as_dict()


@app.post("/v1/proxy/chat")
def proxy_chat(body: ProxyBody) -> dict:
    """Call the model, then gate its answer before it is returned."""
    provider = get_provider()
    outs, usage = provider.complete(body.prompt, n=1, temperature=0.2)
    answer = outs[0] if outs else ""
    req = GateRequest(
        prompt=body.prompt, answer=answer, sources=body.sources, profile=body.profile,
        jurisdiction=body.jurisdiction, action_class=body.action_class,
        regulated=body.regulated, session_id=body.session_id, app=body.app,
        model=SETTINGS.judge_model if SETTINGS.live else "offline",
    )
    result = evaluate(req)
    out = result.as_dict()
    out["upstream_usage"] = usage.as_dict()
    return out


@app.post("/api/seed")
def seed() -> dict:
    """Run a short burst of representative traffic through the real engine.

    Called automatically by the dashboard on first load when the ledger is
    empty, because a governance console showing zeros teaches a reviewer
    nothing. These are real evaluations, not fixtures: same detectors, same
    scorer, same router, same ledger entries as any other request.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "demo"))
    from seed import SEED_TRAFFIC  # noqa: PLC0415

    before = TELEMETRY.snapshot()["requests"]
    for row in SEED_TRAFFIC:
        evaluate(GateRequest(**row, force_offline=True))
    after = TELEMETRY.snapshot()
    return {"seeded": len(SEED_TRAFFIC), "requests_before": before,
            "requests_after": after["requests"], "routes": after["routes"]}


ANSWER_PROMPT = """You are an enterprise assistant. Answer the user's question using ONLY
the SOURCES below. Be concise - two or three sentences.

If the sources do not contain the answer, say so plainly rather than guessing.

SOURCES:
{sources}

QUESTION: {question}

ANSWER:"""


@app.post("/v1/chat")
def chat(body: ChatBody) -> dict:
    """A governed assistant turn: retrieve, generate, then gate before returning.

    This is the shape an enterprise actually deploys. The application does
    retrieval and generation as it already does; ControlPlane sits on the way
    out and decides what the user is allowed to see.
    """
    if body.use_case not in REGISTRY.profiles:
        raise HTTPException(400, f"unknown use case: {body.use_case}")

    docs = retrieve(body.use_case, body.message, k=2)
    sources = [d["text"] for d in docs]
    provider = get_provider()

    prompt = ANSWER_PROMPT.format(
        sources="\n\n".join(f"[{d['id']}] {d['text']}" for d in docs) or "(none retrieved)",
        question=body.message,
    )
    gen_error = None
    try:
        outs, usage = provider.complete(prompt, n=1, temperature=0.3)
    except Exception as exc:  # noqa: BLE001
        # A model outage must not take the governance layer down with it. We
        # report the failure honestly and still gate whatever text we have.
        gen_error = f"{type(exc).__name__}: {str(exc)[:300]}"
        outs, usage = [], Usage()

    raw_answer = (outs[0] if outs else "").strip()
    if gen_error:
        raw_answer = f"(the model could not be reached: {gen_error})"
    elif not raw_answer or raw_answer.startswith("[offline-sample"):
        # Offline provider cannot generate. Say so rather than invent an answer.
        raw_answer = ("(offline mode: no model is configured, so this assistant cannot "
                      "generate a reply. Set CONTROLPLANE_PROVIDER=gemini to see live "
                      "generation. The governance layer below still runs on this text.)")

    regulated = body.use_case in ("customer_support", "decision_support")
    result = evaluate(GateRequest(
        prompt=body.message, answer=raw_answer, sources=sources,
        source_grades=[d["grade"] for d in docs],
        profile=body.use_case, jurisdiction=body.jurisdiction,
        action_class=body.action_class, regulated=regulated,
        session_id=f"{body.use_case}:{body.session_id}",
        task_class="advise", app=f"chat:{body.use_case}",
        model=SETTINGS.judge_model if SETTINGS.live else "offline",
    ))
    out = result.as_dict()
    out["raw_answer"] = raw_answer
    out["retrieved"] = docs
    out["generation_usage"] = usage.as_dict()
    out["generation_error"] = gen_error
    return out


@app.post("/api/compare")
def compare(body: CompareBody) -> dict:
    """Evaluate one identical response under two policies, side by side.

    The clearest demonstration in the system: same bytes in, different decision
    out, because the use case or the jurisdiction differs.
    """
    def run(cfg: dict) -> dict:
        req = GateRequest(
            prompt=body.prompt, answer=body.answer, sources=body.sources,
            profile=cfg.get("profile", "customer_support"),
            jurisdiction=cfg.get("jurisdiction"),
            action_class=cfg.get("action_class", body.action_class),
            regulated=cfg.get("regulated", body.regulated),
            session_id=None, app="compare",
        )
        return evaluate(req).as_dict()

    return {"left": run(body.left), "right": run(body.right)}


@app.get("/api/queue")
def queue(limit: int = 20) -> dict:
    """Escalations and blocks awaiting human review, most expensive first."""
    reviewed = {e["record"].get("request_id") for e in LEDGER.iter_all()
                if e["record"].get("type") == "human_override"}
    pending = []
    for e in LEDGER.iter_all():
        r = e["record"]
        if r.get("type") == "human_override":
            continue
        if r.get("decision", {}).get("action") not in ("escalate", "block"):
            continue
        if r.get("request_id") in reviewed:
            continue
        pending.append({
            "request_id": r["request_id"], "app": r["app"],
            "policy": r["policy"]["id"], "action": r["decision"]["action"],
            "price": r["risk"]["price"], "band": r["risk"]["band"],
            "labels": r["risk"]["labels"], "reason": r["decision"]["reason"],
            "answer_preview": r["answer_preview"],
            "queue": r["decision"].get("review_queue"),
            "ledger_index": e["index"],
        })
    pending.sort(key=lambda x: -x["price"])
    return {"pending": pending[:limit], "total_pending": len(pending),
            "reviewed": len(reviewed)}


@app.get("/api/tuning")
def tuning() -> dict:
    """The measured operating-point curve, from the last evaluation run."""
    import json as _json
    from pathlib import Path as _Path
    path = _Path(__file__).resolve().parent.parent / "eval" / "results.json"
    if not path.exists():
        return {"available": False,
                "hint": "run: python eval/run_eval.py --sweep"}
    doc = _json.loads(path.read_text())
    from .detectors import grounding as _g
    return {
        "available": True,
        "provider": doc.get("provider"),
        "current": doc.get("metrics"),
        "shipped_support_tau": _g.SUPPORT_TAU,
        "sweep_support_tau": doc.get("sweep_support_tau", []),
        "sweep_pass_threshold": doc.get("sweep_pass_threshold", []),
        "cases": len(doc.get("rows", [])),
    }


@app.get("/api/diag")
def diag() -> dict:
    """One live round-trip against the configured provider, with the raw error.

    Exists because "Internal Server Error" is a useless thing to show anyone.
    If the live path is broken this says which call failed and what the provider
    actually returned.
    """
    p = get_provider()
    report: dict[str, Any] = {"provider": p.name, "live": SETTINGS.live,
                              "config": SETTINGS.status}
    inner = getattr(p, "_inner", p)
    lim = getattr(inner, "limiter", None)
    emb = getattr(inner, "embed_limiter", None)
    report["quota"] = {"generation": lim.stats() if lim else None,
                       "embedding": emb.stats() if emb else None,
                       "resolved_model": getattr(inner, "_resolved_model", None),
                       "model_chain": getattr(inner, "_model_chain", None)}
    report["judge_model"] = getattr(inner, "judge_model", None)
    report["embed_model"] = getattr(inner, "embed_model", None)
    key = SETTINGS.gemini_api_key
    report["api_key"] = {"present": bool(key), "length": len(key),
                         "prefix": key[:4] + "..." if key else None,
                         "looks_like_studio_key": key.startswith("AIza") if key else False}

    try:
        outs, usage = p.complete("Reply with exactly the word: OK", n=1, temperature=0.0)
        report["completion"] = {"ok": True, "text": (outs[0] if outs else "")[:200],
                                "usage": usage.as_dict()}
    except Exception as exc:  # noqa: BLE001
        report["completion"] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:600]}"}

    try:
        v = p.embed(["hello world"])
        report["embedding"] = {"ok": True, "dimensions": len(v[0]) if v else 0}
    except Exception as exc:  # noqa: BLE001
        report["embedding"] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:600]}"}

    return report


@app.get("/api/models")
def models() -> dict:
    """Which models this key can actually call.

    Model aliases move and free-tier allowances differ sharply between them, so
    when generation fails this is the first thing worth looking at.
    """
    p = get_provider()
    inner = getattr(p, "_inner", p)
    if not hasattr(inner, "list_models"):
        return {"available": False, "reason": "offline provider"}
    try:
        ms = inner.list_models()
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    return {"available": True,
            "resolved_model": getattr(inner, "_resolved_model", None),
            "chain": getattr(inner, "_model_chain", []),
            "generation": [m for m in ms if m["generate"]][:40],
            "embedding": [m for m in ms if m["embed"]][:20]}


@app.get("/api/cache")
def cache_stats() -> dict:
    """Embedding cache effectiveness. Source documents repeat constantly in a
    real deployment, so this is the cheapest latency win available."""
    p = get_provider()
    return p.stats() if hasattr(p, "stats") else {"available": False}


@app.get("/api/corpora")
def corpora() -> dict:
    return {uc: [{"id": d.id, "grade": d.grade, "owner": d.owner,
                  "preview": d.text[:110] + "..."} for d in docs]
            for uc, docs in CORPORA.items()}


@app.get("/api/policies")
def policies() -> dict:
    return {"profiles": REGISTRY.list_profiles(),
            "jurisdictions": REGISTRY.list_jurisdictions(),
            "calibration": CALIBRATOR.snapshot()}


@app.post("/api/policies/reload")
def reload_policies() -> dict:
    REGISTRY.reload()
    return {"reloaded": True, "profiles": [p["id"] for p in REGISTRY.list_profiles()]}


@app.get("/api/telemetry")
def telemetry() -> dict:
    return TELEMETRY.snapshot()


@app.get("/api/ledger")
def ledger(limit: int = 50) -> dict:
    return {"entries": LEDGER.read(limit=limit), "verification": LEDGER.verify()}


@app.get("/api/ledger/verify")
def ledger_verify() -> dict:
    return LEDGER.verify()


@app.get("/api/sessions")
def sessions() -> dict:
    return {"sessions": SESSIONS.all()}


@app.post("/api/override")
def override(body: OverrideBody) -> dict:
    """A reviewer confirms or rejects an escalation.

    The override is written to the ledger as a first-class entry - the audit
    trail must show who overrode what, not merely that a threshold moved - and
    it nudges the calibration offset for that policy profile.
    """
    if body.verdict not in ("confirmed", "false_alarm"):
        raise HTTPException(400, "verdict must be 'confirmed' or 'false_alarm'")

    target: dict[str, Any] | None = None
    for entry in LEDGER.iter_all():
        if entry.get("record", {}).get("request_id") == body.request_id:
            target = entry
    if target is None:
        raise HTTPException(404, f"no ledger entry for request_id {body.request_id}")

    profile_id = target["record"]["policy"]["id"]
    calib = CALIBRATOR.record(profile_id, body.verdict)
    TELEMETRY.record_override(body.verdict)

    entry = LEDGER.append({
        "type": "human_override",
        "request_id": body.request_id,
        "reviewer_id": body.reviewer_id,
        "verdict": body.verdict,
        "note": body.note[:500],
        "original_decision": target["record"]["decision"]["action"],
        "original_price": target["record"]["risk"]["price"],
        "policy": profile_id,
        "calibration_after": calib,
    })
    return {"recorded": True, "ledger_index": entry["index"], "calibration": calib}


@app.get("/")
def dashboard() -> Any:
    index = DEMO_DIR / "dashboard.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"service": "controlplane", "docs": "/docs"})
