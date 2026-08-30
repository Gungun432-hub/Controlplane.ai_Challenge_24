"""Run the scenario suite against a live ControlPlane server and print a transcript."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenarios as S  # noqa: E402

BASE = "http://127.0.0.1:8000"


def _post(client, path, body):
    r = client.post(f"{BASE}{path}", json=body, timeout=60)
    r.raise_for_status()
    return r.json()


def line(ch="-", n=78):
    print(ch * n)


def show(res: dict, label: str, show_policy: bool = False) -> None:
    d, risk, tel = res["decision"], res["risk"], res["telemetry"]
    print(f"  {label}")
    if show_policy:
        pol = res["policy"]
        print(f"    policy         {pol['id']} v{pol['version']}  regime={pol.get('regime') or 'none'}")
        print(f"    thresholds     pass<{pol['thresholds']['pass']}  "
              f"repair<{pol['thresholds']['repair']}  escalate>={pol['thresholds']['escalate']}")
        print(f"    weights        {pol['weights']}")
    print(f"    route          {d['action'].upper()}")
    print(f"    risk price     {risk['price']}  (confidence band {risk['band'][0]}-{risk['band'][1]},"
          f" confidence {risk['confidence']})")
    print(f"    labels         {', '.join(risk['labels']) or 'none'}")
    print(f"    dominant       {risk['dominant']}")
    print(f"    reason         {d['reason']}")
    if d["repairs"]:
        print(f"    repairs        {', '.join(d['repairs'])}")
    if d["surfaced_uncertainty"]:
        print(f"    surfaced       {d['surfaced_uncertainty']}")
    if d["abstained"]:
        print(f"    abstained      yes")
    print(f"    added latency  {tel['added_latency_ms']} ms  (budget {tel['latency_budget_ms']} ms)"
          f"   judge used: {tel['judge_used']}")
    print(f"    ledger         #{res['ledger']['index']}  {res['ledger']['entry_hash'][:16]}...")
    print()


def run_ab(client, spec: dict) -> None:
    line("=")
    print(spec["title"].upper())
    print(f"  why: {spec['why']}\n")
    print(f'  prompt: "{spec["payload"]["prompt"]}"')
    print(f'  answer: "{spec["payload"]["answer"]}"')
    print(f'  sources: {len(spec["payload"]["sources"])}\n')
    for run in spec["runs"]:
        body = dict(spec["payload"])
        body.update({k: v for k, v in run.items() if k != "label"})
        show(_post(client, "/v1/gate", body), run["label"], show_policy=True)


def run_multiturn(client, spec: dict) -> None:
    line("=")
    print(spec["title"].upper())
    print(f"  why: {spec['why']}\n")
    for i, turn in enumerate(spec["turns"], 1):
        body = dict(turn)
        body.update({"profile": spec["profile"], "session_id": spec["session_id"],
                     "app": "hr-copilot"})
        res = _post(client, "/v1/gate", body)
        print(f'  turn {i}: "{turn["prompt"]}"')
        print(f'    -> "{turn["answer"]}"')
        show(res, f"session risk now {res['session']['accumulated_risk']}")


def run_override(client) -> None:
    line("=")
    print("HUMAN OVERRIDE AND FEEDBACK".upper())
    print("  why: the brief asks how flagged or overridden cases feed back. A reviewer's\n"
          "  verdict is written to the ledger with their id and moves the calibration\n"
          "  offset for that policy. The offset is reported, never silent.\n")
    body = {"prompt": "What is the exit load?",
            "answer": "There is no exit load on this fund at any point.",
            "sources": [S.FUND_SRC], "profile": "customer_support",
            "action_class": "advise", "regulated": True, "app": "wealth-advisory"}
    res = _post(client, "/v1/gate", body)
    show(res, "before review")
    before = _post(client, "/api/policies", {}) if False else httpx.get(f"{BASE}/api/policies").json()
    print(f"  calibration before: {before['calibration']['offsets']}")
    ov = _post(client, "/api/override", {
        "request_id": res["request_id"], "reviewer_id": "reviewer:gungun.jain",
        "verdict": "confirmed", "note": "Exit load of 1 percent does apply before 12 months."})
    print(f"  reviewer verdict recorded -> ledger #{ov['ledger_index']}")
    print(f"  calibration after:  {ov['calibration']}")
    print("  the ledger now holds both the original decision and who overrode it.\n")


def run_surge(client, multiplier: int = 3, base: int = 20) -> None:
    line("=")
    print("SURGE BEHAVIOUR".upper())
    print(f"  why: the system must hold its latency budget when volume spikes. "
          f"Running {base} then {base * multiplier} requests.\n")
    body = {"prompt": "What is the response SLA for priority 1?",
            "answer": "Priority 1 incidents carry a 30 minute response SLA.",
            "sources": ["Priority 1 incidents carry a 30 minute response SLA and a 4 hour "
                        "resolution target."],
            "profile": "customer_support", "action_class": "advise", "app": "surge-test"}
    for label, n in (("normal", base), (f"{multiplier}x surge", base * multiplier)):
        httpx.get(f"{BASE}/api/telemetry")
        t0 = time.perf_counter()
        lat = []
        for _ in range(n):
            r = _post(client, "/v1/gate", body)
            lat.append(r["telemetry"]["added_latency_ms"])
        wall = time.perf_counter() - t0
        lat.sort()
        print(f"  {label:<12} n={n:<4} wall {wall:5.2f}s   "
              f"added latency p50 {lat[len(lat)//2]:6.2f} ms  p95 {lat[int(len(lat)*0.95)-1]:6.2f} ms")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    globals()["BASE"] = args.base

    with httpx.Client() as client:
        health = client.get(f"{args.base}/health").json()
        print(f"\nControlPlane scenario suite   provider={health['provider']}  live={health['live']}\n")
        picks = args.only.split(",") if args.only else []

        def want(name): return not picks or name in picks

        if want("policy"):      run_ab(client, S.POLICY_DIVERGENCE)
        if want("jurisdiction"): run_ab(client, S.JURISDICTION)
        if want("overlap"):     run_ab(client, S.OVERLAP)
        if want("abstain"):     run_ab(client, S.ABSTAIN)
        if want("gate"):        run_ab(client, S.HARD_GATE)
        if want("trap"):        run_ab(client, S.FALSE_POSITIVE_TRAP)
        if want("multiturn"):   run_multiturn(client, S.MULTITURN)
        if want("override"):    run_override(client)
        if want("surge"):       run_surge(client)

        line("=")
        tel = client.get(f"{args.base}/api/telemetry").json()
        print("RUNTIME TELEMETRY")
        print(json.dumps(tel, indent=2)[:1600])
        ver = client.get(f"{args.base}/api/ledger/verify").json()
        print(f"\nledger verification: {ver}")


if __name__ == "__main__":
    main()
