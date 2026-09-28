"""Right, or **confidently wrong** — the problem statement's own words.

The brief asks us to monitor three things about an answer, and the third one is
written like this:

> *"...performance (right or **confidently wrong**)."*

Nothing else in this system measured the second half of that. Grounding asks
whether a claim is supported. The adjudicator asks whether the evidence carries
the answer. Neither of them asks the question a reader actually cares about:
**how sure does this thing sound, and has it earned that?**

Those come apart constantly, and the failure is asymmetric:

* *"Refunds are usually processed within a week, though it depends on your bank"*
  — hedged, and if it is wrong the reader has been warned. Cheap to be wrong.
* *"Your refund will definitely be in your account by Friday. There are no
  exceptions."* — same factual risk, and now the reader has cancelled the card,
  told their spouse, and stopped chasing it. Expensive to be wrong.

A control plane that prices both the same is not measuring the thing that hurts.

So this file measures one number and prices one gap:

1. **How certain does each sentence sound?** Absolutes (*always*, *never*,
   *guaranteed*, *no exceptions*, *100%*), flat futures (*will be*, *you are
   entitled to*), and bare imperatives all raise it. Hedges (*usually*, *may*,
   *typically*, *check with*, *I believe*, *approximately*) lower it — and that
   matters as much, because hedging correctly is the behaviour we want more of
   and it should show up as a *lower* price, not merely a neutral one.
2. **Is that sentence standing on anything?** A sentence is backed when some
   retrieved source sentence shares its distinctive words. Deliberately crude
   and deliberately generous: this is a calibration check, not a second
   grounding check, and it must not fire twice on the same defect.
3. **Price the gap.** Certain and unbacked is the expensive quadrant.
   `confidentlyWrong` in the detail is a fact about the text, so the gate can
   treat it as a floor rather than a probability — the same way it treats a
   numeric contradiction and an omitted condition.

What this is *not*: a truth check. It cannot tell you the answer is wrong. It
tells you the answer has bet more than its evidence covers, which is the part a
human reviewer can settle in fifteen seconds and a model cannot settle at all.

An honest decline is exempt. *"I don't have access to that"* is a maximally
certain sentence with nothing behind it, and it is exactly right.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import abstain
from .detectors import DetectorResult

MISCALIBRATED = "miscalibrated_certainty"
CONFIDENTLY_WRONG = "confidently_wrong"

# --------------------------------------------------------------- vocabulary ---
# Weighted, because "guaranteed" and "will" are not the same promise.
_ABSOLUTE = re.compile(
    r"\b(?:always|never|guarantee[ds]?|guaranteed|definitely|certainly|"
    r"absolutely|undoubtedly|without\s+(?:a\s+)?doubt|without\s+exception|"
    r"no\s+exceptions?|in\s+(?:all|every)\s+cases?|"
    r"100\s*%|completely\s+safe|entirely\s+safe|"
    r"there\s+is\s+no\s+(?:risk|chance|possibility)|"
    r"you\s+(?:are|will\s+be)\s+(?:fully\s+)?(?:entitled|covered|protected)|"
    r"is\s+not\s+possible|cannot\s+happen|impossible)\b", re.I)

_FLAT_FUTURE = re.compile(
    r"\b(?:will\s+be|will\s+have|will\s+receive|will\s+get|will\s+arrive|"
    r"will\s+not|won'?t|is\s+approved|are\s+approved|is\s+eligible|"
    r"are\s+eligible|qualifies|you\s+can\s+safely|you\s+should\s+proceed|"
    r"go\s+ahead|no\s+approval\s+(?:is\s+)?needed|"
    r"you\s+do\s+not\s+need\s+(?:any\s+)?approval)\b", re.I)

_HEDGE = re.compile(
    r"\b(?:usually|typically|generally|often|sometimes|may|might|could|"
    r"likely|unlikely|about|around|approximately|roughly|in\s+most\s+cases|"
    r"as\s+far\s+as|I\s+believe|I\s+think|it\s+appears|it\s+seems|"
    r"subject\s+to|depends\s+on|depending\s+on|check\s+with|confirm\s+with|"
    r"verify\s+with|please\s+confirm|in\s+principle|should\s+normally|"
    r"I\s+am\s+not\s+(?:certain|sure)|cannot\s+confirm|no\s+source|"
    r"unless|provided\s+that|if\s+in\s+doubt)\b", re.I)

# A number or a date is a specific commitment; an assertive sentence carrying one
# is a stronger bet than an assertive sentence of generalities.
_SPECIFIC = re.compile(
    r"\b(?:\d[\d,]*(?:\.\d+)?\s*%?|₹\s?[\d,]+|rs\.?\s?[\d,]+|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"today|tomorrow|tonight)\b", re.I)

_STOP = set("""
a an the and or but so if then than that this these those there here it its is
are was were be been being am do does did done have has had having will would
shall should can could may might must not no nor of to at in on for from by with
i me my we us our you your he him his she her they them their
""".split())
_WORD = re.compile(r"[a-z][a-z0-9'-]*")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")

# An answer can share every word with a document and assert its opposite. This
# is the shape that matters most in practice and the one our own demo turns on:
# the policy says a campaign of this size needs Legal's sign-off, and the answer
# says no approval is needed. Topically identical; factually reversed. A sentence
# that waives a requirement its sources impose is never treated as backed.
_WAIVES = re.compile(
    r"\b(?:no\s+(?:approval|sign-?off|authorisation|authorization|second\s+"
    r"approver|review)\s+(?:is\s+)?(?:needed|required)|"
    r"(?:do|does)\s+not\s+(?:need|require)\s+(?:any\s+)?(?:approval|sign-?off|"
    r"review)|not\s+(?:required|needed)|without\s+(?:approval|sign-?off|review)|"
    r"waive[drs]?|waiver|exempt\w*|no\s+(?:limit|cap|restriction|condition)s?|"
    r"free\s+to\s+(?:send|proceed|go)|"
    r"no\s+(?:risk|chance|possibility)\b)", re.I)

_IMPOSES = re.compile(
    r"\b(?:require[sd]?|requires?|must|mandatory|need[s]?\s+(?:approval|sign-?off|"
    r"a\s+second)|approver|sign-?off|only\s+(?:with|after)|"
    r"not\s+permitted|prohibited|subject\s+to\s+approval)\b", re.I)

BACKING_OVERLAP = 2      # distinctive words ONE source sentence must share
PREFIX_MATCH = 5
CERTAIN_FLOOR = 0.55     # at or above this, the sentence is making a promise


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower())
            if w not in _STOP and len(w) > 2}


def _related(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if long == short + "s":
        return True
    return len(short) >= PREFIX_MATCH and long.startswith(short)


def _overlap(sentence_terms: set[str], source_terms: set[str]) -> int:
    return sum(1 for t in sentence_terms
               if any(_related(t, s) for s in source_terms))


@dataclass
class Sentence:
    text: str
    certainty: float
    backed: bool
    markers: list[str] = field(default_factory=list)
    hedges: list[str] = field(default_factory=list)

    @property
    def overbought(self) -> bool:
        """Certain, and standing on nothing."""
        return self.certainty >= CERTAIN_FLOOR and not self.backed

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text[:160], "certainty": round(self.certainty, 3),
                "backed": self.backed, "markers": self.markers[:4],
                "hedges": self.hedges[:4]}


@dataclass
class CertaintyResult:
    sentences: list[Sentence] = field(default_factory=list)
    declined: bool = False
    sources_seen: int = 0

    @property
    def overbought(self) -> list[Sentence]:
        return [s for s in self.sentences if s.overbought]

    @property
    def stated_certainty(self) -> float:
        """How sure the answer sounds, taken as its most confident sentence.

        Not the average: one unhedged promise is what the reader remembers and
        acts on, and averaging it away with four careful sentences is exactly the
        measurement error that lets a confident wrong answer through."""
        return max((s.certainty for s in self.sentences), default=0.0)

    @property
    def confidently_wrong(self) -> bool:
        """The expensive quadrant: a flat promise with nothing behind it."""
        return any(s.overbought and s.markers for s in self.sentences)

    @property
    def miscalibration(self) -> float:
        if not self.sentences:
            return 0.0
        worst = max((s.certainty for s in self.overbought), default=0.0)
        share = len(self.overbought) / len(self.sentences)
        return round(min(1.0, worst * (0.6 + 0.4 * share)), 4)

    def as_dict(self) -> dict[str, Any]:
        return {"statedCertainty": round(self.stated_certainty, 3),
                "miscalibration": self.miscalibration,
                "confidentlyWrong": self.confidently_wrong,
                "sentencesChecked": len(self.sentences),
                "overbought": [s.as_dict() for s in self.overbought][:3],
                "answerDeclined": self.declined,
                "sourceSentences": self.sources_seen}


def _score_sentence(text: str) -> tuple[float, list[str], list[str]]:
    """How sure this one sentence sounds, and the words that make it so."""
    absolutes = [" ".join(m.group(0).split()) for m in _ABSOLUTE.finditer(text)]
    futures = [" ".join(m.group(0).split()) for m in _FLAT_FUTURE.finditer(text)]
    hedges = [" ".join(m.group(0).split()) for m in _HEDGE.finditer(text)]

    score = 0.0
    if absolutes:
        score += 0.62 + 0.08 * (len(absolutes) - 1)
    if futures:
        score += 0.40 + 0.08 * (len(futures) - 1)
    if absolutes or futures:
        if _SPECIFIC.search(text):
            # A named date or figure turns a confident sentence into a
            # commitment somebody can plan around: "your refund will arrive" is
            # a hope, "your refund will arrive Friday" is something the reader
            # reschedules their week around.
            score += 0.16
    # A hedge is a real retraction of certainty, and the first one does most of
    # the work: "usually" changes the reader's behaviour, "usually ... typically"
    # barely changes it again.
    if hedges:
        score -= 0.30 + 0.08 * min(len(hedges) - 1, 3)
    return max(0.0, min(1.0, score)), absolutes + futures, hedges


def inspect(answer: str, sources: list[str] | None = None) -> CertaintyResult:
    """Sentence by sentence: how sure it sounds, and whether it is standing on anything."""
    result = CertaintyResult()
    text = (answer or "").strip()
    if not text:
        return result

    if abstain.posture(text) == abstain.FULL:
        # An outright decline is a certain sentence with nothing behind it, and
        # it is the behaviour we want. Saying so costs nothing; pricing it would
        # teach the model to waffle instead of declining.
        result.declined = True
        return result

    pool = [s for s in (sources or []) if (s or "").strip()]
    # Per source sentence, never a pooled bag of words: a claim that borrows one
    # word from each of three unrelated documents has not been supported by any
    # of them.
    source_terms = [_terms(one) for one in pool]
    imposes = any(_IMPOSES.search(one) for one in pool)
    result.sources_seen = len(pool)

    declined_clauses, _ = abstain.split(text)
    declined = {" ".join(c.split()) for c in declined_clauses}

    for raw in _SENTENCE.split(text):
        sentence = " ".join(raw.split()).strip()
        if len(sentence) < 12:
            continue
        if sentence in declined or abstain.is_abstention(sentence):
            continue
        score, markers, hedges = _score_sentence(sentence)
        terms = _terms(sentence)
        backed = any(_overlap(terms, one) >= BACKING_OVERLAP for one in source_terms)
        if backed and imposes and _WAIVES.search(sentence):
            # Same subject, opposite conclusion.
            backed = False
        result.sentences.append(Sentence(sentence, score, backed, markers, hedges))

    return result


def describe(result: CertaintyResult) -> str:
    """One sentence a person reads without decoding anything."""
    worst = result.overbought
    if not worst:
        return ""
    target = max(worst, key=lambda s: s.certainty)
    word = (target.markers or ["a flat statement"])[0]
    if result.sources_seen:
        return (f"The answer says “{word}” as if it were settled, and nothing in "
                f"the {result.sources_seen} document(s) it was given backs that up.")
    return (f"The answer says “{word}” as if it were settled, and it was working "
            f"from no documents at all.")


# ------------------------------------------------------------- detector ---
def certainty(answer: str = "", sources: list[str] | None = None,
              retrieved: list[str] | None = None, **_: Any) -> DetectorResult:
    """Deterministic, inline, zero tokens.

    Measured against everything retrieval surfaced, not only what the answer
    chose to cite — an answer that ignores the document it was handed and then
    states its conclusion flatly is the case this exists for."""
    pool = list(retrieved or []) or list(sources or [])
    r = inspect(answer, pool)

    if r.declined:
        return DetectorResult(
            "certainty", score=0.0, confidence=0.6,
            evidence=["the answer declines rather than asserting, so there is no "
                      "certainty to be miscalibrated"],
            requirement="advisory",
            detail={**r.as_dict(), "confidentlyWrong": False})

    if not r.sentences:
        return DetectorResult(
            "certainty", score=0.0, confidence=0.35,
            evidence=["no assertive sentence long enough to judge"],
            requirement="advisory", detail={**r.as_dict(), "confidentlyWrong": False})

    score = r.miscalibration
    evidence: list[str] = []
    if r.overbought:
        worst = max(r.overbought, key=lambda s: s.certainty)
        evidence.append(describe(r))
        evidence.append(f"the sentence is: \"{worst.text[:170]}\"")
        if len(r.overbought) > 1:
            evidence.append(f"{len(r.overbought)} of {len(r.sentences)} sentences make "
                            f"a firm statement nothing retrieved supports")
    else:
        hedged = sum(1 for s in r.sentences if s.hedges)
        if r.stated_certainty < CERTAIN_FLOOR:
            evidence.append(
                f"nothing in the answer is stated more firmly than "
                f"{r.stated_certainty:.2f} on stated certainty, so there is no "
                f"over-claim to price"
                + (f" — and {hedged} sentence(s) hedge explicitly, which is the "
                   f"behaviour we want" if hedged else ""))
        else:
            evidence.append(
                f"the answer's firmest sentence scores {r.stated_certainty:.2f} on "
                f"stated certainty and every firm sentence is supported by something "
                f"retrieved"
                + (f"; {hedged} sentence(s) hedge as well" if hedged else ""))

    return DetectorResult(
        "certainty", score=round(score, 4),
        confidence=0.72 if r.overbought else 0.6,
        labels=([MISCALIBRATED] + ([CONFIDENTLY_WRONG] if r.confidently_wrong else []))
        if r.overbought else [],
        evidence=evidence, requirement="advisory",
        detail={**r.as_dict(),
                "measuredAgainst": ("everything retrieval surfaced" if retrieved
                                    else "the cited sources only"),
                "certainFloor": CERTAIN_FLOOR})
