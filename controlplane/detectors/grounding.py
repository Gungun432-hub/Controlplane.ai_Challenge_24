"""Grounding: does each claim in the answer trace back to retrieved source text?

This detector is the system's answer to the hardest constraint in the brief:
there is often no reliable real-time ground truth to check a claim against.

So we do not check truth. We check *support*. A claim that no source covers is
marked UNVERIFIABLE, which is a distinct outcome from "false" and is routed
differently. Claiming to detect falsehood without ground truth would be exactly
the kind of overconfidence this system exists to catch.
"""
from __future__ import annotations

import re
import time

import numpy as np

from ..providers.base import Usage
from .base import HALLUCINATION, PRIVACY, UNVERIFIABLE, Signal

# A claim is supported if its best match against any source chunk clears this.
SUPPORT_TAU = 0.55

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
# Rough person-name heuristic: two capitalised words not at sentence start, or a
# title followed by a capitalised word. Enough to flag the overlap case.
_PERSON = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Shri|Smt)\.?\s+[A-Z][a-z]+|\b[A-Z][a-z]+\s[A-Z][a-z]+\b")
_NUMERIC = re.compile(r"\d+(?:[.,]\d+)?")

# Sentences that assert nothing checkable: refusals, meta-statements about the
# assistant itself, and pure pleasantries. Scoring these as "unsupported" is the
# single largest source of false positives, because a correct refusal is exactly
# the behaviour we want and would otherwise be punished for it.
_META = re.compile(
    r"^\s*(?:i\s+(?:cannot|can't|won't|am\s+unable|do\s+not|don't|'m\s+not)"
    r"|as\s+an\s+ai|i'm\s+sorry|sorry,|please\s+(?:contact|consult|speak)"
    r"|note\s+that|let\s+me\s+know|happy\s+to\s+help|thank\s+you)",
    re.I)


def _is_checkable(sentence: str) -> bool:
    """A sentence is checkable if it asserts something about the world."""
    if _META.search(sentence):
        return False
    # A sentence with no content words beyond stopwords carries no claim.
    words = re.findall(r"[A-Za-z]{4,}", sentence)
    return len(words) >= 3


def _sentences(text: str, checkable_only: bool = False) -> list[str]:
    out = [s.strip() for s in _SENT.split(text or "") if len(s.strip()) > 12]
    if checkable_only:
        out = [s for s in out if _is_checkable(s)]
    return out


def _numbers(text: str) -> set[str]:
    """Normalised numeric tokens. 8.4 and 8.40 are the same number; 60 and 90 are not."""
    out = set()
    for raw in _NUMERIC.findall(text or ""):
        try:
            out.add(f"{float(raw.replace(',', '')):g}")
        except ValueError:
            continue
    return out


def _chunks(sources: list[str]) -> list[str]:
    out: list[str] = []
    for s in sources:
        parts = _sentences(s) or ([s.strip()] if s.strip() else [])
        out.extend(parts)
    return out


_STOP = {"the","a","an","is","are","was","were","be","been","to","of","for","on","in","and",
         "or","it","its","this","that","with","at","by","as","from","your","you","we","our",
         "has","have","had","will","would","can","may","not","no","but","if","so","than","then"}


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _STOP and len(w) > 2}


def _containment(claim: str, chunk: str) -> float:
    """Fraction of the claim's content words that appear in the chunk.

    A sparse lexical term alongside the dense one. Paraphrase defeats bag-of-words
    and re-framing defeats a weak encoder, so we take the better of the two rather
    than betting the system on either. This is the same hybrid dense+sparse
    argument that retrieval systems settled on years ago.
    """
    cw = _content_words(claim)
    if not cw:
        return 0.0
    return len(cw & _content_words(chunk)) / len(cw)


