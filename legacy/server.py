from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, ConfigDict
from typing_extensions import Literal

from .engine import ControlPlane, Detector, Overlay, utc_now
from .ledger import JsonlLedger
from .seed import register_catalog, seed_demo


class DetectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    score: float = Field(default=0, ge=0, le=1)
    status: Literal["passed", "failed", "timed_out", "error"] = "passed"
    reason: str | None = None
    delayMs: int = Field(default=0, ge=0)
    timeoutMs: int = Field(default=100, ge=1)


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    applicationId: str
    toolId: str
    input: Any = None
    blastRadius: float = Field(ge=0)
    detectors: list[DetectorRequest] = Field(default_factory=list)
    deferredDetectors: list[DetectorRequest] = Field(default_factory=list)


class ShadowRequest(EvaluateRequest):
    pass


def detector_from_json(data: DetectorRequest) -> Detector:
    return Detector(id=data.id, score=data.score, status=data.status, reason=data.reason,
                    delay_ms=data.delayMs, timeout_ms=data.timeoutMs)


def create_app(plane: ControlPlane | None = None, ledger: JsonlLedger | None = None, seed_on_startup: bool = False) -> FastAPI:
    plane = plane or ControlPlane()
    ledger = ledger or JsonlLedger(os.environ.get("CONTROLPLANE_LEDGER", "data/ledger.jsonl"))
    register_catalog(plane)
    recovered_entries = plane.recover_from_ledger(ledger.read(limit=None))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if seed_on_startup:
            await seed_demo(plane, ledger)
        yield

    app = FastAPI(title="ControlPlane v2", version="0.2.0", lifespan=lifespan)

    def request_context(tenant_id: str | None, actor_id: str | None) -> dict[str, str]:
        auth_mode = os.environ.get("CONTROLPLANE_AUTH_MODE", "development")
        if auth_mode == "required" and (not tenant_id or not actor_id):
            raise HTTPException(status_code=401, detail="X-Tenant-ID and X-Actor-ID are required")
        return {"tenantId": tenant_id or "demo-tenant", "actorId": actor_id or "demo-operator", "authMode": auth_mode}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard_page() -> str:
        from importlib.resources import files
        return files("python.controlplane").joinpath("dashboard.html").read_text(encoding="utf-8")

    @app.get("/developer", response_class=HTMLResponse, include_in_schema=False)
    def developer_page() -> str:
        from importlib.resources import files
        return files("python.controlplane").joinpath("developer.html").read_text(encoding="utf-8")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "recoveredDecisions": str(recovered_entries),
                "ledger": "authoritative-jsonl", "provider": os.environ.get("CONTROLPLANE_PROVIDER", "deterministic")}

    @app.get("/config")
    def config() -> dict[str, Any]:
        return {
            "authMode": os.environ.get("CONTROLPLANE_AUTH_MODE", "development"),
            "tenantHeader": "X-Tenant-ID",
            "actorHeader": "X-Actor-ID",
            "provider": os.environ.get("CONTROLPLANE_PROVIDER", "deterministic"),
            "providerConfigured": bool(os.environ.get("CONTROLPLANE_PROVIDER_URL")),
            "providerAuthority": "advisory-only",
            "budgets": {
                "spend": float(os.environ.get("CONTROLPLANE_SPEND_BUDGET", "1000")),
                "reviewerCapacity": int(os.environ.get("CONTROLPLANE_REVIEWER_CAPACITY", "100")),
                "verificationCapacity": int(os.environ.get("CONTROLPLANE_VERIFICATION_CAPACITY", "100")),
            },
        }

    @app.get("/governance/roles")
    def governance_roles() -> dict[str, Any]:
        return {
            "roles": [
                {"id": "safety-governor", "can": ["observe", "recommend"], "cannot": ["bypass-route", "mutate-base-policy"]},
                {"id": "resource-governor", "can": ["observe", "recommend"], "cannot": ["bypass-route", "mutate-base-policy"]},
                {"id": "evidence-monitor", "can": ["observe", "cite-evidence"], "cannot": ["approve-exception"]},
                {"id": "deterministic-supervisor", "can": ["arbitrate-typed-controls"], "cannot": ["ignore-capability-mismatch"]},
                {"id": "human-operator", "can": ["approve-high-impact-control", "rollback-control"], "cannot": ["rewrite-ledger"]},
            ],
            "policyAuthority": "deterministic-supervisor",
        }

    @app.get("/catalog")
    def catalog() -> dict[str, Any]:
        return {
            "applications": [
                {"id": item.id, "name": item.name}
                for item in sorted(plane.applications.values(), key=lambda item: item.name)
            ],
            "tools": [
                {"id": item.id, "name": item.name, "capabilities": item.capabilities}
                for item in sorted(plane.tools.values(), key=lambda item: item.name)
            ],
        }

    @app.get("/scenarios")
    def scenarios() -> list[dict[str, Any]]:
        return [
            {"id": "safe-support", "label": "Safe support reply", "department": "Customer Support",
             "applicationId": "customer-support", "toolId": "ticketing", "declaredBlastRadius": 10,
             "input": {"message": "Your order is on its way."}},
            {"id": "recruitment-mismatch", "label": "Recruitment capability mismatch", "department": "Recruitment",
             "applicationId": "recruitment", "toolId": "recruiting", "declaredBlastRadius": 20,
             "input": {"candidate": "candidate-17", "operation": "schedule"}},
            {"id": "finance-approval", "label": "Finance approval", "department": "Finance",
             "applicationId": "finance-decision", "toolId": "credit", "declaredBlastRadius": 90,
             "input": {"amount": 25000, "operation": "approve"}},
            {"id": "it-timeout", "label": "IT slow verification", "department": "IT Operations",
             "applicationId": "it-operations", "toolId": "ops", "declaredBlastRadius": 40,
             "input": {"service": "payments", "operation": "restart"}},
            {"id": "marketing-campaign", "label": "Marketing campaign", "department": "Marketing",
             "applicationId": "marketing", "toolId": "campaigns", "declaredBlastRadius": 30,
             "input": {"campaign": "spring-launch", "operation": "send"}},
        ]

    @app.get("/decisions")
    def decisions() -> list[dict[str, Any]]:
        return list(reversed(list(plane.decisions.values())))

    @app.get("/operations")
    def operations() -> dict[str, Any]:
        deferred = [
            {"decisionId": decision_id, "detectors": [detector.id for detector in detectors]}
            for decision_id, detectors in plane._deferred
        ]
        failed = [
            {"decisionId": decision["id"], "applicationId": decision["applicationId"], "detectorId": detector["detectorId"],
             "status": detector["status"], "reason": detector.get("reason")}
            for decision in plane.decisions.values()
            for detector in decision["detectors"]
            if detector["status"] in {"failed", "timed_out", "error"}
        ]
        return {
            "deferredQueue": deferred,
            "deferredCount": len(deferred),
            "failedDetectors": failed,
            "staleExposure": plane.project_portfolio()["staleExposure"],
            "ledgerEntries": len(ledger.read()),
        }

    @app.get("/applications/{application_id}")
    def application_detail(application_id: str) -> dict[str, Any]:
        application = plane.applications.get(application_id)
        if not application:
            raise HTTPException(status_code=404, detail=f"unknown application: {application_id}")
        decisions_for_app = [decision for decision in plane.decisions.values()
                             if decision["applicationId"] == application_id]
        return {
            "application": {"id": application.id, "name": application.name,
                            "declaredCapabilities": application.declared_capabilities},
            "dashboard": next(row for row in plane.dashboard()["applications"] if row["id"] == application_id),
            "decisions": list(reversed(decisions_for_app)),
            "controls": [plane._overlay_dict(overlay) for overlay in plane.overlays
                         if overlay.scope.get("applicationId") == application_id],
            "events": [event for event in plane.events if event["aggregateId"] in
                       {decision["id"] for decision in decisions_for_app}],
        }

    @app.post("/evaluate")
    async def evaluate(
        request: EvaluateRequest,
        tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
        actor_id: str | None = Header(default=None, alias="X-Actor-ID"),
    ) -> dict[str, Any]:
        context = request_context(tenant_id, actor_id)
        detectors = [detector_from_json(d) for d in request.detectors]
        deferred = [detector_from_json(d) for d in request.deferredDetectors]
        try:
            decision = await plane.decide(request.applicationId, request.toolId, request.input, request.blastRadius, detectors, deferred)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ledger_entry = ledger.append({"type": "decision", "context": context, "decision": decision})
        recommendation_ids = [item["id"] for item in plane.recommendations if item["decisionId"] == decision["id"]]
        decision["receipt"] = {
            "decisionId": decision["id"],
            "route": decision["outcome"],
            "evidence": [item["detectorId"] for item in decision["detectors"]],
            "recommendationIds": recommendation_ids,
            "ledger": {"index": ledger_entry["index"], "hash": ledger_entry["hash"]},
            "provenance": {
                "source": "synthetic deterministic demo" if os.environ.get("CONTROLPLANE_SEED", "1") != "0" else "operator request",
                "scenario": "live evaluate request",
                "tenantId": context["tenantId"],
                "actorId": context["actorId"],
                "ruleVersion": "1.0",
                "callerBlastRadius": decision["declaredBlastRadius"],
                "derivedBlastRadius": decision["blastRadius"],
                "capabilitySnapshot": {
                    "effectiveCapabilities": decision["effectiveCapabilities"],
                    "actionClass": decision["actionClass"],
                    "mismatch": decision["capabilityMismatch"],
                },
            },
        }
        return decision

    @app.post("/shadow")
    async def shadow(request: ShadowRequest) -> dict[str, Any]:
        try:
            result = await plane.simulate(request.applicationId, request.toolId, [detector_from_json(d) for d in request.detectors])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ledger.append({"type": "simulation", "result": result})
        return result

    @app.get("/recommendations")
    def recommendations() -> list[dict[str, Any]]:
        return plane.recommendations

    @app.get("/receipts/{decision_id}")
    def receipt(decision_id: str) -> dict[str, Any]:
        decision = plane.decisions.get(decision_id)
        if not decision:
            raise HTTPException(status_code=404, detail=f"unknown decision: {decision_id}")
        for entry in reversed(ledger.read(limit=None)):
            record = entry.get("record", {})
            if record.get("type") == "decision" and record.get("decision", {}).get("id") == decision_id:
                return decision.get("receipt") or {
                    "decisionId": decision_id,
                    "route": decision["outcome"],
                    "evidence": [item["detectorId"] for item in decision["detectors"]],
                    "recommendationIds": [item["id"] for item in plane.recommendations if item["decisionId"] == decision_id],
                    "ledger": {"index": entry["index"], "hash": entry["hash"]},
                }
        raise HTTPException(status_code=404, detail=f"ledger receipt not found: {decision_id}")

    @app.get("/dashboard")
    def dashboard() -> dict[str, Any]:
        return plane.dashboard()

    @app.post("/deferred/drain")
    async def drain() -> list[dict[str, Any]]:
        changed = await plane.drain_deferred()
        for decision in changed:
            ledger.append({"type": "deferred-verification", "decision": decision})
        return changed

    @app.get("/ledger")
    def ledger_read() -> dict[str, Any]:
        return {"entries": ledger.read(), "verification": ledger.verify()}

    @app.post("/seed")
    async def seed() -> dict[str, Any]:
        return await seed_demo(plane, ledger)

    @app.post("/reset")
    async def reset() -> dict[str, Any]:
        plane.__init__()
        register_catalog(plane)
        ledger.reset()
        return {"reset": True, "dashboard": plane.dashboard(), "provenance": "empty operator-controlled state"}

    @app.post("/demo/finale")
    async def finale_demo() -> dict[str, Any]:
        """Run the scripted finale narrative against the live server state."""
        steps: list[dict[str, Any]] = []
        initial_event_count = len(plane.events)

        draft = await plane.decide(
            "customer-support", "ticketing", {"answer": "Your order is on its way."}, 10,
            [Detector("policy", .96)],
        )
        steps.append({"scene": "same answer / draft consequence", "decision": draft})

        execute = await plane.decide(
            "finance-decision", "credit", {"answer": "Approve the credit request."}, 10,
            [Detector("policy", .96)],
        )
        steps.append({"scene": "same answer / execute consequence", "decision": execute})

        mismatch = await plane.decide(
            "recruitment", "recruiting", {"candidate": "candidate-17"}, 10,
            [Detector("policy", .96)],
        )
        steps.append({"scene": "capability mismatch", "decision": mismatch})

        timeout = await plane.decide(
            "it-operations", "ops", {"service": "payments"}, 10,
            [Detector("slow-detector", .99, delay_ms=100, timeout_ms=5)],
            [Detector("deferred-verification", .98)],
        )
        steps.append({"scene": "bounded inline plus deferred verification", "decision": timeout})

        shadow = await plane.simulate("finance-decision", "credit", [Detector("candidate-policy", .55, status="failed")])
        steps.append({"scene": "shadow candidate policy", "shadow": shadow})

        freeze = Overlay("finale-finance-freeze", {"applicationId": "finance-decision"}, "deny", 200,
                         utc_now(), utc_now() + timedelta(minutes=10))
        steps.append({"scene": "deterministic arbitration", "control": plane._overlay_dict(plane.add_overlay(freeze))})
        controlled = await plane.decide(
            "finance-decision", "credit", {"answer": "Approve after freeze"}, 90,
            [Detector("policy", .99)],
        )
        steps.append({"scene": "control takes effect", "decision": controlled})
        changed = await plane.drain_deferred()
        for decision in changed:
            ledger.append({"type": "deferred-verification", "decision": decision})
        for event in plane.events[initial_event_count:]:
            ledger.append(event)
        return {"scenes": steps, "deferredVerified": len(changed), "dashboard": plane.dashboard(),
                "ledger": ledger.verify()}

    @app.post("/overlays/deny-finance")
    def deny_finance() -> dict[str, Any]:
        overlay = Overlay("finance-freeze", {"applicationId": "finance-decision"}, "deny", 100,
                          utc_now(), utc_now() + timedelta(hours=1))
        added = plane.add_overlay(overlay)
        ledger.append({"type": "control.changed", "data": {"operation": "overlay_added", "overlay": plane._overlay_dict(added)}})
        return plane._overlay_dict(added)

    @app.post("/overlays/{overlay_id}/rollback")
    def rollback_overlay(overlay_id: str) -> dict[str, Any]:
        try:
            plane.rollback_overlay(overlay_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        ledger.append({"type": "control.changed", "data": {"operation": "overlay_rolled_back", "overlayId": overlay_id}})
        return {"rolledBack": overlay_id, "dashboard": plane.dashboard()}

    return app


app = create_app(seed_on_startup=os.environ.get("CONTROLPLANE_SEED", "1") != "0")
