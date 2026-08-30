"""Evaluation harness.

Reports the numbers a sceptical stakeholder actually asks for: false positive
rate, false negative rate, precision, recall, and how all four move as you slide
the operating point. The brief is explicit that over-flagging causes alert
fatigue and under-flagging causes liability, and that most real systems tune
this tradeoff rather than solve it. This harness is where that tuning is done in
the open.

Run:  python eval/run_eval.py [--sweep] [--json eval/results.json]

Note on the offline provider: self-consistency and the counterfactual bias probe
both need a real model to resample, so offline they abstain rather than emit a
number. Offline results therefore UNDER-report what the live system detects.
Cases marked live_only are skipped and counted separately.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controlplane.config import REGISTRY  # noqa: E402
from controlplane.engine import GateRequest, evaluate  # noqa: E402
from controlplane.providers import get_provider  # noqa: E402

DATA = Path(__file__).resolve().parent / "dataset.jsonl"


def load() -> list[dict]:
    return [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]


def run_case(c: dict) -> dict:
    res = evaluate(GateRequest(
        prompt=c.get("prompt", ""), answer=c["answer"], sources=c.get("sources", []),
        profile=c["profile"], jurisdiction=c.get("jurisdiction"),
        action_class=c.get("action_class"), regulated=c.get("regulated", False),
        task_class=c.get("task_class", "generic"), session_id=f"eval-{c['id']}",
        app=f"eval:{c['id']}",
    ))
    d = res.as_dict()
    flagged = d["decision"]["action"] != "pass"
    return {
        "id": c["id"], "name": c["name"], "category": c["category"],
        "profile": c["profile"], "expect_flag": c["expect_flag"],
        "route": d["decision"]["action"], "flagged": flagged,
        "price": d["risk"]["price"], "band": d["risk"]["band"],
        "confidence": d["risk"]["confidence"],
        "labels": d["risk"]["labels"], "expect_labels": c.get("expect_labels", []),
        "added_latency_ms": d["telemetry"]["added_latency_ms"],
        "correct": flagged == c["expect_flag"],
    }


def confusion(rows: list[dict]) -> dict:
    tp = sum(1 for r in rows if r["expect_flag"] and r["flagged"])
    fn = sum(1 for r in rows if r["expect_flag"] and not r["flagged"])
    fp = sum(1 for r in rows if not r["expect_flag"] and r["flagged"])
    tn = sum(1 for r in rows if not r["expect_flag"] and not r["flagged"])
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else 0.0,
        "accuracy": round((tp + tn) / max(1, len(rows)), 4),
    }


def sweep(cases: list[dict], deltas=range(-14, 15, 2)) -> list[dict]:
    """Shift every profile's pass threshold and watch the tradeoff move."""
    base = {pid: dict(p["thresholds"]) for pid, p in
            ((x["id"], x) for x in REGISTRY.list_profiles())}
    out = []
    for d in deltas:
        for pid, th in base.items():
            REGISTRY.profiles[pid]["thresholds"]["pass"] = max(1, th["pass"] + d)
        rows = [run_case(c) for c in cases]
        m = confusion(rows)
        m["pass_threshold_delta"] = d
        out.append(m)
    for pid, th in base.items():
        REGISTRY.profiles[pid]["thresholds"].update(th)
    return out


def sweep_tau(cases: list[dict], taus=(0.30, 0.40, 0.50, 0.55, 0.62, 0.70, 0.80, 0.90)) -> list[dict]:
    """Sweep the grounding support threshold.

    This is the operating point that actually matters. The pass-threshold sweep
    saturates because the contradiction floor is categorical, so it tells you
    little; support_tau is the continuous knob that trades alert fatigue against
    liability, and this is the curve an operator would be handed.
    """
    from controlplane.detectors import grounding
    original = grounding.SUPPORT_TAU
    out = []
    for t in taus:
        grounding.SUPPORT_TAU = t
        rows = [run_case(c) for c in cases]
        m = confusion(rows)
        m["support_tau"] = t
        out.append(m)
    grounding.SUPPORT_TAU = original
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--json", default=str(Path(__file__).resolve().parent / "results.json"))
    args = ap.parse_args()

    provider = get_provider()
    all_cases = load()
    live_only = [c for c in all_cases if c.get("live_only")]
    cases = [c for c in all_cases if not (c.get("live_only") and provider.name == "offline")]

    rows = [run_case(c) for c in cases]
    m = confusion(rows)

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)

    print(f"\nControlPlane evaluation - provider={provider.name}")
    print(f"cases evaluated: {len(rows)}   skipped (live-only): "
          f"{len(live_only) if provider.name == 'offline' else 0}\n")
    print(f"{'':>14}  flagged   not flagged")
    print(f"{'should flag':>14}  {m['tp']:^7}  {m['fn']:^11}")
    print(f"{'should not':>14}  {m['fp']:^7}  {m['tn']:^11}\n")
    print(f"precision {m['precision']:.3f}   recall {m['recall']:.3f}   F1 {m['f1']:.3f}")
    print(f"false-positive rate {m['false_positive_rate']:.3f}   "
          f"false-negative rate {m['false_negative_rate']:.3f}\n")

    print("by category:")
    for cat, rs in sorted(by_cat.items()):
        ok = sum(1 for r in rs if r["correct"])
        print(f"  {cat:<14} {ok}/{len(rs)}")

    misses = [r for r in rows if not r["correct"]]
    if misses:
        print("\nmisclassified:")
        for r in misses:
            kind = "FALSE NEGATIVE" if r["expect_flag"] else "FALSE POSITIVE"
            print(f"  [{kind}] {r['id']} {r['name']} -> {r['route']} (price {r['price']})")

    lat = sorted(r["added_latency_ms"] for r in rows)
    p50 = lat[len(lat) // 2] if lat else 0
    p95 = lat[int(len(lat) * 0.95) - 1] if lat else 0
    print(f"\nadded latency  p50 {p50:.1f} ms   p95 {p95:.1f} ms")

    results = {"provider": provider.name, "metrics": m, "rows": rows,
               "by_category": {k: confusion(v) for k, v in by_cat.items()},
               "latency_ms": {"p50": p50, "p95": p95},
               "skipped_live_only": [c["id"] for c in live_only] if provider.name == "offline" else []}

    if args.sweep:
        print("\noperating-point sweep (shifting every pass threshold):")
        print(f"{'delta':>6} {'prec':>7} {'recall':>7} {'FPR':>7} {'FNR':>7} {'F1':>7}")
        sw = sweep(cases)
        for s in sw:
            print(f"{s['pass_threshold_delta']:>6} {s['precision']:>7.3f} {s['recall']:>7.3f} "
                  f"{s['false_positive_rate']:>7.3f} {s['false_negative_rate']:>7.3f} {s['f1']:>7.3f}")
        results["sweep_pass_threshold"] = sw

        print("\noperating-point sweep (grounding support threshold):")
        print(f"{'tau':>6} {'prec':>7} {'recall':>7} {'FPR':>7} {'FNR':>7} {'F1':>7}")
        st = sweep_tau(cases)
        for s_ in st:
            print(f"{s_['support_tau']:>6.2f} {s_['precision']:>7.3f} {s_['recall']:>7.3f} "
                  f"{s_['false_positive_rate']:>7.3f} {s_['false_negative_rate']:>7.3f} {s_['f1']:>7.3f}")
        results["sweep_support_tau"] = st

    Path(args.json).write_text(json.dumps(results, indent=2))
    print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
