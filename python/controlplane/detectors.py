"""Deterministic detectors.

Each detector reads real text and returns real evidence. No detector calls a
language model to decide anything; the fairness probe uses the provider only to
generate counterfactual variants, and the comparison itself is deterministic.

Every result carries a STATUS as well as a score, because a check that did not
run is not the same thing as a check that found nothing.
"""
from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal[
    "completed", "timed_out", "failed", "not_configured",
    "skipped_by_policy", "queued_async", "completed_async", "stale",
]

HALLUCINATION = "hallucination"
PRIVACY = "privacy"
BIAS = "bias"
WASTE = "waste"
UNVERIFIABLE = "unverifiable"

#: Does this answer contain anything a person could be wrong about? A number, a
#: date, money, a duration, a policy word, or a commitment. If none of these
#: appear, the answer is conversational and there is nothing to ground.
_CHECKABLE = re.compile(
    r"\d"                                             # any figure at all
    r"|\b(?:policy|policies|rule|rules|limit|limits|threshold|approval|"
    r"approved|eligible|entitled|required|requires|must|cannot|guarantee|"
    r"guaranteed|refund|charge|fee|deadline|window|days?|weeks?|months?|"
    r"hours?|minutes?|percent|rupees?|inr|usd|will\s+be|you\s+can|"
    r"you\s+should|we\s+will|allowed|prohibited|covered)\b", re.I)


@dataclass
class DetectorResult:
    detector_id: str
    score: float | None = None
    confidence: float | None = None
    status: Status = "completed"
    execution_mode: str = "inline"
    latency_ms: float = 0.0
    queue_delay_ms: float = 0.0
    labels: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    requirement: str = "advisory"          # advisory | mandatory

    @property
    def ran(self) -> bool:
        return self.status in ("completed", "completed_async")

    def as_dict(self) -> dict[str, Any]:
        return {
            "detectorId": self.detector_id, "score": self.score,
            "confidence": self.confidence, "status": self.status,
            "executionMode": self.execution_mode,
            "latencyMs": round(self.latency_ms, 2),
            "queueDelayMs": round(self.queue_delay_ms, 2),
            "labels": self.labels, "evidence": self.evidence[:4],
            "detail": self.detail, "errorCode": self.error_code,
            "requirement": self.requirement,
        }


# ---------------------------------------------------------------- helpers ---
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and", "or",
    "in", "on", "for", "with", "that", "this", "it", "as", "at", "by", "from",
    "will", "can", "may", "your", "you", "we", "our", "i", "am", "please", "all",
}
_NUM = re.compile(r"(?<![\w.])(?:₹|rs\.?\s*)?\d[\d,]*(?:\.\d+)?%?", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9%.₹]+", (text or "").lower()) if w not in _STOP and len(w) > 1}


def _norm_num(raw: str) -> str:
    return re.sub(r"[₹,\s]|rs\.?", "", raw.lower())


# ------------------------------------------------------------- grounding ---
SUPPORT_TAU = 0.55


def _shape(raw: str) -> str:
    """percent / money / plain. Two figures can only contradict within a shape:
    "8.4%" and "5,000 rupees" are not rival answers to the same question."""
    low = raw.lower()
    if low.endswith("%") or "percent" in low:
        return "percent"
    if low.startswith("\u20b9") or low.startswith("rs"):
        return "money"
    return "plain"


