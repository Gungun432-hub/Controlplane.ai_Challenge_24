"""Provider interface.

ControlPlane deliberately treats the foundation model as a black box reachable
only over an API. It never reads logits, attention or any other model internal,
because the brief is explicit that enterprises consume models via API and cannot
inspect them. Every signal we compute is derived from text we can see: the
prompt, the retrieved context, and one or more sampled completions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, other: "Usage") -> None:
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.output_tokens += other.output_tokens
        self.cost_usd += other.cost_usd

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass
class JudgeVerdict:
    supported: bool
    confidence: float
    rationale: str
    unverifiable: bool = False
    usage: Usage = field(default_factory=Usage)


class Provider(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def complete(self, prompt: str, n: int = 1, temperature: float = 0.7) -> tuple[list[str], Usage]: ...

    def judge(self, question: str, answer: str, sources: list[str]) -> JudgeVerdict: ...
