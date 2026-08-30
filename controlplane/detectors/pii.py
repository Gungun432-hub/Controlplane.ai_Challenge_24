"""Personal data egress detection.

Deterministic and cheap by design. Every finding here has a known repair, which
is why PII almost always routes to REPAIR rather than BLOCK: the user is never
made to wait for a human to remove a card number that we can remove ourselves.

Validators (Luhn for card numbers, Verhoeff for Aadhaar) are used so that a
random 16-digit order reference is not mistaken for a payment card. Precision
matters more than recall here - a false PII alarm on every invoice number is
exactly the alert fatigue the brief warns about.
"""
from __future__ import annotations

import re
import time

from .base import PRIVACY, Signal

CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
PHONE_IN = re.compile(r"\b(?:\+91[- ]?)?[6-9]\d{9}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")

_VERHOEFF_D = [
    [0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
    [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
    [9,8,7,6,5,4,3,2,1,0]]
_VERHOEFF_P = [
    [0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
    [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
    [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _verhoeff(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def _mask(s: str, keep: int = 4) -> str:
    body = re.sub(r"\D", "", s)
    return ("*" * max(0, len(body) - keep)) + body[-keep:] if body else "***"


def scan(text: str) -> list[dict]:
    found: list[dict] = []
    for m in CARD.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append({"type": "payment_card", "raw": m.group(), "masked": _mask(m.group()),
                          "severity": 1.0, "validator": "luhn"})
    for m in AADHAAR.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) == 12 and _verhoeff(digits):
            found.append({"type": "aadhaar", "raw": m.group(), "masked": _mask(m.group()),
                          "severity": 1.0, "validator": "verhoeff"})
    for rx, kind, sev in ((PAN, "pan", 0.8), (EMAIL, "email", 0.4),
                          (PHONE_IN, "phone", 0.5), (IBAN, "iban", 0.9)):
        for m in rx.finditer(text or ""):
            found.append({"type": kind, "raw": m.group(), "masked": _mask(m.group()),
                          "severity": sev, "validator": "pattern"})
    # de-duplicate on the raw span
    seen, out = set(), []
    for f in found:
        if f["raw"] not in seen:
            seen.add(f["raw"])
            out.append(f)
    return out


def redact(text: str, findings: list[dict]) -> str:
    out = text
    for f in sorted(findings, key=lambda x: -len(x["raw"])):
        out = out.replace(f["raw"], f"[{f['type'].upper()} REDACTED]")
    return out


def detect(provider, answer: str, **_) -> Signal:
    t0 = time.perf_counter()
    findings = scan(answer)
    if not findings:
        return Signal("pii", 0.0, 0.95, detail={"findings": 0},
                      latency_ms=(time.perf_counter() - t0) * 1000)
    score = min(1.0, max(f["severity"] for f in findings) * (1 + 0.1 * (len(findings) - 1)))
    return Signal(
        "pii", score=float(score), confidence=0.95, labels=[PRIVACY],
        evidence=[f"{f['type']} detected ({f['validator']}): {f['masked']}" for f in findings[:5]],
        detail={"findings": len(findings), "types": sorted({f["type"] for f in findings}),
                "repairable": True},
        latency_ms=(time.perf_counter() - t0) * 1000,
    )