def _numeric_verdict(answer: str, sources: list[str], prompt: str
                     ) -> tuple[list[str], list[str], list[str]]:
    """(contradicted, unsourced, echoed_from_prompt)

    The distinction this function exists for: **a figure the sources do not
    mention is not a figure the sources deny.** Reporting silence as a
    contradiction is how a checker earns a reputation for crying wolf, and it is
    also simply untrue — "the 30-day window" being absent from a refund SOP means
    nobody has confirmed it, not that the SOP says otherwise.

    A figure is only *contradicted* when a source sentence that is plainly about
    the same thing carries a different figure of the same shape. Everything else
    that is missing is recorded as unsourced, which routes as unverifiable rather
    than as a hallucination."""
    src_raw = _NUM.findall(" ".join(sources))
    src_nums = {_norm_num(m) for m in src_raw}
    ask_nums = {_norm_num(m) for m in _NUM.findall(prompt)}

    src_sentences = [x.strip() for src in sources for x in _SENT.split(src)
                     if len(x.strip()) > 12]

    contradicted, unsourced = [], []
    for sentence in _SENT.split(answer):
        sentence = sentence.strip()
        if not sentence:
            continue
        s_terms = _words(sentence)
        for raw in _NUM.findall(sentence):
            value = _norm_num(raw)
            if not value or value in src_nums or value.endswith("."):
                continue
            if value in ask_nums:
                # The person asking supplied this figure. Whatever else is true
                # of it, the model did not invent it — so it can never be a
                # fabrication, only an unconfirmed echo. Checked before the
                # rival search, because a nearby source figure would otherwise
                # make the user's own number look like a lie the model told.
                continue
            shape = _shape(raw)
            rival = ""
            for candidate in src_sentences:
                c_terms = _words(candidate)
                # How much overlap proves two sentences are about the same thing
                # depends on how much there is to overlap. A terse policy line
                # ("The fund targets 8.4% annualised returns.") shares only its
                # subject with a terse claim, and demanding two terms there
                # missed real contradictions.
                need = 2 if min(len(s_terms), len(c_terms)) > 6 else 1
                if len(s_terms & c_terms) < need:
                    continue                      # not about the same thing
                for other in _NUM.findall(candidate):
                    if _shape(other) == shape and _norm_num(other) != value:
                        rival = f"{value} (the source says {_norm_num(other)})"
                        break
                if rival:
                    break
            if rival:
                contradicted.append(rival)
            else:
                unsourced.append(value)

    echoed = sorted({_norm_num(m) for m in _NUM.findall(answer)}
                    & ask_nums - src_nums)
    return (sorted(set(contradicted)), sorted(set(unsourced)), echoed)


def grounding(answer: str, sources: list[str], prompt: str = "",
              retrieved: list[str] | None = None, **_: Any) -> DetectorResult:
    """Verify SUPPORT, not truth.

    Three outcomes per claim, never two: supported by a source, contradicted by
    one, or **not settled either way**. Collapsing the third into the second is
    the single most common way a grounding check becomes untrustworthy.

    A sentence in which the assistant declines, defers to a person or describes
    its own limits is not a claim about the world at all and is excluded before
    any of this begins — see `abstain.py`. Measuring "I cannot advise on that"
    against a policy corpus and reporting it as unsupported made correct
    behaviour look like a failure, which is worse than missing a real one.
    """
    if not (answer or "").strip():
        return DetectorResult("grounding", status="skipped_by_policy",
                              detail={"reason": "no answer text"})

    from .abstain import split as _split
    declined, asserted = _split(answer)

    if declined and not asserted:
        # Nothing was asserted, so there is nothing to ground. This is a clean
        # result, not an absent one.
        return DetectorResult(
            "grounding", score=0.0, confidence=0.85,
            evidence=["the assistant declined and asserted nothing about the world, "
                      "so there is no claim here to support or contradict"],
            requirement="mandatory",
            detail={"groundedFraction": 1.0, "claims": 0, "claimsSupported": 0,
                    "sources": len(sources or []), "abstention": True,
                    "declinedSentences": len(declined),
                    "numericContradictions": [], "unsourcedFigures": [],
                    "figuresEchoedFromPrompt": [], "contradiction": False})

    # A greeting, an acknowledgement, an offer of help: sentences that assert
    # nothing about the world. There is no claim here to be right or wrong
    # about, and scoring it 0.62 "unverifiable" put *"Hello! How can I help you
    # today?"* under a banner reading "check one thing before you act on it".
    # That is alert fatigue manufactured by our own checker, and alert fatigue
    # is how a control plane gets ignored.
    #
    # Deliberately narrow: no sentence carrying a figure, a date, a policy word
    # or a commitment qualifies, so it cannot become a way to smuggle a claim
    # past grounding.
    if asserted and not _CHECKABLE.search(answer or ""):
        return DetectorResult(
            "grounding", score=0.0, confidence=0.75,
            evidence=["nothing in this answer is a claim about the world — there "
                      "are no figures, dates, policies or commitments in it to "
                      "check against anything"],
            requirement="mandatory",
            detail={"groundedFraction": 1.0, "claims": 0, "claimsSupported": 0,
                    "sources": len(sources or []), "abstention": False,
                    "nothingAsserted": True,
                    "numericContradictions": [], "unsourcedFigures": [],
                    "figuresEchoedFromPrompt": [], "contradiction": False})

    if not sources:
        # Two different situations, and calling both of them "nothing was
        # retrieved" was simply untrue whenever retrieval had in fact returned
        # six chunks and the agent cited none of them. The second case is worse
        # than the first — the evidence was there and went unused — so it must
        # not be described in weaker words.
        found = len(retrieved or [])
        note = ("nothing was retrieved for this question, so there is no source "
                "material to check the answer against"
                if not found else
                f"{found} source(s) were retrieved for this question and the "
                f"answer cites none of them, so none of it can be checked")
        return DetectorResult("grounding", score=0.62, confidence=0.6,
                              labels=[UNVERIFIABLE],
                              evidence=[note],
                              detail={"groundedFraction": 0.0, "sources": 0,
                                      "sourcesRetrieved": len(retrieved or []),
                                      "citedNothingDespiteRetrieval":
                                          bool(retrieved) and not sources,
                                      "claims": len(asserted), "claimsSupported": 0,
                                      "contradiction": False},
                              requirement="mandatory")

    # The prompt is NOT evidence. Including the user's own words in the support
    # pool meant a claim could look supported because the person asking supplied
    # the vocabulary — which is precisely how a governance check gets laundered.
    # Support is measured against the server-resolved corpus and nothing else.
    pool = _words(" ".join(sources))
    asked = _words(prompt)
    claims = asserted or [answer.strip()]
    supported, loose = 0, []
    for claim in claims:
        cw = _words(claim)
        if not cw:
            supported += 1
            continue
        containment = len(cw & pool) / len(cw)
        if containment >= SUPPORT_TAU:
            supported += 1
        else:
            loose.append(claim[:110])

    fraction = supported / len(claims)
    score = round(1.0 - fraction, 4)

    contradictions, unsourced, echoed = _numeric_verdict(
        " ".join(asserted) or answer, sources, prompt)
    if contradictions:
        score = min(1.0, score + 0.20 * len(contradictions))
    if unsourced:
        # Priced, but well below a contradiction: an unconfirmed figure is a gap
        # in our evidence, not a false statement by the model.
        score = min(1.0, score + 0.08 * len(unsourced))
    if echoed:
        score = min(1.0, score + 0.05 * len(echoed))

    labels: list[str] = []
    if contradictions:
        labels.append(HALLUCINATION)
    if (loose or echoed or unsourced) and not contradictions:
        labels.append(UNVERIFIABLE)

    ev = [f"{supported} of {len(claims)} claim(s) supported by {len(sources)} source(s)"]
    if declined:
        ev.append(f"{len(declined)} sentence(s) where the assistant declined were not "
                  f"measured, because a refusal asserts nothing about the world")
    ev += [f"not supported by any source: \"{c}\"" for c in loose[:2]]
    ev += [f"contradicts the source of record: {c}" for c in contradictions[:2]]
    ev += [f"figure appears in no source, and no source denies it either: {c}"
           for c in unsourced[:2]]
    ev += [f"figure repeated from the question, confirmed by no source: {c}"
           for c in echoed[:2]]

    return DetectorResult(
        "grounding", score=round(min(1.0, score), 4),
        confidence=0.8 if len(sources) >= 3 else 0.6,
        labels=labels, evidence=ev, requirement="mandatory",
        detail={"groundedFraction": round(fraction, 3), "claims": len(claims),
                "claimsSupported": supported,
                "declinedSentences": len(declined),
                "sources": len(sources), "numericContradictions": contradictions,
                "unsourcedFigures": unsourced,
                "figuresEchoedFromPrompt": echoed,
                "questionTerms": len(asked),
                # Only a genuine rival figure sets the contradiction floor.
                "contradiction": bool(contradictions)},
    )


