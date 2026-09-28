"""Live provider.

The agent runs on a real model. What the model returns is a *proposal*, parsed
under a strict schema, on a deadline. It cannot decide a route, and a malformed
or late response is recorded as a governance event rather than coerced into an
allow.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from .base import AgentProposal, ProposalError, SYSTEM_PROMPT, parse_proposal


class ProviderError(RuntimeError):
    """A classified provider failure.

    The code is stable and safe to persist. The provider's own response body is
    deliberately not carried into it — a governance receipt should not become a
    place where upstream infrastructure detail leaks.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

_ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
             "{model}:generateContent")

#: Four attempts with exponential backoff: 0.8s, 1.6s, 3.2s. Overridable,
#: because a conference network and a jury clock want different numbers.
RETRIES = int(os.getenv("CONTROLPLANE_AGENT_RETRIES", "4"))
RETRY_BACKOFF_S = float(os.getenv("CONTROLPLANE_AGENT_BACKOFF_S", "0.8"))


class GeminiProvider:
    name = "gemini"
    live = True

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 probe_model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        # The judge may hold its own credential. Two applications are calling the
        # provider now — the assistant that writes the answer and the adjudicator
        # that marks it — and metering them on one key means the bill and the
        # quota cannot tell them apart. That matters for a product whose pitch is
        # that oversight has a price you can see: "governance cost us ₹X this
        # month" is a claim, and a separate key is what makes it a measurement.
        # It also means a judge that runs out of quota cannot take the assistant
        # down with it. Optional by design — unset, the judge shares the main key
        # and nothing changes.
        self.judge_api_key = (os.getenv("GEMINI_JUDGE_API_KEY", "").strip()
                              or self.api_key)
        self.model = model or os.getenv("CONTROLPLANE_AGENT_MODEL", "gemini-3.1-flash-lite")
        self.probe_model = probe_model or self.model
        if not self.api_key:
            raise ProviderError("provider_not_configured", "GEMINI_API_KEY is not set")
        self.calls = 0

    # ------------------------------------------------------------------ raw ---
    def _generate(self, prompt: str, *, system: str | None, deadline_s: float,
                  temperature: float, max_tokens: int,
                  model: str | None = None,
                  api_key: str | None = None) -> tuple[str, dict[str, int]]:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature,
                                 "maxOutputTokens": max_tokens,
                                 "responseMimeType": "application/json"},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            import httpx
        except ModuleNotFoundError as exc:                           # noqa: BLE001
            raise ProviderError("provider_not_configured",
                                "the live provider needs httpx: pip install httpx") from exc

        url = _ENDPOINT.format(model=model or self.model)
        # Transient upstream failures (429/503) are retried briefly. Anything
        # else is surfaced as a stable code — the raw provider body never reaches
        # a governance record.
        last: Exception | None = None
        for attempt in range(RETRIES):
            try:
                with httpx.Client(timeout=deadline_s) as client:
                    response = client.post(url, params={"key": api_key or self.api_key},
                                           json=body)
            except httpx.TimeoutException as exc:
                raise ProviderError("provider_timeout", "the model did not respond in time"
                                    ) from exc
            except httpx.HTTPError as exc:
                last = exc
                time.sleep(0.4 * (attempt + 1))
                continue
            self.calls += 1
            if response.status_code in (429, 500, 502, 503) and attempt < RETRIES - 1:
                # A free-tier key rate-limits readily, and a jury asking three
                # questions in quick succession is exactly the pattern that
                # trips it. Backing off and trying again is much cheaper than
                # falling through to the deterministic provider — the whole
                # point of this build is that the AI answers.
                time.sleep(RETRY_BACKOFF_S * (2 ** attempt))
                continue
            if response.status_code == 429:
                raise ProviderError("provider_rate_limited", "the model is rate limited")
            if response.status_code == 503:
                raise ProviderError("provider_unavailable", "the model is temporarily "
                                                            "overloaded")
            if response.status_code in (401, 403):
                raise ProviderError("provider_unauthorised", "the model rejected our "
                                                             "credentials")
            if response.status_code >= 400:
                raise ProviderError("provider_http_error",
                                    f"the model returned HTTP {response.status_code}")
            break
        else:
            raise ProviderError("provider_unavailable", "the model could not be reached"
                                ) from last
        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            raise ProviderError("provider_schema_error",
                                "the model returned no candidate response")
        parts = candidates[0].get("content", {}).get("parts") or [{}]
        text = "".join(part.get("text", "") for part in parts)
        meta = payload.get("usageMetadata", {}) or {}
        usage = {"promptTokens": int(meta.get("promptTokenCount", 0)),
                 "outputTokens": int(meta.get("candidatesTokenCount", 0)), "calls": 1}
        return text, usage

    # ------------------------------------------------------------- proposal ---
    def propose(self, message: str, *, tools: list[dict[str, Any]], context: list[str],
                deadline_s: float = 6.0) -> AgentProposal:
        # The catalogue used to list only ids and capabilities, and that set the
        # model up to fail. Asked *"what score does a candidate need to reach
        # interview?"* — a pure rubric lookup — it picked `recruiting`, because
        # "candidate" was in that tool's keywords, and `recruiting` is
        # decide-capable and irreversible. The gate then correctly refused a
        # decision tool for a reading question, and a perfectly ordinary
        # question came back blocked.
        #
        # The model could not have known. Nothing in what we sent it said that
        # one tool reads and the other one decides. So now the catalogue says
        # exactly that, in the order of consequence, and the rules below tell it
        # to reach for the weakest tool that does the job.
        weight = {"read": 1, "draft": 2, "advise": 3, "decide": 4, "execute": 5}
        listed = sorted(tools, key=lambda t: weight.get(t.get("effectiveAction"), 9))
        catalogue = "\n".join(
            f"- {t['id']}: {t.get('name', t['id'])} "
            f"— this tool {t.get('effectiveAction', 'read').upper()}S"
            f"{'' if t.get('reversible', True) else ' and CANNOT BE UNDONE'}"
            f"{' and needs human approval' if t.get('approvalRequired') else ''}"
            f" (capabilities: {', '.join(t.get('capabilities', [])) or 'none'})"
            for t in listed) or "- none"
        ctx = "\n".join(f"[{c['id']}] {c['text']}" for c in context[:8]) or "[no context]"
        prompt = (f"Tools available to you:\n{catalogue}\n\n"
                  f"Context you may cite BY ID (cite the bracketed id, never the "
                  f"text):\n{ctx}\n\n"
                  f"User request:\n{message}\n\nReturn the JSON proposal now.")
        started = time.perf_counter()
        text, usage = self._generate(prompt, system=SYSTEM_PROMPT, deadline_s=deadline_s,
                                     temperature=0.2, max_tokens=700)
        elapsed = (time.perf_counter() - started) * 1000
        proposal = parse_proposal(text, [t["id"] for t in tools])   # raises ProposalError
        proposal.provider = self.name
        proposal.usage = usage
        proposal.latency_ms = elapsed
        return proposal

    # ---------------------------------------------------------------- probe ---
    @property
    def judge_model(self) -> str:
        import os as _os
        return _os.getenv("CONTROLPLANE_JUDGE_MODEL", self.model)

    @property
    def judge_key_is_separate(self) -> bool:
        """Reported by /health so nobody has to take the separation on trust."""
        return bool(self.judge_api_key) and self.judge_api_key != self.api_key

    def adjudicate(self, system: str, prompt: str,
                   timeout_s: float = 6.0) -> tuple[str, dict[str, Any]]:
        """The second opinion. Temperature zero, JSON out, its own short budget.

        A separate model id is allowed so the judge can be a different — and
        deliberately not the same — model from the one that wrote the answer.
        Asking a model to mark its own homework is not a second opinion."""
        import os as _os
        model = _os.getenv("CONTROLPLANE_JUDGE_MODEL", self.model)
        out, usage = self._generate(prompt, system=system, deadline_s=timeout_s,
                                    temperature=0.0, max_tokens=700, model=model,
                                    api_key=self.judge_api_key)
        return out, usage

    def decide_probe(self, text: str) -> str:
        """Temperature 0, one word out. Used only for counterfactual comparison —
        the comparison itself is deterministic."""
        prompt = ("Decide this case. Reply with exactly one word, either "
                  f"approve or reject, and nothing else.\n\n{text}")
        try:
            out, _ = self._generate(prompt, system=None, deadline_s=4.0,
                                    temperature=0.0, max_tokens=8)
        except ProviderError:
            raise
        except Exception as exc:                                    # noqa: BLE001
            raise ProviderError("provider_probe_failed", "the counterfactual probe "
                                                         "could not be completed") from exc
        word = "".join(ch for ch in out.lower() if ch.isalpha())
        return "approve" if "approve" in word else "reject" if "reject" in word else "unknown"
