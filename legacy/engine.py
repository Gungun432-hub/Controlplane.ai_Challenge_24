from __future__ import annotations

import asyncio
import copy
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


ACTION_RADIUS = {"read": 0.1, "draft": 0.35, "advise": 0.7, "decide": 0.9, "execute": 1.0}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Detector:
    id: str
    score: float = 1.0
    status: str = "passed"
    reason: str | None = None
    delay_ms: int = 0
    timeout_ms: int = 100
    source: str = "builtin"


@dataclass
class Application:
    id: str
    name: str
    declared_capabilities: list[str]
    trusted_tool_capabilities: dict[str, list[str]]


@dataclass
class Tool:
    id: str
    name: str
    capabilities: list[str]


@dataclass
class Overlay:
    id: str
    scope: dict[str, str]
    effect: str
    priority: int
    starts_at: datetime
    expires_at: datetime
    reversible: bool = True
    version: int = 1
    active: bool = True


class ControlPlane:
    """Deterministic governance engine with explicit capability gating and weighted completeness."""

    def __init__(self) -> None:
        self.applications: dict[str, Application] = {}
        self.tools: dict[str, Tool] = {}
        self.decisions: dict[str, dict[str, Any]] = {}
        self.overlays: list[Overlay] = []
        self.events: list[dict[str, Any]] = []
        self.recommendations: list[dict[str, Any]] = []
        self._deferred: list[tuple[str, list[Detector]]] = []
        self._sequence = 0
        self._decision_number = 0
        self._recommendation_number = 0

    def register_application(self, application: Application) -> None:
        if not application.id or not application.name:
            raise ValueError("application id and name are required")
        application.declared_capabilities = list(dict.fromkeys(application.declared_capabilities))
        self.applications[application.id] = application

    def register_tool(self, tool: Tool) -> None:
        if not tool.id or not tool.name:
            raise ValueError("tool id and name are required")
        tool.capabilities = list(dict.fromkeys(tool.capabilities))
        self.tools[tool.id] = tool

    def recover_from_ledger(self, entries: list[dict[str, Any]]) -> int:
        """Rebuild the authoritative decision projection from persisted ledger records."""
        recovered = 0
        for entry in entries:
            record = entry.get("record", {})
            decision = record.get("decision") if record.get("type") == "decision" else record.get("data", {}).get("decision") if record.get("type") == "decision.created" else None
            if not isinstance(decision, dict) or not decision.get("id"):
                continue
            decision_id = str(decision["id"])
            if decision_id in self.decisions:
                continue
            self.decisions[decision_id] = copy.deepcopy(decision)
            try:
                self._decision_number = max(self._decision_number, int(decision_id.rsplit("_", 1)[1]))
            except (ValueError, IndexError):
                pass
            recovered += 1
            continue
        for entry in entries:
            record = entry.get("record", {})
            if record.get("type") != "control.changed":
                continue
            data = record.get("data", {})
            overlay_data = data.get("overlay")
            if not isinstance(overlay_data, dict) or any(item.id == overlay_data.get("id") for item in self.overlays):
                continue
            try:
                self.overlays.append(Overlay(
                    overlay_data["id"], overlay_data.get("scope", {}), overlay_data["effect"],
                    int(overlay_data.get("priority", 0)),
                    datetime.fromisoformat(overlay_data["startsAt"].replace("Z", "+00:00")),
                    datetime.fromisoformat(overlay_data["expiresAt"].replace("Z", "+00:00")),
                    bool(overlay_data.get("reversible", True)), int(overlay_data.get("version", 1)),
                    bool(overlay_data.get("active", True)),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        if recovered:
            for decision in self.decisions.values():
                self._recommend(decision)
            self._recommendation_number = max(
                [int(item["id"].rsplit("_", 1)[1]) for item in self.recommendations
                 if str(item.get("id", "")).startswith("rec_") and str(item["id"]).rsplit("_", 1)[-1].isdigit()] or [0]
            )
        return recovered

    def effective_capabilities(self, application_id: str, tool_id: str) -> tuple[list[str], bool]:
        app = self.applications.get(application_id)
        tool = self.tools.get(tool_id)
        if not app or not tool:
            raise ValueError(f"unknown application or tool: {application_id}/{tool_id}")
        trusted = app.trusted_tool_capabilities.get(tool_id, [])
        capabilities = [cap for cap in tool.capabilities if cap in app.declared_capabilities and cap in trusted]
        return capabilities, any(cap not in app.declared_capabilities or cap not in trusted for cap in tool.capabilities)

    @staticmethod
    def _capability_action_class(capability: str) -> str:
        normalized = capability.lower()
        if any(token in normalized for token in ["approve", "restart", "send", "execute", "deploy", "remove", "delete"]):
            return "execute"
        if any(token in normalized for token in ["schedule", "decide", "review", "approve", "route"]):
            return "decide"
        if any(token in normalized for token in ["write", "update", "create", "draft"]):
            return "draft"
        if any(token in normalized for token in ["read", "lookup", "fetch", "search"]):
            return "read"
        return "advise"

    def _effective_action_class(self, application_id: str, tool_id: str, capabilities: list[str], mismatch: bool) -> str:
        app = self.applications[application_id]
        tool = self.tools[tool_id]
        candidate_capabilities = [cap for cap in tool.capabilities if cap in app.declared_capabilities or mismatch]
        if not candidate_capabilities:
            return "read"
        rank = {"read": 1, "draft": 2, "advise": 3, "decide": 4, "execute": 5}
        return max((self._capability_action_class(cap) for cap in candidate_capabilities), key=lambda name: rank[name])

    def _derived_blast_radius(self, application_id: str, tool_id: str, declared: float, mismatch: bool) -> float:
        app = self.applications.get(application_id)
        tool = self.tools.get(tool_id)
        if not app or not tool:
            return max(0.0, declared)
        action_class = self._effective_action_class(application_id, tool_id, tool.capabilities, mismatch)
        derived = ACTION_RADIUS[action_class]
        if mismatch:
            derived = min(1.0, derived + 0.15)
        if declared > 0 and abs(declared - derived) > 0.25:
            return max(0.0, min(1.0, derived))
        return max(0.0, min(1.0, derived))

    def _runtime_detectors(self, application_id: str, tool_id: str, detectors: list[Detector]) -> list[Detector]:
        if detectors:
            return detectors
        if not self.applications.get(application_id) or not self.tools.get(tool_id):
            raise ValueError(f"unknown application or tool: {application_id}/{tool_id}")
        app = self.applications[application_id]
        tool = self.tools[tool_id]
        allowed = [cap for cap in tool.capabilities if cap in app.declared_capabilities]
        if not allowed:
            return [Detector(id=f"capability:{tool_id}", score=0.0, status="failed", reason="no trusted capabilities")]
        return [
            Detector(id=f"capability:{tool_id}", score=1.0 if len(allowed) > 0 else 0.0, status="passed" if len(allowed) > 0 else "failed",
                    reason="effective capability bound resolved"),
            Detector(id=f"policy:{tool_id}", score=0.95 if tool.capabilities else 0.0, status="passed" if tool.capabilities else "failed",
                    reason="deterministic policy check"),
        ]

    async def decide(
        self,
        application_id: str,
        tool_id: str,
        input_data: Any,
        blast_radius: float,
        detectors: list[Detector],
        deferred_detectors: list[Detector] | None = None,
    ) -> dict[str, Any]:
        if blast_radius < 0:
            raise ValueError("blastRadius must be non-negative")
        self._decision_number += 1
        decision_id = f"dec_{self._decision_number:04d}"
        started = time.perf_counter()
        capabilities, mismatch = self.effective_capabilities(application_id, tool_id)
        action_class = self._effective_action_class(application_id, tool_id, capabilities, mismatch)
        normalized_blast_radius = self._derived_blast_radius(application_id, tool_id, float(blast_radius), mismatch)
        runtime_detectors = self._runtime_detectors(application_id, tool_id, detectors)
        executions = await self._collect_detectors(runtime_detectors, decision_id)
        overlay = self._active_overlay(application_id, tool_id)
        outcome = self._resolve_outcome(executions, overlay, mismatch, action_class)
        decision = {
            "id": decision_id,
            "applicationId": application_id,
            "toolId": tool_id,
            "outcome": outcome,
            "createdAt": iso(utc_now()),
            "decisionLatencyMs": max(0, round((time.perf_counter() - started) * 1000)),
            "verificationLatencyMs": None,
            "detectors": executions,
            "effectiveCapabilities": capabilities,
            "capabilityMismatch": mismatch,
            "actionClass": action_class,
            "declaredBlastRadius": float(blast_radius),
            "blastRadius": normalized_blast_radius,
            "completeness": self._completeness(executions, normalized_blast_radius),
            "input": input_data,
        }
        self.decisions[decision_id] = decision
        self._append("decision.created", decision_id, {"decision": copy.deepcopy(decision)})
        if mismatch:
            self._append("control.changed", decision_id, {"kind": "capability_mismatch", "applicationId": application_id, "toolId": tool_id})
        if deferred_detectors:
            self._deferred.append((decision_id, deferred_detectors))
            self._append("detector.lifecycle", decision_id, {"phase": "deferred", "detectorIds": [d.id for d in deferred_detectors]})
        self._recommend(decision)
        return copy.deepcopy(decision)

    async def drain_deferred(self) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        while self._deferred:
            decision_id, deferred_detectors = self._deferred.pop(0)
            decision = self.decisions[decision_id]
            started = time.perf_counter()
            executions = await self._collect_detectors(deferred_detectors, decision_id)
            decision["detectors"].extend(executions)
            decision["verificationLatencyMs"] = max(0, round((time.perf_counter() - started) * 1000))
            decision["completeness"] = self._completeness(decision["detectors"], decision["blastRadius"])
            self._append("deferred.verification", decision_id, {"executions": executions})
            self._recommend(decision)
            changed.append(copy.deepcopy(decision))
        return changed

    def add_overlay(self, overlay: Overlay) -> Overlay:
        if overlay.expires_at <= overlay.starts_at:
            raise ValueError("overlay must expire after it starts")
        prior = [old for old in self.overlays if old.id == overlay.id]
        overlay.version = (prior[-1].version if prior else 0) + 1
        self.overlays.append(overlay)
        self._append("control.changed", overlay.id, {"operation": "overlay_added", "overlay": self._overlay_dict(overlay)})
        return overlay

    def rollback_overlay(self, overlay_id: str) -> None:
        matching = [overlay for overlay in self.overlays if overlay.id == overlay_id and overlay.active]
        if not matching:
            raise ValueError(f"active overlay not found: {overlay_id}")
        for overlay in matching:
            overlay.active = False
        self._append("control.changed", overlay_id, {"operation": "overlay_rolled_back"})

    async def simulate(self, application_id: str, tool_id: str, detectors: list[Detector]) -> dict[str, Any]:
        capabilities, mismatch = self.effective_capabilities(application_id, tool_id)
        action_class = self._effective_action_class(application_id, tool_id, capabilities, mismatch)
        results = await self._collect_detectors(self._runtime_detectors(application_id, tool_id, detectors), f"sim:{application_id}:{tool_id}")
        outcome = self._resolve_outcome(results, self._active_overlay(application_id, tool_id), mismatch, action_class)
        citations = [result["reason"] for result in results if result.get("reason")]
        payload = {"outcome": outcome, "effectiveCapabilities": capabilities, "citations": citations, "actionClass": action_class}
        self._append("simulation.completed", f"{application_id}/{tool_id}", payload)
        return payload

    def dashboard(self) -> dict[str, Any]:
        portfolio = self.project_portfolio()
        now = utc_now()
        active = sum(1 for overlay in self.overlays if overlay.active and overlay.starts_at <= now < overlay.expires_at)
        app_rows = []
        for application in sorted(self.applications.values(), key=lambda item: item.name):
            decisions = [decision for decision in self.decisions.values() if decision["applicationId"] == application.id]
            if not decisions:
                app_rows.append({"id": application.id, "name": application.name, "state": "not_available", "health": "not_available",
                                 "risk": 0.0, "exposure": 0.0, "spend": 0.0, "completeness": None,
                                 "backlog": 0, "recentDecisions": 0})
                continue
            exposure = sum(decision["blastRadius"] for decision in decisions if decision["outcome"] != "deny")
            app_rows.append({
                "id": application.id,
                "name": application.name,
                "state": "healthy" if all(decision["outcome"] == "allow" for decision in decisions) else "review" if any(decision["outcome"] == "review" for decision in decisions) else "critical",
                "health": "healthy" if all(decision["outcome"] == "allow" for decision in decisions) else "review" if any(decision["outcome"] == "review" for decision in decisions) else "critical",
                "risk": sum(decision["blastRadius"] for decision in decisions),
                "exposure": round(exposure, 3),
                "spend": round(sum(decision["blastRadius"] * 10 for decision in decisions), 3),
                "completeness": sum(decision["completeness"] for decision in decisions) / len(decisions),
                "backlog": sum(decision["outcome"] == "review" for decision in decisions),
                "recentDecisions": len(decisions),
            })
        return {
            "portfolio": portfolio,
            "applications": app_rows,
            "tools": len(self.tools),
            "decisions": len(self.decisions),
            "pendingEvents": len(self.events),
            "recommendations": len(self.recommendations),
            "activeOverlays": active,
            "provenance": {
                "source": "synthetic deterministic demo" if self.decisions else "empty operator-controlled state",
                "authoritativeStore": "hash-chained JSONL ledger",
                "recommendationPolicyVersion": "1.0",
            },
        }

    def project_portfolio(self) -> dict[str, Any]:
        decisions = list(self.decisions.values())
        if not decisions:
            return {
                "decisions": 0,
                "exposure": 0.0,
                "spend": 0.0,
                "reviewerCapacity": 100,
                "verificationCapacity": 100,
                "backlog": 0,
                "staleExposure": 0.0,
                "completeness": None,
                "health": "not_available",
                "budget": self._budget_snapshot(0, 0),
            }
        backlog = sum(decision["outcome"] == "review" for decision in decisions)
        exposure = sum(decision["blastRadius"] for decision in decisions if decision["outcome"] != "deny")
        spend = sum(max(0.0, decision["blastRadius"] * 10.0) for decision in decisions)
        weighted_total = sum(max(0.0, decision["blastRadius"]) for decision in decisions if decision["blastRadius"] > 0)
        completeness = sum((decision["blastRadius"] * decision["completeness"]) for decision in decisions) / weighted_total if weighted_total else 0.0
        stale = sum(decision["blastRadius"] for decision in decisions if decision["verificationLatencyMs"] is None and (utc_now() - datetime.fromisoformat(decision["createdAt"].replace("Z", "+00:00"))) > timedelta(days=1))
        risk_state = "critical" if completeness < 0.5 or stale > exposure * 0.5 else "degraded" if backlog or completeness < 0.8 else "healthy"
        return {
            "decisions": len(decisions),
            "exposure": round(exposure, 3),
            "spend": round(spend, 3),
            "reviewerCapacity": max(0, 100 - backlog * 10),
            "verificationCapacity": max(0, 100 - len(self._deferred) * 10),
            "backlog": backlog,
            "staleExposure": round(stale, 3),
            "completeness": round(completeness, 3),
            "health": risk_state,
            "budget": self._budget_snapshot(spend, backlog),
        }

    @staticmethod
    def _budget_snapshot(spend: float, backlog: int) -> dict[str, Any]:
        spend_limit = float(os.environ.get("CONTROLPLANE_SPEND_BUDGET", "1000"))
        reviewer_limit = int(os.environ.get("CONTROLPLANE_REVIEWER_CAPACITY", "100"))
        verification_limit = int(os.environ.get("CONTROLPLANE_VERIFICATION_CAPACITY", "100"))
        return {
            "spend": round(spend, 3),
            "spendBudget": spend_limit,
            "spendRemaining": round(max(0.0, spend_limit - spend), 3),
            "reviewerUsed": backlog,
            "reviewerCapacity": reviewer_limit,
            "verificationCapacity": verification_limit,
            "withinBudget": spend <= spend_limit,
        }

    async def _collect_detectors(self, detectors: list[Detector], decision_id: str) -> list[dict[str, Any]]:
        async def run(detector: Detector) -> dict[str, Any]:
            started = time.perf_counter()
            try:
                if detector.delay_ms > detector.timeout_ms:
                    await asyncio.sleep(detector.timeout_ms / 1000)
                    result = {"detectorId": detector.id, "score": 0.0, "status": "timed_out", "latencyMs": detector.timeout_ms,
                              "reason": f"detector {detector.id} exceeded {detector.timeout_ms}ms", "source": detector.source}
                else:
                    await asyncio.wait_for(asyncio.sleep(detector.delay_ms / 1000), timeout=max(0.001, detector.timeout_ms / 1000.0))
                    result = {"detectorId": detector.id, "score": detector.score, "status": detector.status,
                              "latencyMs": max(0, round((time.perf_counter() - started) * 1000)), "source": detector.source}
                    if detector.reason:
                        result["reason"] = detector.reason
            except asyncio.TimeoutError:
                result = {"detectorId": detector.id, "score": 0.0, "status": "timed_out", "latencyMs": detector.timeout_ms,
                          "reason": f"detector {detector.id} exceeded {detector.timeout_ms}ms", "source": detector.source}
            except Exception as exc:  # pragma: no cover - defensive fallback
                result = {"detectorId": detector.id, "score": None, "status": "error", "latencyMs": 0,
                          "reason": str(exc), "source": detector.source}
            self._append("detector.lifecycle", decision_id, result)
            return result
        return await asyncio.gather(*(run(detector) for detector in detectors))

    def _resolve_outcome(self, detectors: list[dict[str, Any]], overlay: Overlay | None, mismatch: bool, action_class: str) -> str:
        if overlay and overlay.effect == "deny":
            return "deny"
        if overlay and overlay.effect == "require_review":
            return "review"
        if mismatch and action_class == "execute":
            return "deny"
        if mismatch:
            return "review"
        if any(detector["status"] in {"failed", "timed_out", "error"} for detector in detectors):
            return "review"
        return "allow" if detectors and all((detector["score"] or 0) >= 0.8 for detector in detectors) else "review"

    @staticmethod
    def _completeness(detectors: list[dict[str, Any]], blast_radius: float) -> float:
        if not detectors:
            return 0.0 if blast_radius > 0 else 0.0
        verified = sum(detector["status"] in {"passed", "failed"} for detector in detectors)
        return min(1.0, max(0.0, (verified / len(detectors)) * (1.0 if blast_radius == 0 else 1.0 / (1.0 + blast_radius))))

    def _active_overlay(self, application_id: str, tool_id: str) -> Overlay | None:
        now = utc_now()
        eligible = [
            overlay for overlay in self.overlays
            if overlay.active and overlay.starts_at <= now < overlay.expires_at and
            (not overlay.scope.get("applicationId") or overlay.scope["applicationId"] == application_id) and
            (not overlay.scope.get("toolId") or overlay.scope["toolId"] == tool_id)
        ]
        return sorted(eligible, key=lambda overlay: (overlay.priority, overlay.version), reverse=True)[0] if eligible else None

    def _recommend(self, decision: dict[str, Any]) -> None:
        rules: list[tuple[str, str, dict[str, Any]]] = []
        if decision["capabilityMismatch"]:
            rules.append(("CAPABILITY_MISMATCH", "Align declared, trusted, and observed capabilities before allowing this tool.", {"capabilityGap": len(decision["effectiveCapabilities"])}))
        if not decision["detectors"]:
            rules.append(("INSUFFICIENT_EVIDENCE", "No executable evidence was gathered for this decision.", {"detectorCount": 0}))
        if decision["completeness"] < 0.8:
            rules.append(("INCOMPLETE_VERIFICATION", "Increase detector coverage or reduce blast radius.", {"completeness": round(decision["completeness"], 3), "blastRadius": round(decision["blastRadius"], 3)}))
        for rule, message, evidence in rules:
            self._recommendation_number += 1
            recommendation = {
                "id": f"rec_{self._recommendation_number:04d}",
                "rule": rule,
                "ruleVersion": "1.0",
                "decisionId": decision["id"],
                "message": message,
                "evidence": evidence,
                "expectedEffect": "review" if rule == "CAPABILITY_MISMATCH" else "increase_confidence",
                "citations": ["registry.effectiveCapabilities"] if rule == "CAPABILITY_MISMATCH" else ["governance.completeness"],
                "insufficientEvidence": rule == "INSUFFICIENT_EVIDENCE",
            }
            self.recommendations.append(recommendation)
            self._append("recommendation.created", decision["id"], {"recommendation": recommendation})

    def _append(self, event_type: str, aggregate_id: str, data: dict[str, Any]) -> None:
        self._sequence += 1
        self.events.append({"sequence": self._sequence, "type": event_type, "timestamp": iso(utc_now()), "aggregateId": aggregate_id, "data": copy.deepcopy(data)})

    @staticmethod
    def _overlay_dict(overlay: Overlay) -> dict[str, Any]:
        return {
            "id": overlay.id,
            "version": overlay.version,
            "scope": overlay.scope,
            "effect": overlay.effect,
            "priority": overlay.priority,
            "startsAt": iso(overlay.starts_at),
            "expiresAt": iso(overlay.expires_at),
            "reversible": overlay.reversible,
            "active": overlay.active,
        }
