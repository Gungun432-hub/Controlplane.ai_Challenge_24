"""The answers where every sentence is true and the person is still harmed.

This is the class of failure our mentor kept coming back to, and it is the one
almost nothing in this market looks for. Call it the car-wash problem: you ask
how to get the job done, you are told something entirely accurate, you act on
it, and the thing you were actually trying to achieve is defeated — because the
one line that governed you was left out.

It is worth being precise about why the other detectors cannot see it.

* **Grounding** asks *is this supported by the sources?* An answer that quotes
  two true sentences from the policy and omits the third scores clean. Grounding
  measures the presence of support, and omission is an absence.
* **Toxicity and bias** are about the character of the text. This text is
  polite, neutral and helpful.
* **The adjudicator** can see it — and is asked to, as its second charge — but a
  model call costs money and latency, so the cheap deterministic version should
  run first and on every turn.

Three concrete failures, all observed in our own corpus:

1. *Omitted blocking condition.* Marketing asks whether it may send a campaign to
   80,000 external contacts. The answer confirms the copy follows the tone guide.
   True. The campaign policy says an external send above 50,000 contacts needs
   the marketing director **plus legal sign-off**. The send goes out unapproved.
2. *Threshold crossed in silence.* The question contains a number, the governing
   document gates on that number, and the answer never mentions the gate. This
   one is nearly free to detect and almost never a false positive.
3. *Answered the adjacent question.* Somebody asks **how long**; the answer
   explains the process beautifully and contains no duration at all. Nothing in
   it is false. It is not an answer.

Everything here is deterministic, local, sub-millisecond and costs no tokens —
and it reports the exact sentence, from the organisation's own document, that the
answer walked past. On the receipt that is far more useful than a score, because
it is directly actionable by the team that owns the assistant.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .detectors import DetectorResult

from . import objective

PURPOSE_DEFEATED = "purpose_defeated"

# ---------------------------------------------------------------- terms ---
# A much smaller stop list than the scope index uses, on purpose: here the
# governance vocabulary IS the subject. "Do I need approval" is a question about
# approval, and dropping the word would throw away the only term that matters.
_FUNCTION = set("""
a an the and or of to in for on at is are was were be been being this that these
those with as by from it its you your we our i me my they their will shall would
should could do does did have has had not no but if then than so such when where
which who what how why any some more most other each both very just about into
""".split())

_WORD = re.compile(r"[a-z][a-z0-9\-]*")
_SENT = re.compile(r"(?<=[.!?])\s+|\n(?=[A-Z#])|\n\n")
_NUMBER = re.compile(r"(?<![\w.])(?:₹|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)\s*(%|percent|"
                     r"lakh|crore|thousand|k\b)?", re.I)

# Which side of a threshold a rule governs. A policy document is full of tiers —
# "up to 50,000: manager approval", "above 50,000: director plus legal sign-off"
# — and a question about 80,000 contacts is governed by exactly one of them.
# Without this, both tiers look relevant and the check reports the wrong line,
# which is worse than reporting nothing: it hands a developer a rule their case
# does not fall under and teaches them the finding is noise.
_ABOVE = re.compile(r"\b(above|over|exceeding|more\s+than|greater\s+than|beyond)\s+"
                    r"(?:₹|rs\.?\s*)?([\d,]+)", re.I)
_UP_TO = re.compile(r"\b(up\s+to|below|under|less\s+than|at\s+most|within)\s+"
                    r"(?:₹|rs\.?\s*)?([\d,]+)", re.I)


def _bands(sentence: str) -> tuple[list[float], list[float]]:
    """(lower bounds this rule governs above, upper bounds it governs below)."""
    def vals(pattern):
        out = []
        for _, raw in pattern.findall(sentence or ""):
            try:
                out.append(float(raw.replace(",", "")))
            except ValueError:
                continue
        return out
    return vals(_ABOVE), vals(_UP_TO)


def _stem(word: str) -> str:
    """Crude and deliberate. Matching "send" against "sends" matters far more
    here than linguistic correctness, and a real stemmer is a dependency."""
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def _content(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall((text or "").lower())
            if w not in _FUNCTION and len(w) > 2]


def _numbers(text: str) -> list[float]:
    out = []
    for raw, unit in _NUMBER.findall(text or ""):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        unit = (unit or "").lower()
        if unit in ("lakh",):
            value *= 100_000
        elif unit in ("crore",):
            value *= 10_000_000
        elif unit in ("thousand", "k"):
            value *= 1_000
        out.append(value)
    return out


# ---------------------------------------------------------------- gates ---
# What makes a sentence in a policy document *binding on the reader*. Each entry
# is (kind, pattern, how we say it to a human).
_GATES: list[tuple[str, re.Pattern[str], str]] = [
    ("approval", re.compile(
        r"\b(requires?|require|needs?|needing|subject\s+to)\b[^.;]{0,60}?"
        r"\b(approval|approver|approvers|sign-?off|authorisation|authorization|"
        r"consent|review)\b"
        # Policy documents are full of table lines that state a gate with a
        # colon and no verb at all: "External sends up to 50,000 contacts:
        # marketing manager approval." Missing those meant missing most of the
        # gates in a real policy file.
        r"|:\s*[^.;]{0,48}\b(approval|approver|approvers|sign-?off)\b", re.I),
     "it requires an approval"),
    ("approver", re.compile(
        r"\b(two|second|single|named|manager|director|legal)\b[^.;]{0,24}?"
        r"\b(approver|approvers|sign-?off|grade)\b", re.I),
     "it names who has to approve it"),
    ("prohibition", re.compile(
        r"\b(?:must|may|can|shall|should)\s+(?:not|never)\b|\bcannot\b|"
        r"\bnot\s+permitted\b|\bprohibited\b|\bnot\s+allowed\b|\bno\s+"
        r"(?:production|external|personal)\b", re.I),
     "it forbids something"),
    ("conditional", re.compile(
        r"\bonly\s+(?:if|when|from|between|with|after|by)\b|\bunless\b|"
        r"\bexcept\b|\bprovided\s+that\b|\bon\s+condition\b|\brequires\s+an?\s+"
        r"(?:incident|change|ticket)\b", re.I),
     "it applies only under a condition"),
    ("window", re.compile(
        r"\b(?:permitted|allowed|only|between)\b[^.;]{0,50}?"
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"\d{1,2}:\d{2})\b", re.I),
     "it is limited to a time window"),
    ("no_guarantee", re.compile(
        r"\bnot\s+(?:a\s+)?guarantee|\bno\s+guarantee|\bnot\s+assured\b|"
        r"\bnot\s+a\s+reliable\s+indicator\b|\bmay\s+fall\b|\bcapital\s+at\s+risk\b",
        re.I),
     "it says the outcome is not guaranteed"),
    ("threshold", re.compile(
        r"\b(?:above|over|exceeding|more\s+than|up\s+to|below|under)\s+"
        r"(?:₹|rs\.?\s*)?[\d,]+", re.I),
     "it gates on a threshold"),
    ("irreversible", re.compile(
        r"\birreversible\b|\bcannot\s+be\s+(?:recalled|undone|reversed|reverted)\b|"
        r"\bno\s+rollback\b|\bpermanent\b", re.I),
     "it warns the action cannot be undone"),
]

# Language that tells the reader to go ahead. Harmless on its own; damning when it
# sits next to an on-topic condition the answer never mentions.
_GO_AHEAD = re.compile(
    r"\byes\b|\byou\s+(?:can|may|are\s+able)\b|\bgo\s+ahead\b|\bsimply\b|"
    r"\bjust\s+\w+\b|\bno\s+approval\s+(?:is\s+)?(?:needed|required)\b|"
    r"\bhas\s+been\s+(?:issued|sent|approved|credited|restarted|dispatched)\b|"
    r"\b(?:restarting|sending|issuing|approving)\s+\w+\s+now\b|"
    r"\bthis\s+(?:has|is)\s+(?:now\s+)?(?:been\s+)?\w+ed\b", re.I)

# ---------------------------------------------------------------- focus ---
# What the person asked FOR, and what an answer to it has to contain. Keeping the
# two in one table is what stops the check drifting into a vibe.
_FOCUS: list[tuple[str, re.Pattern[str], re.Pattern[str], str]] = [
    ("duration",
     re.compile(r"\bhow\s+long\b|\bhow\s+many\s+(?:days|hours|weeks)\b|"
                r"\bwhen\s+will\b|\bhow\s+soon\b|\bturnaround\b|\blead\s+time\b|"
                r"\btime\s+(?:to|does\s+it\s+take)\b", re.I),
     re.compile(r"\b(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|"
                r"fourteen|thirty|couple|few|several)\s*(?:to\s*[\w]+\s*)?"
                r"(?:working\s+|business\s+|calendar\s+)?"
                r"(?:second|minute|hour|day|week|fortnight|month|quarter|year)s?\b|"
                r"\bimmediately\b|\bsame\s+day\b|\bwithin\s+\d|\b\d{1,2}:\d{2}\b|"
                r"\bnext\s+(?:day|week|month)\b|\bovernight\b", re.I),
     "a length of time"),
    ("money",
     re.compile(r"\bhow\s+much\b|\bwhat\s+(?:is\s+the\s+)?(?:cost|fee|price|charge)\b|"
                r"\bhow\s+expensive\b", re.I),
     re.compile(r"₹|\brs\.?\s*\d|\b\d[\d,]*\s*(?:rupees|inr)\b|\bfree\b|"
                r"\bno\s+(?:charge|fee|cost)\b|\b\d+\s*(?:%|percent)\b", re.I),
     "an amount of money"),
    ("permission",
     re.compile(r"\b(?:can|may|am\s+i\s+allowed\s+to|are\s+we\s+allowed\s+to)\s+"
                r"(?:i|we|you)\b|\bdo\s+(?:i|we)\s+need\b|\bis\s+it\s+(?:ok|okay|"
                r"allowed|permitted|acceptable)\b|\bam\s+i\s+(?:allowed|permitted)\b",
                re.I),
     re.compile(r"\byes\b|\bno\b|\byou\s+(?:can|cannot|may|must|need)\b|"
                r"\bpermitted\b|\bnot\s+allowed\b|\bprohibited\b|"
                r"\brequires?\b|\bapproval\b|\bsign-?off\b", re.I),
     "a yes or a no"),
    ("quantity",
     re.compile(r"\bhow\s+many\b|\bhow\s+much\s+(?:is|can)\b|"
                r"\bwhat\s+(?:is|are)\s+(?:the\s+)?(?:\w+\s+){0,3}"
                r"(?:limit|limits|threshold|thresholds|maximum|minimum|cap|"
                r"allowance|quota|ceiling)\b", re.I),
     re.compile(r"\b\d[\d,]*\b|\bunlimited\b|\bno\s+limit\b", re.I),
     "a number"),
    ("eligibility",
     re.compile(r"\bam\s+i\s+eligible\b|\bdo\s+(?:i|we|they)\s+qualify\b|"
                r"\bwho\s+(?:is|are)\s+eligible\b", re.I),
     re.compile(r"\beligible\b|\bqualif\w+\b|\byes\b|\bno\b|\bonly\b|"
                r"\brequires?\b", re.I),
     "an eligibility verdict"),
]

# Scope qualifiers that come in opposed pairs. A rule about *external* sends is
# not a rule the person asking about an *internal* send has walked past, and
# reporting it as one is the single most annoying false positive this check can
# produce — it trains the reader to ignore the warning.
_SCOPE_PAIRS: tuple[tuple[str, str], ...] = (
    ("external", "internal"),
    ("production", "staging"),
    ("production", "development"),
    ("metro", "non-metro"),
    ("retail", "institutional"),
    ("permanent", "temporary"),
    ("outbound", "inbound"),
    ("paid", "free"),
)


def _scoped_elsewhere(sentence_terms: set[str], question_terms: set[str]) -> str:
    """Name the qualifier that puts this condition in a different room."""
    for a, b in _SCOPE_PAIRS:
        for here, there in ((a, b), (b, a)):
            if here in sentence_terms and there in question_terms and \
                    here not in question_terms:
                return here
    return ""


MIN_SHARED_TERMS = 2
CARRY_SHARE = 0.45
MAX_REPORTED = 3


@dataclass
class Omission:
    kind: str
    explanation: str
    sentence: str
    shared: list[str] = field(default_factory=list)
    threshold: float | None = None
    asked_value: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "explanation": self.explanation,
                "sentence": self.sentence[:300], "shared": self.shared[:6],
                "threshold": self.threshold, "askedValue": self.asked_value}


@dataclass
class PurposeResult:
    omissions: list[Omission] = field(default_factory=list)
    unanswered: str = ""
    expected: str = ""
    go_ahead: bool = False
    off_topic: bool = False
    considered: int = 0

    @property
    def defeated(self) -> bool:
        return bool(self.omissions) or bool(self.unanswered) or self.off_topic

    def as_dict(self) -> dict[str, Any]:
        return {"omissions": [o.as_dict() for o in self.omissions],
                "unansweredFocus": self.unanswered, "expectedShape": self.expected,
                "unconditionalGoAhead": self.go_ahead,
                "offTopic": self.off_topic,
                "conditionSentencesConsidered": self.considered}


def _gates_in(sentence: str) -> list[tuple[str, str]]:
    return [(kind, human) for kind, pattern, human in _GATES
            if pattern.search(sentence)]


def _sentences(sources: list[str]) -> list[str]:
    out = []
    for src in sources or []:
        for raw in _SENT.split(src or ""):
            s = " ".join(raw.split())
            if 25 <= len(s) <= 320 and not s.startswith("#"):
                out.append(s)
    return out


def inspect(question: str, answer: str, sources: list[str]) -> PurposeResult:
    """Did this answer leave out something in the sources that changes what the
    reader should do — or answer a different question than the one asked?"""
    result = PurposeResult()
    q_terms = set(_content(question))
    a_terms = set(_content(answer))
    a_low = (answer or "").lower()
    answer_gates = {kind for kind, _ in _gates_in(answer or "")}
    asked_numbers = _numbers(question)

    # ---- 1 · a governing condition, on this subject, that the answer skips ---
    candidates = _sentences(sources)
    result.considered = len(candidates)
    seen: set[str] = set()
    for sentence in candidates:
        gates = _gates_in(sentence)
        if not gates:
            continue
        s_terms = set(_content(sentence))
        shared = sorted(q_terms & s_terms)

        # Relevance. Two independent routes in, because a number crossing a
        # threshold named in the document is a stronger signal than any amount
        # of vocabulary overlap.
        above, up_to = _bands(sentence)
        crossed: tuple[float, float] | None = None
        outside = False
        for asked in asked_numbers:
            # A rule that governs everything above N, and the question is above N.
            for limit in above:
                if 0 < limit < asked and asked / limit <= 10_000:
                    if crossed is None or limit > crossed[0]:
                        crossed = (limit, asked)
            # A rule that governs everything up to N, and the question is over N:
            # this tier is not the one that binds here.
            for limit in up_to:
                if 0 < limit < asked and asked / limit <= 10_000:
                    outside = True
            # A bare threshold with no direction word — treat as a crossing, but
            # weakly: it still needs vocabulary overlap to be reported.
            if crossed is None and not above and not up_to:
                for limit in _numbers(sentence):
                    if 0 < limit < asked and asked / limit <= 10_000:
                        if crossed is None or limit > crossed[0]:
                            crossed = (limit, asked)

        if outside and crossed is None:
            # The question sits outside this tier's band entirely. Reporting it
            # would hand a developer a rule their case does not fall under.
            continue

        relevant = len(shared) >= MIN_SHARED_TERMS or (
            crossed is not None and bool(shared))
        if not relevant:
            continue

        # Applicability before omission. A rule scoped to the opposite side of a
        # distinction the question sits on was never binding on this reader.
        if _scoped_elsewhere(s_terms, q_terms):
            continue

        # Did the answer carry it? Either it repeats the condition's own
        # vocabulary, or it at least states a gate of the same kind. Both are
        # acceptable — we are checking that the reader was warned, not that the
        # wording matched.
        overlap = (len(s_terms & a_terms) / len(s_terms)) if s_terms else 0.0
        kinds = {k for k, _ in gates}
        carried = (overlap >= CARRY_SHARE and bool(kinds & answer_gates)) or (
            crossed is None and bool(kinds & answer_gates) and overlap >= 0.3)
        if carried:
            continue

        key = sentence[:80]
        if key in seen:
            continue
        seen.add(key)
        kind, human = gates[0]
        result.omissions.append(Omission(
            kind=kind, explanation=human, sentence=sentence, shared=shared,
            threshold=crossed[0] if crossed else None,
            asked_value=crossed[1] if crossed else None))
        if len(result.omissions) >= MAX_REPORTED:
            break

    # Sort so a crossed threshold is reported first: it is the most concrete and
    # the least arguable finding we can hand a developer.
    result.omissions.sort(key=lambda o: (o.threshold is None, -len(o.shared)))
    result.go_ahead = bool(result.omissions) and bool(_GO_AHEAD.search(a_low))

    # ---- 1b · the answer is about something else entirely -------------------
    # The plainest failure of all, and the one a reader spots instantly while
    # every other check reports clean: ask for the approved monthly limit, get a
    # correct, well-sourced, fully verified paragraph about a fund's drawdown.
    # Every claim in it checks out. It is not an answer.
    #
    # Deliberately conservative — it fires only on a *total* miss, where the
    # answer and the question have no subject word in common at all. A partial
    # overlap is a judgement call and belongs to the adjudicator, not to a
    # regular expression.
    if len(q_terms) >= 4 and len(a_terms) >= 12:
        # Match on a long shared prefix as well as an exact stem, so
        # "recruitment" and "recruiter" count as the same subject. The floor of
        # six characters is what keeps "month" from matching "monthly" — a real
        # off-topic answer about a fund's *monthly* drawdown must not be excused
        # by a question about a *monthly* limit.
        def related(a: str, b: str) -> bool:
            if a == b:
                return True
            short, long = (a, b) if len(a) <= len(b) else (b, a)
            return len(short) >= 6 and long.startswith(short)

        shared_topic = any(related(q, a) for q in q_terms for a in a_terms)
        if not shared_topic:
            result.off_topic = True

    # ---- 2 · answered the adjacent question ---------------------------------
    for name, asks, expects, shape in _FOCUS:
        if not asks.search(question or ""):
            continue
        if expects.search(answer or ""):
            break
        result.unanswered, result.expected = name, shape
        break

    return result



# ------------------------------------------------- objective satisfaction ---
# This part needs no sources at all, which is the whole point of it. The
# omission check above compares an answer against the organisation's documents;
# this one compares the answer against *what the person said they were trying to
# do*. Our mentor's car-wash question has no governing document anywhere — it is
# just a person with two objectives, one of which the model quietly traded away.
# See `objective.py` for how the objectives are read out of the question.
OBJECTIVE_UNSERVED = "objective_unserved"


def _objective_signal(prompt: str, answer: str) -> tuple[float, list[str], dict[str, Any]]:
    """Score, evidence and detail for the objectives the answer never engaged."""
    obj = objective.inspect(prompt or "", answer or "")
    detail: dict[str, Any] = {"objectiveCheck": obj.as_dict()}
    if not obj.defeated:
        return 0.0, [], detail

    target = obj.headline
    assert target is not None
    # The trade-off shape is scored higher because it is the one where an
    # objective is *chosen against* rather than merely missed.
    score = 0.66 if obj.is_choice else 0.5
    if len(obj.unserved) > 1:
        score = min(1.0, score + 0.06 * (len(obj.unserved) - 1))
    evidence = [
        f"the question has {len(obj.objectives)} thing(s) the person is trying to "
        f"achieve and the answer engages with "
        f"{len(obj.objectives) - len(obj.unserved)} of them — "
        + objective.describe(obj)]
    if obj.is_choice:
        evidence.append("the question asked the model to choose between two options, "
                        "and it chose one by dropping something the person asked for")
    detail["purposeUnserved"] = True
    detail["unservedObjective"] = target.as_dict()
    detail["plainEnglish"] = objective.describe(obj)
    return score, evidence, detail


# ------------------------------------------------------------- detector ---
def purpose(answer: str = "", prompt: str = "", sources: list[str] | None = None,
            retrieved: list[str] | None = None, **_: Any) -> DetectorResult:
    """An ordinary detector: deterministic, inline, zero tokens.

    The score is deliberately blunt. A skipped condition that the answer then
    invites the reader to act on is the worst case this system can produce
    without ever saying anything false, and it is priced accordingly."""
    if not (answer or "").strip():
        return DetectorResult("purpose", score=0.0, confidence=0.4,
                              evidence=["no answer text to check"],
                              detail={"reason": "empty answer",
                                      "omittedCondition": False})
    # Does the answer serve what the person was trying to do? This runs first
    # and without sources, because it needs none.
    obj_score, obj_evidence, obj_detail = _objective_signal(prompt, answer)

    # Everything retrieval put in front of the agent, not only what it cited.
    pool = list(retrieved or []) or list(sources or [])
    if not pool:
        # Nothing to have *omitted* — but the objective check still applies, and
        # on a question with no governing document it is the only thing that
        # does. This is the path the car-wash question takes.
        return DetectorResult(
            "purpose", score=round(obj_score, 4),
            confidence=0.72 if obj_score else 0.35,
            labels=[PURPOSE_DEFEATED, OBJECTIVE_UNSERVED] if obj_score else [],
            evidence=obj_evidence or ["no source text was retrieved, so there is no "
                                      "condition this answer could be measured against"],
            detail={"reason": "no sources", "omittedCondition": False, **obj_detail})

    r = inspect(prompt, answer, pool)

    score, evidence = obj_score, list(obj_evidence)
    if r.omissions:
        first = r.omissions[0]
        score = 0.62 if first.threshold is not None else 0.5
        if r.go_ahead:
            score = min(1.0, score + 0.22)
        if len(r.omissions) > 1:
            score = min(1.0, score + 0.06 * (len(r.omissions) - 1))
        if first.threshold is not None:
            evidence.append(
                f"the question is about {first.asked_value:,.0f} and the governing "
                f"document gates at {first.threshold:,.0f}, but the answer never "
                f"mentions it: \"{first.sentence[:150]}\"")
        else:
            evidence.append(
                f"the answer leaves out a condition in the source that applies here — "
                f"{first.explanation}: \"{first.sentence[:150]}\"")
        if r.go_ahead:
            evidence.append("and it tells the reader to go ahead anyway")
    if r.off_topic:
        score = max(score, 0.5)
        evidence.append("the answer shares no subject word with the question — every "
                        "claim in it may be true and it is still not an answer to what "
                        "was asked")
    if r.unanswered:
        score = max(score, 0.42)
        evidence.append(f"the question asks for {r.expected} and the answer contains "
                        f"none ({r.unanswered})")

    if not evidence:
        evidence.append(f"no condition in the {r.considered} source sentence(s) checked "
                        f"is left out, and the answer addresses what was asked")

    labels = [PURPOSE_DEFEATED] if (r.defeated or obj_score) else []
    if obj_score:
        labels.append(OBJECTIVE_UNSERVED)

    return DetectorResult(
        "purpose", score=round(score, 4),
        confidence=0.78 if (r.defeated or obj_score) else 0.66,
        labels=labels,
        evidence=evidence,
        # `omittedCondition` is what makes routing able to treat this as a fact
        # about the text rather than a probability — the same way a numeric
        # contradiction is treated.
        detail={**r.as_dict(), **obj_detail,
                "measuredAgainst": ("everything retrieval surfaced"
                                    if retrieved else "the cited sources only"),
                "sourceSentences": len(pool),
                "omittedCondition": bool(r.omissions),
                "unconditionalGoAhead": r.go_ahead})