# --------------------------------------------------------------- privacy ---
def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_VD = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
       [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
       [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
       [9,8,7,6,5,4,3,2,1,0]]
_VP = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
       [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
       [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
_VINV = [0,4,3,2,1,5,6,7,8,9]


def _verhoeff(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VD[c][_VP[i % 8][ord(ch) - 48]]
    return c == 0


_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
_DIGITS = re.compile(r"(?<!\d)(?:\d[ -]?){11,19}\d(?!\d)")


def redact(text: str) -> str:
    """Mask validated-looking identifiers, deterministically.

    One routine, used by the repair route *and* by anything that writes text to
    the ledger. Two implementations of "make this safe to keep" would drift, and
    the one that drifted would be the one writing to the append-only log nobody
    can go back and fix."""
    out = _DIGITS.sub(lambda m: "\u2022" * 12 + m.group()[-4:], text or "")
    out = _EMAIL.sub("[redacted-email]", out)
    return _PHONE.sub("[redacted-phone]", out)


def privacy(answer: str, prompt: str = "", **_: Any) -> DetectorResult:
    """Checksum validators, so a string that merely looks like an identifier
    does not raise a finding."""
    text = f"{answer or ''}\n{prompt or ''}"
    findings: list[dict[str, Any]] = []

    for m in _DIGITS.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) == 12 and _verhoeff(digits):
            findings.append({"kind": "aadhaar", "severity": 1.0, "validator": "verhoeff",
                             "masked": f"XXXX-XXXX-{digits[-4:]}"})
        elif 13 <= len(digits) <= 19 and _luhn(digits):
            findings.append({"kind": "payment_card", "severity": 1.0, "validator": "luhn",
                             "masked": f"****-****-****-{digits[-4:]}"})

    for m in _EMAIL.finditer(text):
        findings.append({"kind": "email", "severity": 0.5, "validator": "pattern",
                         "masked": m.group()[0] + "***@" + m.group().split("@")[1]})
    for m in _PHONE.finditer(text):
        findings.append({"kind": "phone", "severity": 0.6, "validator": "pattern",
                         "masked": "*******" + m.group()[-3:]})

    if not findings:
        return DetectorResult("privacy", score=0.0, confidence=0.95,
                              evidence=["no validated identifiers present"],
                              requirement="mandatory", detail={"findings": 0})

    peak = max(f["severity"] for f in findings)
    score = min(1.0, peak * (1 + 0.1 * (len(findings) - 1)))
    return DetectorResult(
        "privacy", score=round(score, 4), confidence=0.95, labels=[PRIVACY],
        evidence=[f"{f['kind']} confirmed by {f['validator']}: {f['masked']}" for f in findings[:3]],
        requirement="mandatory",
        detail={"findings": len(findings), "kinds": sorted({f["kind"] for f in findings}),
                "redactable": True},
    )


# -------------------------------------------------------------- fairness ---
def _word_present(word: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text, re.I) is not None


def _swap_word(text: str, a: str, b: str) -> str:
    """Replace whole words only, so the counterfactual differs from the original
    in exactly the protected attribute and nothing else."""
    return re.sub(rf"\b{re.escape(a)}\b", b, text, flags=re.I)


_SWAPS = [
    ("given_name", ("Rajesh", "Fatima")),
    ("gender_term", ("he", "she")),
    ("locality", ("Bandra", "Dharavi")),
    ("pincode", ("400050", "400017")),
]


def fairness(answer: str, prompt: str = "", provider: Any = None, max_probes: int = 3,
             **_: Any) -> DetectorResult:
    """Counterfactual probe, not a content filter.

    Change only a protected attribute, hold everything else constant, and see
    whether the decision flips. A content filter cannot catch the failure that
    matters here, where every word is polite and the outcome is still different.
    """
    base = f"{prompt or ''} {answer or ''}"
    # Whole words only. A substring test matched "he" inside "the", so this
    # detector fired on almost every English sentence — and then substituted
    # inside the word, turning "The guide" into "Tshe guide" and probing a
    # sentence nobody wrote. Both the trigger and the swap need boundaries.
    applicable = [(name, pair) for name, pair in _SWAPS
                  if _word_present(pair[0], base) or _word_present(pair[1], base)]
    if not applicable:
        return DetectorResult("fairness", status="skipped_by_policy",
                              detail={"reason": "no protected attribute present in this request"})
    if provider is None:
        return DetectorResult("fairness", status="not_configured",
                              detail={"reason": "no provider available for counterfactual probes"})

    probes = applicable[:max_probes]
    flips, tested, inconclusive, ev = 0, 0, 0, []
    for name, (a, b) in probes:
        try:
            va = provider.decide_probe(_swap_word(base, a, b))
            vb = provider.decide_probe(_swap_word(base, b, a))
        except Exception as exc:                                   # noqa: BLE001
            return DetectorResult("fairness", status="failed",
                                  error_code=type(exc).__name__,
                                  detail={"message": str(exc)[:160]})
        # A probe the model declined to answer is not evidence of bias. Counting
        # "approve" against "unknown" as a flip would manufacture a finding out
        # of a model that simply did not reply, and a bias detector that cries
        # wolf is a bias detector nobody acts on.
        if "unknown" in (va, vb):
            inconclusive += 1
            ev.append(f"swapping {name} ({a} ↔ {b}) was inconclusive: "
                      f"the model returned {va} / {vb}")
            continue
        tested += 1
        if va != vb:
            flips += 1
            ev.append(f"swapping {name} ({a} ↔ {b}) changed the outcome: {va} vs {vb}")

    if tested == 0:
        # Every applicable probe was inconclusive. Absence of a comparison is not
        # a clean result, so this is recorded as not having run.
        return DetectorResult(
            "fairness", status="failed", error_code="probes_inconclusive",
            requirement="advisory", evidence=ev,
            detail={"probes": 0, "inconclusive": inconclusive,
                    "attributes": [n for n, _ in probes],
                    "reason": "no counterfactual pair produced a comparable outcome"})

    rate = flips / tested
    return DetectorResult(
        "fairness", score=round(rate, 4),
        confidence=round(min(0.9, 0.4 + 0.2 * tested), 3),
        labels=[BIAS] if flips else [],
        evidence=ev or [f"{tested} counterfactual probe(s), no outcome change"],
        requirement="advisory",
        detail={"probes": tested, "flips": flips, "flipRate": round(rate, 3),
                "inconclusive": inconclusive,
                "attributes": [n for n, _ in probes]},
    )


# ------------------------------------------------------------------ cost ---
REWORK_TAU = 0.86


class CostWindow:
    """Rolling history per task class, so 'expensive' means expensive relative to
    this kind of work rather than to an arbitrary constant."""

    def __init__(self, keep: int = 200) -> None:
        self._tokens: dict[str, list[int]] = {}
        self._hashes: dict[str, list[str]] = {}
        self.keep = keep
        # Detectors run on two thread pools at once. Without this, a read could
        # sort a list another thread is truncating, and the median a receipt
        # cites would not be the median anything was compared against.
        self._lock = threading.Lock()

    def observe(self, task_class: str, tokens: int,
                prompt: str) -> tuple[float, float, dict[str, Any]]:
        digest = hashlib.sha256(" ".join(sorted(_words(prompt))).encode()).hexdigest()[:16]
        with self._lock:
            toks = self._tokens.setdefault(task_class, [])
            hashes = self._hashes.setdefault(task_class, [])
            ratio, median, n = 1.0, None, len(toks)
            if toks:
                ordered = sorted(toks)
                median = ordered[len(ordered) // 2] or 1
                ratio = tokens / median
            dup = hashes.count(digest) / len(hashes) if hashes else 0.0
            toks.append(tokens)
            hashes.append(digest)
            del toks[:-self.keep]
            del hashes[:-self.keep]
        # The window is stateful, so the receipt records the window the number was
        # derived from. Replay reads the recorded evidence rather than
        # recomputing against a window that has since moved on.
        return ratio, dup, {"windowSize": n, "median": median, "keep": self.keep}


COSTS = CostWindow()


def cost(answer: str, prompt: str = "", task_class: str = "generic", tokens: int | None = None,
         **_: Any) -> DetectorResult:
    est = tokens if tokens is not None else max(1, (len(prompt or "") + len(answer or "")) // 4)
    ratio, dup, window = COSTS.observe(task_class, est, prompt or "")
    overrun = max(0.0, (ratio - 1.5) / 3.0)
    score = min(1.0, overrun + (dup if dup >= 0.5 else 0.0) * 0.4)
    ev = ([f"{est} tokens, {ratio:.2f}x the median of the last {window['windowSize']} "
           f"in task class '{task_class}'"] if window["windowSize"] else
          [f"{est} tokens; no history yet for task class '{task_class}', so no comparison "
           f"is claimed"])
    if dup:
        ev.append(f"{dup*100:.0f}% of recent prompts in this class are near-duplicates")
    return DetectorResult(
        "cost", score=round(score, 4), confidence=0.7,
        labels=[WASTE] if score > 0.3 else [], evidence=ev, requirement="advisory",
        detail={"tokens": est, "medianRatio": round(ratio, 3),
                "duplicateShare": round(dup, 3), "reworkTau": REWORK_TAU,
                "window": window},
    )


def _purpose(**kwargs: Any) -> DetectorResult:
    """Imported lazily: purpose.py imports DetectorResult from this module, and a
    top-level import here would close the circle."""
    from .purpose import purpose as _impl
    return _impl(**kwargs)


def _abstention(**kwargs: Any) -> DetectorResult:
    from .abstain import abstention as _impl
    return _impl(**kwargs)


def _certainty(**kwargs: Any) -> DetectorResult:
    from .certainty import certainty as _impl
    return _impl(**kwargs)


def _toxicity(**kwargs: Any) -> DetectorResult:
    from .harm import toxicity as _impl
    return _impl(**kwargs)


DETECTORS = {
    "grounding": grounding,
    # Declining is the system working. This records that, and prices the one
    # thing that is genuinely wrong: promising an ability the registry withholds.
    "abstention": _abstention,
    "privacy": privacy,
    "fairness": fairness,
    "cost": cost,
    # The car-wash class: every sentence true, the reader's purpose defeated.
    "purpose": _purpose,
    # The problem statement's own phrase: "right or confidently wrong". Nothing
    # else here measured how sure an answer sounds against what it stands on.
    "certainty": _certainty,
    # The other end of the harm gate. Screening the question and then releasing
    # an abusive answer would be governing one end of the call.
    "toxicity": _toxicity,
}
