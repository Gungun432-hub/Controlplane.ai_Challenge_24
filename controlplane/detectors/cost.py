"""Waste detection.

The interesting quantity is not spend, it is spend that produced nothing. Two
signals combine:

  1. Token overrun against a rolling baseline for the same task class. An answer
     three times longer than the median answer to that kind of question is
     usually a model that failed to find the point.
  2. The rework signal. If the user asks a semantically near-identical question
     again inside the same session, the previous answer did not land. Rework is
     the cheapest ground truth about answer quality that exists in production,
     and it requires no labels.
"""
from __future__ import annotations

import time
from collections import defaultdict

import numpy as np

from .base import WASTE, Signal

# Rolling per-task-class token baselines, seeded with sane defaults and updated
# online. In production this would be a shared store, not process memory.
_BASELINE: dict[str, list[int]] = defaultdict(list)
_SEED = {"summarise": 180, "lookup": 120, "extract": 150, "advise": 260,
         "decide": 200, "draft": 300, "generic": 220}

REWORK_TAU = 0.86      # cosine similarity above which two asks are "the same"


def observe(task_class: str, tokens: int) -> None:
    _BASELINE[task_class].append(int(tokens))
    if len(_BASELINE[task_class]) > 200:
        _BASELINE[task_class].pop(0)


def baseline_for(task_class: str) -> float:
    seen = _BASELINE.get(task_class, [])
    if len(seen) >= 8:
        return float(np.median(seen))
    return float(_SEED.get(task_class, _SEED["generic"]))


def approx_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def detect(provider, answer: str, prompt: str = "", task_class: str = "generic",
           session_prompts: list[str] | None = None, **_) -> Signal:
    t0 = time.perf_counter()
    tokens = approx_tokens(answer)
    base = baseline_for(task_class)
    ratio = tokens / base if base else 1.0
    overrun = max(0.0, (ratio - 1.5) / 3.0)      # nothing below 1.5x counts

    rework, rework_sim = 0.0, 0.0
    prior = [p for p in (session_prompts or []) if p and p != prompt]
    if prior and prompt:
        vecs = provider.embed([prompt] + prior)
        m = np.array(vecs, dtype=float)
        m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        sims = (m[0:1] @ m[1:].T).ravel()
        rework_sim = float(sims.max())
        if rework_sim >= REWORK_TAU:
            rework = 0.7

    observe(task_class, tokens)
    score = float(min(1.0, overrun + rework))
    evidence = []
    if overrun > 0:
        evidence.append(f"{ratio:.1f}x the {task_class} token baseline ({tokens} vs {base:.0f})")
    if rework:
        evidence.append(f"user re-asked a near-identical question (similarity {rework_sim:.2f}) - "
                        f"the earlier answer did not land")

    return Signal(
        "cost", score=score, confidence=0.6 if prior else 0.45,
        labels=[WASTE] if score > 0.4 else [],
        evidence=evidence or ["within normal spend for this task class"],
        detail={"tokens": tokens, "baseline": round(base, 1), "ratio": round(ratio, 2),
                "rework_similarity": round(rework_sim, 3), "task_class": task_class},
        latency_ms=(time.perf_counter() - t0) * 1000,
    )
