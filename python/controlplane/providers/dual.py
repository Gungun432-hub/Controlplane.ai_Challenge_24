"""Live where it earns its keep, deterministic everywhere else.

A real model is the honest answer to "is the AI real?" — and it is also a cost
per call, a rate limit, and a thing that can fail in front of a jury. Running
every seeded turn and every ambient tick through it would mean paying for 110
calls on each reset and putting a network dependency underneath the dashboards.

So: the question a person actually types goes to the live model. Everything
else — seeded history, ambient traffic, the scenario bench — runs on the
deterministic provider. Governance is identical either way, which is the point:
the gate does not care where the proposal came from.

If the live call fails, this falls back rather than failing the turn, and says
which provider answered so the receipt never overstates what happened.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from .base import AgentProposal
from .offline import OfflineProvider


class DualProvider:
    """Live for interactive work, offline for everything else."""

    name = "dual"

    def __init__(self, live: Any = None, offline: Any = None) -> None:
        self._offline = offline or OfflineProvider()
        self._live = live
        self._lock = threading.Lock()
        self.live_calls = 0
        self.fallbacks = 0
        self.last_error = ""
        # Thread-local, because "is this turn interactive?" is a property of the
        # request, and a module-level flag would leak across concurrent requests.
        self._local = threading.local()

    # ------------------------------------------------------------- routing ---
    def interactive(self, on: bool = True) -> "_Scope":
        return _Scope(self, on)

    @property
    def _is_interactive(self) -> bool:
        return bool(getattr(self._local, "interactive", False))

    def _resolve_live(self) -> Any:
        if self._live is None:
            from .gemini import GeminiProvider
            self._live = GeminiProvider()
        return self._live

    @property
    def live(self) -> bool:
        """Reported on /health. True when a live model is configured at all."""
        return bool(os.getenv("GEMINI_API_KEY"))

    # -------------------------------------------------------------- propose ---
    def propose(self, message: str, **kwargs: Any) -> AgentProposal:
        if self._is_interactive and self.live:
            try:
                proposal = self._resolve_live().propose(message, **kwargs)
                with self._lock:
                    self.live_calls += 1
                return proposal
            except Exception as exc:                                 # noqa: BLE001
                # Never fail a person's question because a provider blinked —
                # but never pass the backup off as the model's answer either.
                #
                # This was a real and serious defect. A rate-limited Gemini call
                # fell through to the deterministic provider, whose canned text
                # ("Standard guidance applies and is reviewed quarterly") was
                # then shown to the person in the AI's own bubble, scored, and
                # priced. Nothing on the screen said the AI had not answered.
                # Somebody reasonably concluded the model was broken; what was
                # actually broken was our honesty about which provider spoke.
                code = getattr(exc, "code", "") or type(exc).__name__
                detail = f"{code}: {exc}"[:160]
                with self._lock:
                    self.fallbacks += 1
                    self.last_error = detail
                proposal = self._offline.propose(message, **kwargs)
                proposal.fell_back_from = "gemini"
                proposal.fallback_code = str(code)
                proposal.fallback_detail = detail
                return proposal
        return self._offline.propose(message, **kwargs)

    @property
    def judge_model(self) -> str:
        if self._is_interactive and self.live:
            try:
                return self._resolve_live().judge_model
            except Exception:                                        # noqa: BLE001
                pass
        return self._offline.judge_model

    @property
    def judge_key_is_separate(self) -> bool:
        """Whether the adjudicator holds its own credential. Reported by /health,
        because "oversight cost us this much" is only a measurement if the two
        applications can be metered apart."""
        if self.live:
            try:
                return bool(self._resolve_live().judge_key_is_separate)
            except Exception:                                        # noqa: BLE001
                return False
        return False

    def adjudicate(self, system: str, prompt: str,
                   timeout_s: float = 6.0) -> tuple[str, dict[str, Any]]:
        """The second opinion follows the same rule as the first: live for a
        question a person typed, deterministic otherwise."""
        if self._is_interactive and self.live:
            try:
                out = self._resolve_live().adjudicate(system, prompt,
                                                      timeout_s=timeout_s)
                with self._lock:
                    self.live_calls += 1
                return out
            except Exception as exc:                                 # noqa: BLE001
                with self._lock:
                    self.fallbacks += 1
                    self.last_error = f"judge: {type(exc).__name__}: {exc}"[:160]
        return self._offline.adjudicate(system, prompt, timeout_s=timeout_s)

    def decide_probe(self, text: str) -> str:
        # Counterfactual probes must be deterministic or fairness stops being
        # reproducible, so these never go to the live model.
        return self._offline.decide_probe(text)

    def stats(self) -> dict[str, Any]:
        return {"liveConfigured": self.live, "liveCalls": self.live_calls,
                "fallbacks": self.fallbacks, "lastError": self.last_error}


class _Scope:
    def __init__(self, provider: DualProvider, on: bool) -> None:
        self.provider, self.on, self.previous = provider, on, False

    def __enter__(self) -> DualProvider:
        self.previous = getattr(self.provider._local, "interactive", False)
        self.provider._local.interactive = self.on
        return self.provider

    def __exit__(self, *exc: Any) -> None:
        self.provider._local.interactive = self.previous
