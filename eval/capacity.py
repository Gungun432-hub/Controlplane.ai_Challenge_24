"""Throughput measurement.

The brief's reference parameters assume "tens of thousands of interactions per
week across these use cases combined". A design that claims to sit in the live
path owes an answer to whether it can carry that, measured rather than asserted.

This runs the real gate at concurrency against the offline provider (no model
quota is spent) and converts sustained throughput into the weekly figure the
brief uses.

    python eval/capacity.py --requests 2000 --workers 16
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controlplane.engine import GateRequest, evaluate  # noqa: E402

KB = ("Band 8 employees accrue 21 days of annual leave. Notice period for band 8 "
      "is 60 days.")
MIX = [
    dict(profile="customer_support", action_class="advise", regulated=True,
         prompt="What is the response SLA for priority 1?",
         answer="Priority 1 incidents carry a 30 minute response SLA and a 4 hour resolution target.",
         sources=["Priority 1 incidents carry a 30 minute response SLA and a 4 hour resolution target."]),
    dict(profile="internal_knowledge", action_class="draft",
         prompt="What is the notice period for band 8?",
         answer="Notice period for band 8 is 60 days.", sources=[KB]),
    dict(profile="internal_knowledge", action_class="draft",
         prompt="How much leave do band 8 employees accrue?",
         answer="Band 8 employees serve a 90 day notice period.", sources=[KB]),
    dict(profile="decision_support", action_class="decide", regulated=True,
         prompt="Is a 150,000 accidental claim payable on HX-4412?",
         answer="Approve. Accidental damage is covered up to INR 200,000 with a INR 5,000 deductible.",
         sources=["Policy HX-4412 covers accidental damage up to INR 200,000 with a INR 5,000 deductible."]),
]


def one(i: int) -> float:
    row = dict(MIX[i % len(MIX)])
    t0 = time.perf_counter()
    evaluate(GateRequest(**row, session_id=f"cap-{i}", app="capacity", force_offline=True))
    return (time.perf_counter() - t0) * 1000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    print(f"warming up…")
    for i in range(20):
        one(i)

    print(f"running {args.requests} gated requests at concurrency {args.workers}…")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        lat = list(pool.map(one, range(args.requests)))
    wall = time.perf_counter() - t0

    lat.sort()
    rps = args.requests / wall
    print(f"\nwall clock          {wall:.2f} s")
    print(f"throughput          {rps:.0f} gated requests/second on one process")
    print(f"end-to-end latency  p50 {statistics.median(lat):.1f} ms   "
          f"p95 {lat[int(len(lat)*0.95)-1]:.1f} ms   p99 {lat[int(len(lat)*0.99)-1]:.1f} ms")
    print(f"\nweekly capacity     {rps*3600*24*7/1e6:.1f} million interactions/week, one process")
    print(f"brief's reference   tens of thousands per week")
    headroom = (rps * 3600 * 24 * 7) / 50_000
    print(f"headroom            {headroom:,.0f}x the 50,000/week figure used in the business case")
    print("\nMeasured against the offline provider, so this is the cost of the governance")
    print("layer itself. Live embedding and judge calls add provider latency on the small")
    print("fraction of traffic that needs them, which is the point of rationing them.")


if __name__ == "__main__":
    main()