def _cos(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    an = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    bn = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    return an @ bn.T


def detect(provider, answer: str, sources: list[str], prompt: str = "",
           source_grades: list[str] | None = None, **_) -> Signal:
    t0 = time.perf_counter()
    claims = _sentences(answer, checkable_only=True)
    usage = Usage()

    if not claims:
        return Signal("grounding", 0.0, 0.4, detail={"reason": "no checkable claims"},
                      latency_ms=(time.perf_counter() - t0) * 1000)

    src = _chunks(sources)
    if not src:
        # Nothing to check against. This is unverifiable, not wrong.
        return Signal(
            "grounding", score=0.62, confidence=0.35, labels=[UNVERIFIABLE],
            evidence=["No source material was retrieved for this response."],
            detail={"grounded_fraction": None, "claims": len(claims), "sources": 0,
                    "reason": "no_sources_retrieved"},
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    labels: list[str] = []
    evidence: list[str] = []
    evidence_numeric: list[str] = []

    # Cheap first. Lexical containment costs microseconds and needs no model
    # call, so compute it for every claim before spending anything. Only claims
    # it cannot already clear go to the embedder.
    #
    # This is the system's own thesis applied to its own internals: the
    # expensive check runs on the fraction of work that actually needs it. On
    # ordinary grounded traffic it removes the model call entirely.
    lex = np.array([[_containment(c, chunk) for chunk in src] for c in claims])
    lex_best = lex.max(axis=1)
    needs_embedding = [i for i, v in enumerate(lex_best) if v < SUPPORT_TAU]

    hybrid = lex.copy()
    embedded = 0
    if needs_embedding:
        subset = [claims[i] for i in needs_embedding]
        vecs = provider.embed(subset + src)
        cv = np.array(vecs[: len(subset)], dtype=float)
        sv = np.array(vecs[len(subset):], dtype=float)
        sim = _cos(cv, sv)
        for row, i in enumerate(needs_embedding):
            hybrid[i] = np.maximum(hybrid[i], sim[row])
        embedded = len(subset)

    best = hybrid.max(axis=1)

    supported = best >= SUPPORT_TAU

    # Numeric consistency check. Embedding similarity is dominated by prose, so
    # "notice period is 60 days" and "notice period is 90 days" look almost
    # identical to any encoder. Numbers are also the part of an answer people
    # actually act on, so a numeric token that appears in no source overrides the
    # similarity verdict outright.
    # Provenance for a number is the retrieved sources OR the user's own prompt.
    # A figure the user supplied ("is a 150,000 claim payable?") is legitimately
    # absent from the source documents and must not read as a fabrication.
    source_numbers: set[str] = set()
    for chunk in src:
        source_numbers |= _numbers(chunk)
    source_numbers |= _numbers(prompt)
    numeric_conflicts: list[int] = []
    for i, claim in enumerate(claims):
        claim_numbers = _numbers(claim)
        if claim_numbers and not claim_numbers.issubset(source_numbers):
            unmatched = sorted(claim_numbers - source_numbers)
            numeric_conflicts.append(i)
            supported[i] = False
            if len(evidence_numeric) < 4:
                evidence_numeric.append(
                    f"numeric claim {unmatched} appears in no retrieved source: "
                    f"\"{claim[:140]}\""
                )

    grounded_fraction = float(supported.mean())

    unsupported_idx = [i for i, ok in enumerate(supported) if not ok]

    if unsupported_idx:
        labels.append(HALLUCINATION)
        for i in unsupported_idx[:4]:
            evidence.append(f"unsupported (best match {best[i]:.2f}): \"{claims[i][:160]}\"")

    # Overlap case: an unsupported claim that names a person is simultaneously a
    # fabrication and a personal-data problem. One finding, two labels.
    person_claims = [i for i in unsupported_idx if _PERSON.search(claims[i])]
    if person_claims:
        labels.append(PRIVACY)
        evidence.append(
            "fabricated detail attached to a named individual - counts as both "
            "hallucination and personal-data exposure"
        )

    # Unsupported numeric claims are weighted harder: numbers get acted on.
    score = 1.0 - grounded_fraction
    if numeric_conflicts:
        score = min(1.0, score + 0.20 * len(numeric_conflicts))
    evidence = evidence_numeric + evidence

    # Source governance. The brief assumes a mix of well-governed and loosely
    # governed internal sources feeding these systems. A claim supported only by
    # an unowned wiki page is supported more weakly than one traced to an owned,
    # versioned document, so the grade lowers our confidence in the verdict and
    # raises the residual risk rather than being decorative metadata.
    grades = source_grades or []
    loose = sum(1 for g in grades if g != "governed")
    loose_share = (loose / len(grades)) if grades else 0.0
    confidence = 0.8 if len(src) >= 3 else 0.6
    confidence *= (1.0 - 0.35 * loose_share)
    if loose_share:
        score = min(1.0, score + 0.18 * loose_share)
        evidence.append(
            f"{loose} of {len(grades)} supporting sources are loosely governed "
            f"(unowned or unreviewed), so support is weaker than it looks")

    return Signal(
        "grounding",
        score=float(score),
        confidence=float(confidence),
        labels=labels,
        evidence=evidence,
        detail={
            "grounded_fraction": round(grounded_fraction, 3),
            "claims": len(claims),
            "unsupported": len(unsupported_idx),
            "numeric_conflicts": len(numeric_conflicts),
            "contradiction": bool(numeric_conflicts),
            "sources": len(src),
            "loosely_governed_sources": loose,
            "source_grades": grades,
            "support_tau": SUPPORT_TAU,
            "method": "lexical-first hybrid: containment, then dense cosine only where needed",
            "claims_embedded": embedded,
            "claims_resolved_lexically": len(claims) - embedded,
        },
        latency_ms=(time.perf_counter() - t0) * 1000,
        usage=usage,
    )
