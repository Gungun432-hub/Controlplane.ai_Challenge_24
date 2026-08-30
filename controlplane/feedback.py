"""Feedback loop and threshold calibration.

The brief asks how flagged or overridden cases feed back to improve detection.
Two mechanisms, both deliberately simple enough to be auditable:

1. Override capture. A reviewer confirms or rejects an escalation. Every
   override is written to the trust ledger with the reviewer id, so the record
   of who overrode what survives independently of this process.

2. Threshold calibration. Overrides move a per-profile offset applied on top of
   the policy thresholds. Confirmed escalations (we were right) pull thresholds
   down; rejected escalations (false alarm) push them up. The offset is bounded
   and is *not* silent - it is reported through the API and shown on the
   dashboard, because a governance layer that retunes itself invisibly is worse
   than one that does not retune at all.

This is intentionally not online gradient training. With the volume a reviewer
queue realistically produces, a bounded bias term you can explain to an auditor
beats a model nobody can account for.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .config import DATA_DIR

MAX_OFFSET = 12.0
STEP = 1.5


class Calibrator:
    def __init__(self, path: Path | None = None):
        self.path = path or (DATA_DIR / "calibration.json")
        self._lock = threading.Lock()
        self.offsets: dict[str, float] = {}
        self.counts: dict[str, dict[str, int]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                doc = json.loads(self.path.read_text())
                self.offsets = doc.get("offsets", {})
                self.counts = doc.get("counts", {})
            except json.JSONDecodeError:
                pass

    def _save(self) -> None:
        self.path.write_text(json.dumps({"offsets": self.offsets, "counts": self.counts}, indent=2))

    def offset_for(self, profile_id: str) -> float:
        return float(self.offsets.get(profile_id, 0.0))

    def record(self, profile_id: str, verdict: str) -> dict:
        """verdict: 'confirmed' (the flag was right) or 'false_alarm'."""
        with self._lock:
            cur = self.offsets.get(profile_id, 0.0)
            c = self.counts.setdefault(profile_id, {"confirmed": 0, "false_alarm": 0})
            if verdict == "false_alarm":
                cur = min(MAX_OFFSET, cur + STEP)     # be less trigger-happy
                c["false_alarm"] += 1
            elif verdict == "confirmed":
                cur = max(-MAX_OFFSET, cur - STEP)    # catch more next time
                c["confirmed"] += 1
            self.offsets[profile_id] = cur
            self._save()
            return {"profile": profile_id, "offset": cur, "counts": dict(c)}

    def snapshot(self) -> dict:
        return {"offsets": dict(self.offsets), "counts": {k: dict(v) for k, v in self.counts.items()},
                "max_offset": MAX_OFFSET, "step": STEP}

    def reset(self) -> None:
        with self._lock:
            self.offsets, self.counts = {}, {}
            if self.path.exists():
                self.path.unlink()


CALIBRATOR = Calibrator()
