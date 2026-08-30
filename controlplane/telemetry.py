"""Runtime telemetry: latency, model calls, tokens, estimated cost, routing mix.

Reported because a governance layer that cannot account for its own overhead has
no business asking anyone else to account for theirs.
"""
from __future__ import annotations

import threading
from collections import Counter, defaultdict

import numpy as np


class Telemetry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.added_latency_ms: list[float] = []
        self.detector_latency: dict[str, list[float]] = defaultdict(list)
        self.routes = Counter()
        self.by_profile = defaultdict(Counter)
        self.model_calls = 0
        self.judge_calls = 0
        self.prompt_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0
        self.requests = 0
        self.budget_breaches = 0
        self.labels = Counter()
        self.overrides = Counter()

    def record(self, *, profile: str, route: str, added_latency_ms: float,
               detector_latency: dict[str, float], usage: dict, judge_used: bool,
               labels: list[str], breached_budget: bool) -> None:
        with self._lock:
            self.requests += 1
            self.added_latency_ms.append(added_latency_ms)
            for k, v in detector_latency.items():
                self.detector_latency[k].append(v)
            self.routes[route] += 1
            self.by_profile[profile][route] += 1
            self.model_calls += usage.get("calls", 0)
            self.judge_calls += 1 if judge_used else 0
            self.prompt_tokens += usage.get("prompt_tokens", 0)
            self.output_tokens += usage.get("output_tokens", 0)
            self.cost_usd += usage.get("cost_usd", 0.0)
            for lab in labels:
                self.labels[lab] += 1
            if breached_budget:
                self.budget_breaches += 1

    def record_override(self, verdict: str) -> None:
        with self._lock:
            self.overrides[verdict] += 1

    @staticmethod
    def _pct(values: list[float], q: float) -> float:
        return float(np.percentile(values, q)) if values else 0.0

    def snapshot(self) -> dict:
        with self._lock:
            n = max(1, self.requests)
            per_1k = (self.cost_usd / n) * 1000
            return {
                "requests": self.requests,
                "added_latency_ms": {
                    "p50": round(self._pct(self.added_latency_ms, 50), 1),
                    "p95": round(self._pct(self.added_latency_ms, 95), 1),
                    "p99": round(self._pct(self.added_latency_ms, 99), 1),
                    "mean": round(float(np.mean(self.added_latency_ms)) if self.added_latency_ms else 0.0, 1),
                },
                "detector_latency_p50_ms": {
                    k: round(self._pct(v, 50), 2) for k, v in self.detector_latency.items()
                },
                "routes": dict(self.routes),
                "route_share_pct": {k: round(100 * v / n, 1) for k, v in self.routes.items()},
                "by_profile": {k: dict(v) for k, v in self.by_profile.items()},
                "model_calls": self.model_calls,
                "judge_calls": self.judge_calls,
                "judge_rate_pct": round(100 * self.judge_calls / n, 2),
                "tokens": {"prompt": self.prompt_tokens, "output": self.output_tokens},
                "cost_usd_total": round(self.cost_usd, 5),
                "cost_usd_per_1k_interactions": round(per_1k, 4),
                "labels": dict(self.labels),
                "latency_budget_breaches": self.budget_breaches,
                "overrides": dict(self.overrides),
            }

    def reset(self) -> None:
        with self._lock:
            self.__init__()


TELEMETRY = Telemetry()
