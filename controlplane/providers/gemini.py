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

import hashlib
import json
import os
import random
import re
import threading
import time

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


class RateLimiter:
    """Token bucket sized for the free tier.

    The published free-tier limit is small - single-digit requests per minute
    and a low daily cap - and a governance layer that DDoSes its own model
    provider is a poor advertisement for itself. Calls block briefly rather than
    failing, and the limiter reports how much headroom is left.
    """

    def __init__(self, rpm: int = 4, rpd: int = 18):
        self.rpm, self.rpd = rpm, rpd
        self._minute: list[float] = []
        self._day: list[float] = []
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        while True:
            with self._lock:
                now = time.time()
                self._minute = [t for t in self._minute if now - t < 60]
                self._day = [t for t in self._day if now - t < 86400]
                if len(self._day) >= self.rpd:
                    raise RuntimeError(
                        f"daily request budget exhausted ({self.rpd}/day, matching the "
                        f"free tier). Resets 24h after the earliest call. The offline "
                        f"provider still works: set CONTROLPLANE_PROVIDER=offline.")
                if len(self._minute) < self.rpm:
                    self._minute.append(now)
                    self._day.append(now)
                    return
                wait = 60 - (now - self._minute[0]) + 0.2
            if time.time() + wait > deadline:
                raise RuntimeError("rate limit wait exceeded the request timeout")
            time.sleep(min(wait, 5))

    def stats(self) -> dict:
        with self._lock:
            now = time.time()
            m = len([t for t in self._minute if now - t < 60])
            d = len([t for t in self._day if now - t < 86400])
        return {"per_minute_used": m, "per_minute_limit": self.rpm,
                "per_day_used": d, "per_day_limit": self.rpd,
                "day_remaining": max(0, self.rpd - d)}


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
        self.limiter = RateLimiter(
            rpm=int(os.environ.get("GEMINI_RPM", "4")),
            rpd=int(os.environ.get("GEMINI_RPD", "18")),
        )
        self._completions: dict[str, str] = {}   # prompt hash -> text
        self._clock = threading.Lock()

    def _post(self, url: str, body: dict, attempts: int = 3) -> dict:
        """One rate-limited call, retrying a 429 with exponential backoff."""
        last: Exception | None = None
        for i in range(attempts):
            self.limiter.acquire()
            try:
                r = self._client.post(url, json=body)
                if r.status_code == 429:
                    wait = (2 ** i) + random.random()
                    last = httpx.HTTPStatusError(
                        f"429 rate limited by the provider; retried after {wait:.1f}s",
                        request=r.request, response=r)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as exc:
                last = exc
                if exc.response is not None and exc.response.status_code < 500:
                    raise
                time.sleep((2 ** i) + random.random())
        raise last or RuntimeError("request failed")

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
        data = self._post(url, payload)
        return [e["values"] for e in data["embeddings"]]

    # -- completion ------------------------------------------------------------
    def complete(self, prompt: str, n: int = 1, temperature: float = 0.7) -> tuple[list[str], Usage]:
        """Sample n independent completions. Used for self-consistency."""
        url = f"{API_ROOT}/models/{self.judge_model}:generateContent"
        outs, usage = [], Usage()
        for i in range(n):
            # Deterministic requests are cached. Re-asking a demo question should
            # not spend quota twice.
            key = hashlib.sha1(f"{prompt}|{temperature}|{i}".encode()).hexdigest()
            if temperature == 0.0 and key in self._completions:
                outs.append(self._completions[key])
                continue
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": 512},
            }
            data = self._post(url, body)
            text = _first_text(data)
            outs.append(text)
            usage.add(_usage_from(data))
            if temperature == 0.0:
                self._completions[key] = text
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
        data = self._post(url, body)
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
