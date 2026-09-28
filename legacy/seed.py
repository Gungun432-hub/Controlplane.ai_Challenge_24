from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from .engine import ControlPlane, Detector, Overlay, utc_now
from .fixtures import APPLICATIONS, TOOLS, scenario_detectors
from .ledger import JsonlLedger


def register_catalog(plane: ControlPlane) -> None:
    for application in APPLICATIONS:
        plane.register_application(application)
    for tool in TOOLS:
        plane.register_tool(tool)


async def seed_demo(plane: ControlPlane, ledger: JsonlLedger) -> dict[str, Any]:
    """Populate one server instance with the deterministic live-demo scenario."""
    register_catalog(plane)
    if plane.decisions:
        return {"seeded": False, "reason": "already populated", "dashboard": plane.dashboard()}

    await plane.decide("finance-decision", "credit", {"amount": 25000}, 80, scenario_detectors("finance-decision"))
    await plane.decide("recruitment", "recruiting", {"candidate": "candidate-17"}, 30, [Detector("policy", .94)])
    await plane.decide(
        "it-operations",
        "ops",
        {"service": "payments"},
        40,
        [Detector("slow-change-check", .99, delay_ms=50, timeout_ms=5)],
    )
    await plane.simulate("marketing", "campaigns", [Detector("policy", .95)])
    plane.add_overlay(
        Overlay("finance-freeze", {"applicationId": "finance-decision"}, "deny", 100,
                utc_now(), utc_now() + timedelta(minutes=10))
    )
    await plane.decide("finance-decision", "credit", {"amount": 50000}, 90, [Detector("policy", .99)])

    for event in plane.events:
        ledger.append(event)
    return {"seeded": True, "dashboard": plane.dashboard()}
