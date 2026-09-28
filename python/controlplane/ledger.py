"""Append-only evidence ledger.

Two failure modes this file exists to prevent:

1. **Interleaved appends.** The request path and the deferred workers are
   different threads, and the server and any eval harness are different
   processes. Both write here. A threading lock cannot coordinate processes, so
   appends take an in-process lock *and* a cross-process file lock, and the
   chain head is re-read from disk inside both.
2. **A silent write failure.** The caller gets the entry back, or an exception.
   It never gets a normal-looking receipt for something that was not persisted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


class LedgerCorrupt(RuntimeError):
    """The existing chain cannot be read. Appending would compound it."""


def _pid_alive(pid: int) -> bool:
    """Is this process still running?

    NOT `os.kill(pid, 0)`. On Windows, signal 0 is CTRL_C_EVENT, so that call
    does not probe a process — it sends Ctrl+C to its console group, which on the
    demo laptop means the liveness check can stop the server it is checking.
    Windows gets OpenProcess; POSIX gets signal 0, where it genuinely is a probe.
    """
    if pid <= 0 or pid > 2 ** 31 - 1:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False                      # gone, or not ours to inspect
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True                   # cannot tell: assume alive, wait
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (OverflowError, ValueError):
        # A PID the platform cannot even represent. A garbage lock file must
        # never be able to raise out of lock acquisition and wedge the ledger.
        return False
    except PermissionError:
        return True                           # alive, owned by another user
    except OSError:
        return True                           # cannot tell: assume alive, wait


class _FileLock:
    """Atomic on POSIX and Windows via O_CREAT|O_EXCL. Breaks a stale lock so a
    killed process cannot wedge the ledger forever."""

    def __init__(self, target: Path, timeout: float = 15.0) -> None:
        self.path = str(target) + ".lock"
        self.timeout = timeout
        self.fd: int | None = None

    def __enter__(self) -> "_FileLock":
        start = time.time()
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"{os.getpid()}:{time.time()}".encode())
                return self
            except FileExistsError:
                # Only break a lock whose OWNER is gone. Breaking a live writer's
                # lock on a timeout recreates the corruption the lock prevents.
                if time.time() - start > self.timeout:
                    if self._owner_is_dead():
                        try:
                            os.unlink(self.path)
                        except OSError:
                            pass
                    start = time.time()
                time.sleep(0.005)

    def _owner_is_dead(self) -> bool:
        try:
            pid_s, _ = open(self.path, encoding="utf-8").read().split(":", 1)
            pid = int(pid_s)
        except Exception:                                            # noqa: BLE001
            return True                       # unreadable owner: treat as stale
        if pid == os.getpid():
            return True
        return not _pid_alive(pid)

    def __exit__(self, *exc: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
        try:
            os.unlink(self.path)
        except OSError:
            pass


class JsonlLedger:
    def __init__(self, path: str | Path, signing_key: str = "development-only") -> None:
        self.path = Path(path)
        self.signing_key = signing_key.encode()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- core ---
    @staticmethod
    def _digest(previous_hash: str, body: dict[str, Any]) -> str:
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False)
        return hashlib.sha256((previous_hash + canonical).encode("utf-8")).hexdigest()

    #: lines the last `read()` could not parse. Never silently zero.
    unreadable: int = 0
    #: tail entries whose signature did not match this key — most often a
    #: rotation, never silently ignored.
    signature_warnings: int = 0
    #: tail entries whose own content hash did not re-derive. Surfaced by
    #: /health; `LEDGER_STRICT_APPEND=1` turns this into a refusal.
    chain_warnings: int = 0

    def _sign(self, digest: str) -> str:
        return hmac.new(self.signing_key, digest.encode(), hashlib.sha256).hexdigest()

    def _tail(self) -> tuple[int, str]:
        """Count and chain head in one pass, read from disk inside the lock."""
        if not self.path.exists():
            return 0, GENESIS
        count, head = 0, GENESIS
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                count += 1
                try:
                    last = json.loads(line)
                    head = last["hash"]
                except Exception as exc:                             # noqa: BLE001
                    # Appending after a corrupt line compounds the corruption.
                    raise LedgerCorrupt(
                        f"ledger line {count - 1} is unreadable; refusing to append"
                    ) from exc
        # Parseable is not the same as intact. Re-derive the last entry's own
        # hash before chaining onto it: a line that was edited in place stays
        # perfectly valid JSON, and chaining onto it would bury the tampering
        # under every entry written afterwards.
        #
        # What we do about a mismatch is a deliberate choice, and it is the
        # opposite of the obvious one. **We record it and keep writing.**
        # Refusing to append would mean a governance system that stops recording
        # evidence the moment anything looks wrong — destroying exactly the
        # trail an investigator needs, and handing anyone who can touch one byte
        # of the file a way to silence the log entirely. The discontinuity is
        # counted here, surfaced by `verify()`, and reported by /health as
        # `degraded`; `LEDGER_STRICT_APPEND=1` switches to refusing for
        # deployments that would rather stop than continue.
        #
        # A signature mismatch is softer still: it usually means the entry was
        # signed with a key that has since been rotated, and refusing there
        # would make rotating a key brick the log permanently.
        if count:
            body = {"index": last.get("index"),
                    "previousHash": last.get("previousHash"),
                    "record": last.get("record")}
            expected = self._digest(last.get("previousHash", GENESIS), body)
            if last.get("hash") != expected:
                self.chain_warnings += 1
                if os.getenv("LEDGER_STRICT_APPEND") == "1":
                    raise LedgerCorrupt(
                        f"ledger entry {last.get('index')} does not match its own "
                        f"content hash; refusing to append on a tampered tail")
            elif last.get("signature") != self._sign(expected):
                self.signature_warnings += 1
        return count, head

    def append(self, record: Any) -> dict[str, Any]:
        with self._lock, _FileLock(self.path):
            index, previous = self._tail()
            # Freeze the record before hashing it.
            #
            # This line is the whole reason the chain verifies, and it was found
            # the hard way: a fresh ledger written by this build failed its own
            # verification at a random index every few dozen entries, reason
            # "content hash mismatch". Nothing was tampering with the file. The
            # digest was computed over the live decision record, and deferred
            # verification — running on a background pool — amends that same
            # record when a slow detector lands. If an amendment arrived in the
            # microseconds between hashing the object and serialising it, the
            # bytes on disk were not the bytes that had been hashed, and the
            # entry was born broken.
            #
            # A JSON round-trip through `loads(dumps(...))` gives us an immutable
            # snapshot of plain JSON types, so what is hashed and what is written
            # are the same thing by construction rather than by timing. `default`
            # keeps an unexpected object from taking the ledger down: a receipt
            # that records something odd is worth far more than no receipt.
            frozen = json.loads(json.dumps(record, sort_keys=True,
                                           ensure_ascii=False, default=str))
            body = {"index": index, "previousHash": previous, "record": frozen}
            digest = self._digest(previous, body)
            entry = {**body,
                     "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                     "hash": digest, "signature": self._sign(digest)}
            line = json.dumps(entry, sort_keys=True, ensure_ascii=False)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return entry

    # ----------------------------------------------------------------- read ---
    def read(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        self.unreadable = 0
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        # Counted, never silently dropped. Recovery rebuilds
                        # state from this list, so a line it could not read is a
                        # hole in what the system is about to claim it knows.
                        self.unreadable += 1
                        continue
        if limit is None:
            return rows
        return rows[-limit:] if limit > 0 else []

    def verify(self) -> dict[str, Any]:
        """Recompute the whole chain. Reports the first index at which it stops
        verifying — tamper-evident under protected key management, which is a
        weaker and more accurate claim than tamper-proof."""
        previous = GENESIS
        count = 0
        if not self.path.exists():
            return {"valid": True, "entries": 0}
        with self.path.open(encoding="utf-8") as stream:
            for raw in stream:
                if not raw.strip():
                    continue
                count += 1
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    return {"valid": False, "entries": count, "brokenAt": count - 1,
                            "reason": "line is not valid JSON"}
                body = {"index": entry.get("index"), "previousHash": entry.get("previousHash"),
                        "record": entry.get("record")}
                digest = self._digest(previous, body)
                if entry.get("previousHash") != previous:
                    return {"valid": False, "entries": count, "brokenAt": entry.get("index"),
                            "reason": "chain linkage mismatch"}
                if entry.get("hash") != digest:
                    return {"valid": False, "entries": count, "brokenAt": entry.get("index"),
                            "reason": "content hash mismatch"}
                if entry.get("signature") != self._sign(digest):
                    return {"valid": False, "entries": count, "brokenAt": entry.get("index"),
                            "reason": "signature mismatch"}
                previous = entry["hash"]
        return {"valid": True, "entries": count}
