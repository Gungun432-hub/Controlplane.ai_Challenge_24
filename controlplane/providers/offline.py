"""Offline provider.

Used for CI, for the reproducible evaluation harness, and so that anybody can
clone the repository and run the whole system with no API key and no network.
Embeddings come from a hashing vectoriser over character n-grams, which is a
genuine lexical embedding - weaker than a neural one, but deterministic and
free. The judge is a conservative rule-based stand-in that never claims more
confidence than the lexical evidence supports.
"""
from __future__ import annotations

import hashlib
import re

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from .base import JudgeVerdict, Usage

_VEC = HashingVectorizer(
    analyzer="char_wb", ngram_range=(3, 5), n_features=2048,
    alternate_sign=False, norm="l2",
)


class OfflineProvider:
    name = "offline"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return _VEC.transform(texts).toarray().tolist()

    def complete(self, prompt: str, n: int = 1, temperature: float = 0.7) -> tuple[list[str], Usage]:
        """Deterministic pseudo-resampling.

        Self-consistency needs several samples of the *same* question. Offline we
        cannot really resample a model, so we derive stable variants from the
        prompt hash. This keeps the code path identical to the live one; the
        numbers it produces are only meaningful in the live provider.
        """
        outs = []
        for i in range(n):
            h = hashlib.sha256(f"{prompt}|{i}".encode()).hexdigest()[:8]
            outs.append(f"[offline-sample-{i}:{h}]")
        return outs, Usage(calls=0)

    def judge(self, question: str, answer: str, sources: list[str]) -> JudgeVerdict:
        if not sources:
            return JudgeVerdict(
                supported=False, confidence=0.0, unverifiable=True,
                rationale="No source material was retrieved, so the claim cannot be "
                          "checked either way. Marked unverifiable rather than false.",
            )
        joined = " ".join(sources).lower()
        toks = [t for t in re.findall(r"[a-z0-9%.]+", answer.lower()) if len(t) > 3]
        if not toks:
            return JudgeVerdict(True, 0.5, "No checkable content in the answer.")
        hits = sum(1 for t in toks if t in joined)
        ratio = hits / len(toks)
        return JudgeVerdict(
            supported=ratio >= 0.5,
            confidence=round(min(0.85, abs(ratio - 0.5) * 2), 3),
            rationale=f"Lexical support {ratio:.0%} of checkable tokens appear in the retrieved sources.",
        )
