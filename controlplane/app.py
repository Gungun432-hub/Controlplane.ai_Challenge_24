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
from .engine import GateRequest, evaluate
from .feedback import CALIBRATOR
from .ledger import LEDGER
from .providers import get_provider
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


class OverrideBody(BaseModel):
    request_id: str
    reviewer_id: str
    verdict: str            # "confirmed" | "false_alarm"
    note: str = ""


@app.get("/health")
def health() -> dict:
    p = get_provider()
    return {"status": "ok", "provider": p.name, "live": SETTINGS.live,
            "judge_model": SETTINGS.judge_model if SETTINGS.live else None}


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
