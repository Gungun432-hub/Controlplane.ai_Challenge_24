"""Google Gemini provider.

This is the live path. It is used for two things only:

  1. Embeddings, for grounding and self-consistency. Cheap, called on every
     response that is not trivially safe.
  2. LLM-as-judge, for responses the cheap gate could not resolve. Expensive,
     and therefore rationed by policy - see `Policy.judge_cfg`.

That split is ControlPlane's own thesis applied to itself: spend the expensive
oversight only where the risk price justifies it.
"""
from __future__ import annotations

import json
import os
import re

import httpx

from .base import JudgeVerdict, Usage

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

# Published list prices for the Flash tier, USD per 1M tokens. Used only to
# produce an *estimated* cost figure in telemetry; it is not billing data.
PRICE_IN_PER_M = 0.075
PRICE_OUT_PER_M = 0.30
PRICE_EMBED_PER_M = 0.0

JUDGE_SYSTEM = """You are a verification component inside an AI governance system.
You are NOT answering the user's question. You are checking whether the ANSWER is
supported by the SOURCES provided.

Rules:
- Judge only support, never truth. If the sources do not cover a claim, that claim
  is UNVERIFIABLE, not false.
- If there are no usable sources, return unverifiable=true.
- Be conservative. Under-claiming support is much cheaper than over-claiming it.

Return ONLY a JSON object:
{"supported": bool, "unverifiable": bool, "confidence": 0.0-1.0, "rationale": "one sentence"}"""


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str | None = None, judge_model: str | None = None,
                 embed_model: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set; use CONTROLPLANE_PROVIDER=offline instead")
        self.judge_model = judge_model or os.environ.get("GEMINI_JUDGE_MODEL", "gemini-flash-latest")
        self.embed_model = embed_model or os.environ.get("GEMINI_EMBED_MODEL", "text-embedding-004")
        self._client = httpx.Client(timeout=timeout, headers={"x-goog-api-key": self.api_key})

    # -- embeddings ------------------------------------------------------------
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{API_ROOT}/models/{self.embed_model}:batchEmbedContents"
        payload = {
            "requests": [
                {"model": f"models/{self.embed_model}",
                 "content": {"parts": [{"text": t[:8000]}]}}
                for t in texts
            ]
        }
        r = self._client.post(url, json=payload)
        r.raise_for_status()
        return [e["values"] for e in r.json()["embeddings"]]

    # -- completion ------------------------------------------------------------
    def complete(self, prompt: str, n: int = 1, temperature: float = 0.7) -> tuple[list[str], Usage]:
        """Sample n independent completions. Used for self-consistency."""
        url = f"{API_ROOT}/models/{self.judge_model}:generateContent"
        outs, usage = [], Usage()
        for _ in range(n):
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": 512},
            }
            r = self._client.post(url, json=body)
            r.raise_for_status()
            data = r.json()
            outs.append(_first_text(data))
            usage.add(_usage_from(data))
        return outs, usage

    # -- judge -----------------------------------------------------------------
    def judge(self, question: str, answer: str, sources: list[str]) -> JudgeVerdict:
        if not sources:
            return JudgeVerdict(
                supported=False, confidence=0.0, unverifiable=True,
                rationale="No sources retrieved; support cannot be established.",
            )
        src = "\n\n".join(f"[S{i+1}] {s[:2000]}" for i, s in enumerate(sources))
        prompt = (
            f"{JUDGE_SYSTEM}\n\nQUESTION:\n{question}\n\nANSWER:\n{answer}\n\nSOURCES:\n{src}\n\nJSON:"
        )
        url = f"{API_ROOT}/models/{self.judge_model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 256,
                                 "responseMimeType": "application/json"},
        }
        r = self._client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
        usage = _usage_from(data)
        parsed = _parse_json(_first_text(data))
        if parsed is None:
            return JudgeVerdict(False, 0.0, "Judge returned unparseable output; failing closed.",
                                unverifiable=True, usage=usage)
        return JudgeVerdict(
            supported=bool(parsed.get("supported", False)),
            confidence=float(parsed.get("confidence", 0.0)),
            rationale=str(parsed.get("rationale", ""))[:300],
            unverifiable=bool(parsed.get("unverifiable", False)),
            usage=usage,
        )


def _first_text(data: dict) -> str:
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return ""


def _usage_from(data: dict) -> Usage:
    m = data.get("usageMetadata", {}) or {}
    pin = int(m.get("promptTokenCount", 0))
    pout = int(m.get("candidatesTokenCount", 0))
    return Usage(
        calls=1, prompt_tokens=pin, output_tokens=pout,
        cost_usd=(pin / 1e6) * PRICE_IN_PER_M + (pout / 1e6) * PRICE_OUT_PER_M,
    )


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None
