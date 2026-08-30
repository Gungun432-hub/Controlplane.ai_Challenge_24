"""Trust ledger: an append-only, hash-chained, HMAC-signed decision record.

Deliberately modest claims. This is a tamper-evident log, not a blockchain and
not tamper-proof: anyone holding the signing key can rewrite history. What it
does give you is detection - altering or removing any entry breaks the chain and
`verify()` reports the first index where it broke.

Each entry is designed to be the evidence a regulator or an internal auditor
asks for: what was asked, what the model said, what we measured, what we decided,
which policy version decided it, and who overrode it if anyone did.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from .config import DATA_DIR, SETTINGS

GENESIS = "0" * 64


class TrustLedger:
    def __init__(self, path: Path | None = None, signing_key: str | None = None):
        self.path = path or (DATA_DIR / "ledger.jsonl")
        self.key = (signing_key or SETTINGS.ledger_key).encode()
        self._lock = threading.Lock()
        self._last_hash = self._recover_tail()

    def _recover_tail(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = GENESIS
        with self.path.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)["entry_hash"]
                    except (json.JSONDecodeError, KeyError):
                        continue
        return last

    @staticmethod
    def _canonical(payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            entry = {
                "index": self._count(),
                "ts": time.time(),
                "prev_hash": self._last_hash,
                "record": record,
            }
            body = self._canonical(entry)
            entry_hash = hashlib.sha256((self._last_hash + body).encode()).hexdigest()
            signature = hmac.new(self.key, entry_hash.encode(), hashlib.sha256).hexdigest()
            entry["entry_hash"] = entry_hash
            entry["signature"] = signature
            with self.path.open("a") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
            self._last_hash = entry_hash
            return entry

    def _count(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open() as fh:
            return sum(1 for line in fh if line.strip())

    def read(self, limit: int = 100) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]
        return rows[-limit:]

    def iter_all(self) -> Iterator[dict]:
        if not self.path.exists():
            return iter(())
        return (json.loads(l) for l in self.path.read_text().splitlines() if l.strip())

    def verify(self) -> dict[str, Any]:
        """Recompute the chain. Returns the first index that fails, if any."""
        prev = GENESIS
        checked = 0
        for entry in self.iter_all():
            checked += 1
            body = self._canonical({k: entry[k] for k in ("index", "ts", "prev_hash", "record")})
            expect = hashlib.sha256((prev + body).encode()).hexdigest()
            if expect != entry.get("entry_hash"):
                return {"valid": False, "entries": checked, "broken_at": entry.get("index"),
                        "reason": "hash chain mismatch"}
            sig = hmac.new(self.key, expect.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, entry.get("signature", "")):
                return {"valid": False, "entries": checked, "broken_at": entry.get("index"),
                        "reason": "signature mismatch"}
            if entry.get("prev_hash") != prev:
                return {"valid": False, "entries": checked, "broken_at": entry.get("index"),
                        "reason": "prev_hash mismatch"}
            prev = entry["entry_hash"]
        return {"valid": True, "entries": checked, "head": prev}


LEDGER = TrustLedger()
