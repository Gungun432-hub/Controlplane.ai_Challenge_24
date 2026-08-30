"""Multi-turn and agentic risk accumulation.

A single turn can look harmless while a conversation as a whole drifts somewhere
it should not go, and an agent that takes actions compounds this: one shaky
intermediate answer can shape several downstream steps.

So a session carries state. Each turn contributes its risk to a decaying
accumulator, and the accumulated value raises the floor of P(failure) for later
turns in the same session. The effect is that the third borderline answer in a
row is treated more seriously than the first.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Session:
    session_id: str
    prompts: list[str] = field(default_factory=list)
    turns: int = 0
    accumulated: float = 0.0        # 0..1
    actions_taken: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def observe(self, prompt: str, price: int, action_class: str, decay: float = 0.75) -> None:
        self.turns += 1
        if prompt:
            self.prompts.append(prompt)
            if len(self.prompts) > 20:
                self.prompts.pop(0)
        # Decaying noisy-OR: old risk fades, repeated risk compounds.
        contribution = min(1.0, price / 100.0)
        self.accumulated = 1.0 - (1.0 - self.accumulated * decay) * (1.0 - contribution * 0.6)
        if action_class in ("decide", "execute"):
            self.actions_taken.append(action_class)
        self.last_seen = time.time()

    def as_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "turns": self.turns,
            "accumulated_risk": round(self.accumulated, 4),
            "consequential_actions": len(self.actions_taken),
            "age_s": round(time.time() - self.started, 1),
        }


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = defaultdict(lambda: Session(""))

    def get(self, session_id: str) -> Session:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                s = Session(session_id)
                self._sessions[session_id] = s
            return s

    def all(self) -> list[dict]:
        with self._lock:
            return [s.as_dict() for s in self._sessions.values()]

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()


SESSIONS = SessionStore()
