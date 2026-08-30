"""Detector contract.

Every detector returns a Signal. A Signal is deliberately multi-label: the brief
points out that bias, hallucination and privacy overlap in practice - a
fabricated detail about a named person is simultaneously a hallucination and a
privacy problem - so a detector may raise more than one label from one finding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..providers.base import Usage

# Canonical labels. A finding may carry several.
HALLUCINATION = "hallucination"
PRIVACY = "privacy"
BIAS = "bias"
WASTE = "waste"
UNVERIFIABLE = "unverifiable"


@dataclass
class Signal:
    name: str                      # detector id: grounding, uncertainty, pii, bias, cost
    score: float                   # 0.0 (no concern) .. 1.0 (maximum concern)
    confidence: float              # how much we trust this score, 0..1
    labels: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    usage: Usage = field(default_factory=Usage)
    ran_inline: bool = True

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 3),
            "labels": self.labels,
            "evidence": self.evidence[:6],
            "detail": self.detail,
            "latency_ms": round(self.latency_ms, 2),
            "usage": self.usage.as_dict(),
            "ran_inline": self.ran_inline,
        }
