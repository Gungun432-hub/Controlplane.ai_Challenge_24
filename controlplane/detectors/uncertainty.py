"""Black-box uncertainty via self-consistency.

Round 1 of this project proposed reading token-level log-probabilities. That was
wrong for the stated enterprise setting: most managed model APIs do not expose
log-probs at all, and the brief is explicit that enterprises consume a
foundation model via API rather than owning it outright.

So the primary signal here is provider-independent. We resample the same prompt
`n` times at non-zero temperature and measure semantic agreement between the
samples. A model that is genuinely confident converges on the same answer; a
model that is confabulating produces answers that disagree with each other while
each individually sounds assured. Log-probs, where a provider happens to offer
them, are accepted as an optional fast path but never required.

Cost note: resampling is not free. It is therefore an inline detector only for
policies whose latency budget allows it, and it is skipped entirely when the
response is already obviously safe.
"""
from __future__ import annotations

import time

import numpy as np

from ..providers.base import Usage
from .base import HALLUCINATION, Signal

DEFAULT_SAMPLES = 3


def _mean_pairwise_cos(vectors: list[list[float]]) -> float:
    if len(vectors) < 2:
        return 1.0
    m = np.array(vectors, dtype=float)
    m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
    sim = m @ m.T
    iu = np.triu_indices(len(m), k=1)
    return float(sim[iu].mean())


def detect(provider, answer: str, prompt: str = "", samples: int = DEFAULT_SAMPLES,
           logprob_hint: float | None = None, **_) -> Signal:
    t0 = time.perf_counter()
    usage = Usage()

    if logprob_hint is not None:
        # Fast path when the provider exposes token probabilities.
        score = float(max(0.0, min(1.0, 1.0 - logprob_hint)))
        return Signal("uncertainty", score, 0.75, detail={"method": "logprob", "source": "provider"},
                      latency_ms=(time.perf_counter() - t0) * 1000)

    if not prompt:
        return Signal("uncertainty", 0.0, 0.15,
                      detail={"method": "unavailable", "reason": "no prompt to resample"},
                      latency_ms=(time.perf_counter() - t0) * 1000)

    if getattr(provider, "name", "") == "offline":
        # Honesty guard. Self-consistency requires genuinely independent samples
        # from a real model. The offline provider cannot produce them, so rather
        # than emit a confident-looking number derived from placeholder text we
        # abstain from this signal entirely and say so. Offline evaluation
        # numbers therefore under-report what the live system detects.
        return Signal(
            "uncertainty", score=0.0, confidence=0.0,
            evidence=["self-consistency unavailable: offline provider cannot resample a model"],
            detail={"method": "unavailable_offline", "requires": "live model provider"},
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    variants, u = provider.complete(prompt, n=samples, temperature=0.8)
    usage.add(u)
    texts = [answer] + [v for v in variants if v]
    vecs = provider.embed(texts)
    agreement = _mean_pairwise_cos(vecs)

    # Agreement is bounded well above zero for any two English texts, so we
    # rescale from an empirical floor rather than treating 0 as "no agreement".
    floor = 0.35
    norm = (agreement - floor) / (1.0 - floor)
    score = float(max(0.0, min(1.0, 1.0 - norm)))

    labels = [HALLUCINATION] if score > 0.55 else []
    return Signal(
        "uncertainty", score=score, confidence=0.7 if samples >= 3 else 0.5,
        labels=labels,
        evidence=[f"{samples} resamples agreed at {agreement:.2f} mean pairwise similarity"],
        detail={"method": "self_consistency", "samples": samples,
                "mean_pairwise_similarity": round(agreement, 3), "floor": floor},
        latency_ms=(time.perf_counter() - t0) * 1000, usage=usage,
    )
