"""The second opinion, for the answers our documents cannot settle.

The problem statement's hardest line: *"There is often no reliable, real-time
ground truth to check a claim against — the same knowledge gaps that cause
hallucination can make automated verification difficult too."*

Lexical grounding handles the easy half: a claim that reuses the vocabulary of a
retrieved policy is supported, a figure that appears in no source is a
contradiction. It has nothing to say about the hard half — an answer to a
question our corpus never covered, or one covered only loosely. Those are
precisely the answers a person is most likely to act on and least able to check.
Every question cannot go to a human; that does not scale, and a reviewer buried
in clean answers stops reading them. So a second model adjudicates.

Two charges, one call
---------------------
The judge is asked two different questions about the same answer, and both come
back in one response because two calls would double the cost for no extra
information:

**Charge 1 — support.** Claim by claim: does this need a source at all, and does
the reference text settle it? "I can help with that" needs none. "Refunds settle
in 5 to 7 days" does. That distinction is what stops the check crying wolf.

**Charge 2 — sufficiency.** Whole answer: is there a condition, limit, exception
or approval requirement *in the reference text and relevant to what was asked*
that this answer leaves out? This is the car-wash class — every sentence true,
the reader's purpose defeated. `purpose.py` catches the version a deterministic
rule can see, for free, on every turn. The judge is here for the version it
cannot: the omission that needs reading comprehension.

Calibration, which is what "train the judge properly" has to mean here
---------------------------------------------------------------------
We are not fine-tuning a model on a laptop before a finale. What we can do — and
what actually moves judge quality — is four things, all of them in this file and
all of them measured:

1. **Exemplars at the decision boundary.** The four mistakes a judge of this kind
   makes are always the same, so it is shown one of each: a pleasantry it must
   not flag, a true-but-uncovered claim it must not clear, an entailment it must
   not mark uncovered, and a figure contradiction it must catch. See `EXEMPLARS`.
2. **Domain calibration.** What counts as material differs by department — an
   unhedged return figure is a regulatory event in Finance and a rounding error
   in Marketing. `DOMAIN_NOTES` injects the difference.
3. **A confidence floor.** A `contradicted` verdict returned at low confidence is
   downgraded to `uncovered` rather than trusted: we would rather say "nobody can
   confirm this" than accuse the answer of being wrong on a coin flip. The
   downgrade is recorded, not silent.
4. **A labelled evaluation set, in the repo, with a score.** `judge_cases.py` and
   `judge_eval.py`. "How do you know your judge is any good" is the question a
   finale jury asks about anything model-based, and the only good answer is a
   number and the command that produced it.

Four constraints keep it from becoming the thing it guards
----------------------------------------------------------
**Triggered, not routine.** Only when the evidence is already weak *and* the risk
price is already high enough to matter. A clean, grounded, cheap answer never
pays for a judge.

**It cannot decide.** Its output is an ordinary advisory signal, priced with
everything else. It cannot lower the evidence floor, lift a hard gate, or
un-block an irreversible action. It can raise risk and reduce uncertainty,
nothing else.

**It fails closed, and loudly.** Where the judge was *required* — nothing
authoritative covers the answer and the action advises or worse — an unreachable
judge marks the check mandatory-and-failed, and routing will not let that answer
take the clean-pass path. An unchecked answer is not a cleared answer.

**Its output is recorded, so replay stays exact.** A judged decision replays
against the judgement made at the time, not a fresh call. Re-running the judge
later is a *re-evaluation*, a different operation, labelled as one.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .detectors import DetectorResult, UNVERIFIABLE

MAX_CLAIMS = 6
MAX_SOURCE_CHARS = 3000
DEFAULT_TIMEOUT_S = 6.0

# Below this, a `contradicted` verdict is downgraded to `uncovered`. Accusing an
# answer of being wrong is a stronger act than saying nobody can confirm it, and
# it should need more confidence.
MIN_CONTRADICTION_CONFIDENCE = 0.45

# A claim worth adjudicating is a sentence that asserts something checkable.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_HEDGE = re.compile(r"\b(may|might|could|approximately|around|typically|usually|"
                    r"generally|in\s+most\s+cases)\b", re.I)
_CHECKABLE = re.compile(
    r"\d"
    # obligations and commitments
    r"|\b(policy|rule|must|will|shall|always|never|guarantee\w*|require\w*|"
    r"entitled|eligible|approved?|permitted|allowed|prohibited)\b"
    # things a customer is told they get — a promise is checkable even with no
    # number in it, and leaving these out let "you receive a dedicated account
    # manager" through as though it asserted nothing
    r"|\b(receives?|receive|provided?|provides|includes?|offers?|covers?|"
    r"grants?|assigned|comes\s+with|access\s+to)\b"
    # quantities, periods and money
    r"|\b(within|days?|hours?|weeks?|months?|percent|per\s+cent|rate|limit|"
    r"threshold|refund\w*|charge\w*|fee|cost|price|deadline|window)\b", re.I)

VERDICTS = ("supported", "contradicted", "uncovered", "not_a_claim")
SUFFICIENCY = ("complete", "omits_condition", "answers_different_question")


def needs_evidence(claim: str) -> bool:
    """Would a reader be harmed if this were wrong?

    The single most important distinction in this file. "I can help with that"
    needs no source; "refunds settle in 5 to 7 days" does. Treating them the
    same is how a checker earns a reputation for crying wolf. Shared with the
    offline judge so there is one definition, not two that drift.

    A sentence in which the assistant declines is excluded outright. It is a
    statement about the system, which the system is authoritative about, so
    there is nothing a source could settle — and asking a judge to settle it
    burns a model call to arrive at "unverifiable" for an answer that was
    correct."""
    from .abstain import is_abstention
    text = claim or ""
    if is_abstention(text):
        return False
    return bool(_CHECKABLE.search(text))


@dataclass
class ClaimVerdict:
    claim: str
    needs_evidence: bool
    verdict: str
    confidence: float
    note: str = ""
    downgraded_from: str = ""

    def as_dict(self) -> dict[str, Any]:
        out = {"claim": self.claim[:220], "needsEvidence": self.needs_evidence,
               "verdict": self.verdict, "confidence": round(self.confidence, 3),
               "note": self.note[:200]}
        if self.downgraded_from:
            out["downgradedFrom"] = self.downgraded_from
        return out


@dataclass
class Sufficiency:
    """Charge 2. The answer can be entirely true and still not be an answer."""
    verdict: str = ""
    confidence: float = 0.0
    omitted: str = ""
    note: str = ""

    @property
    def flagged(self) -> bool:
        return self.verdict in ("omits_condition", "answers_different_question")

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "confidence": round(self.confidence, 3),
                "omitted": self.omitted[:300], "note": self.note[:200]}


@dataclass
class Adjudication:
    ran: bool
    reason: str
    verdicts: list[ClaimVerdict] = field(default_factory=list)
    sufficiency: Sufficiency = field(default_factory=Sufficiency)
    model: str = ""
    domain: str = ""
    latency_ms: float = 0.0
    tokens: int = 0
    prompt_sha256: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ran": self.ran, "reason": self.reason, "model": self.model,
                "domain": self.domain,
                "latencyMs": round(self.latency_ms, 1), "tokens": self.tokens,
                "promptSha256": self.prompt_sha256, "error": self.error,
                "verdicts": [v.as_dict() for v in self.verdicts],
                "sufficiency": self.sufficiency.as_dict(),
                "downgraded": sum(1 for v in self.verdicts if v.downgraded_from)}


# ----------------------------------------------------------------- claims ---
def extract_claims(answer: str) -> list[str]:
    """Sentences that assert something a source could settle.

    Deterministic, so the same answer always produces the same claim list and a
    replayed judgement lines up with the claims it was made about."""
    from .abstain import split as _split

    # Only what the answer asserts about the world. A refusal, and a deferral to
    # a human, are separated out first — including the case where a refusal
    # carries a specific reason, which is split off and kept.
    declined, asserted = _split(answer)
    if declined and not asserted:
        # A pure refusal. There is nothing here a source could settle, and
        # sending it to a judge would spend a model call to be told so.
        return []

    out: list[str] = []
    for sentence in asserted or _SENTENCE.split((answer or "").strip()):
        s = sentence.strip()
        if len(s) < 25 or len(s) > 400:
            continue
        if not _CHECKABLE.search(s):
            continue
        out.append(s)
        if len(out) >= MAX_CLAIMS:
            break
    return out


# ---------------------------------------------------------------- trigger ---
def should_adjudicate(*, tier: str, price: float, pass_threshold: float,
                      grounding: DetectorResult | None, already_blocked: bool,
                      claims: list[str], scope: str = "",
                      purpose_flagged: bool = False) -> tuple[bool, str]:
    """Narrow on purpose. Each 'no' here is a model call not made.

    `scope` is the subject-scope verdict from `scope.py`. An `uncovered` question
    — one no registered system's documents cover — is the exact case the problem
    statement calls out, and it overrides the price floor: there is no cheaper
    way to check an answer nobody holds evidence for."""
    if already_blocked:
        return False, "the decision was already refused on capability or evidence grounds"
    if not claims:
        return False, "the answer makes no checkable claim"

    # Two overrides that fire below the price floor, because in both cases the
    # price is low precisely for the wrong reason.
    if scope == "uncovered":
        return True, ("no document held by any registered system covers this subject, "
                      "so there is nothing for a lexical check to measure against")
    if purpose_flagged:
        return True, ("a deterministic check found a condition the answer may have "
                      "left out, and a second reader is the cheapest way to confirm it")

    if price < pass_threshold:
        return False, (f"risk price {price} is below the pass threshold "
                       f"{pass_threshold}; nothing is at stake")

    weak_evidence = tier != "authoritative"
    unverifiable = bool(grounding and UNVERIFIABLE in (grounding.labels or []))
    loose = bool(grounding and grounding.ran and (grounding.score or 0) >= 0.34)

    if weak_evidence:
        return True, "the answer is not backed by an authoritative source"
    if unverifiable:
        return True, "grounding marked at least one claim unverifiable"
    if loose:
        return True, (f"grounding is loose (score {grounding.score}) and the price "
                      f"{price} is above the pass threshold")
    return False, "the answer is grounded in an authoritative source and scored clean"


def judge_required(*, tier: str, effective_action: str, scope: str = "") -> bool:
    """Was the second opinion load-bearing, rather than merely useful?

    Where nothing authoritative backs an answer and the action advises or worse,
    the judge is the only check standing between the reader and an unverifiable
    claim they will act on. If it does not answer, the decision may not take the
    clean-pass path — so the detector is recorded mandatory and routing has a
    floor for it. Below `advise` the stakes do not justify blocking on an
    unreachable dependency."""
    return (effective_action in ("advise", "decide", "execute")
            and (tier != "authoritative" or scope == "uncovered"))


# ------------------------------------------------------------ calibration ---
# The four mistakes a judge of this kind always makes, one exemplar each. Short
# on purpose: they are paying for themselves in every single call, so each one
# has to earn its tokens.
EXEMPLARS = (
    ('REFERENCE: "Refunds settle within 5-7 working days."\n'
     'CLAIM: "I would be glad to look into this for you."\n'
     '-> needs_evidence false, verdict not_a_claim '
     '(a pleasantry asserts nothing a reader could act on)'),
    ('REFERENCE: "Metro addresses: 2 to 3 working days from dispatch."\n'
     'CLAIM: "Most couriers in India deliver within a week."\n'
     '-> needs_evidence true, verdict uncovered '
     '(it may well be true; the reference text does not settle it, and your own '
     'knowledge of the world is not evidence here)'),
    ('REFERENCE: "Refunds are issued to the original payment method and settle '
     'within 5-7 working days."\n'
     'CLAIM: "Your money goes back to the card you paid with."\n'
     '-> needs_evidence true, verdict supported '
     '(different words, same fact — the reference text directly entails it)'),
    ('REFERENCE: "The Horizon Balanced Fund targets 8.4% annualised returns. '
     'Returns are not guaranteed."\n'
     'CLAIM: "The fund guarantees a 12.5% return every year."\n'
     '-> needs_evidence true, verdict contradicted '
     '(both the figure and the guarantee are incompatible with the reference)'),
)

# What counts as material differs by department. An unhedged return figure is a
# regulatory event in Finance and a rounding error in Marketing, and a judge that
# does not know which room it is in will be wrong in both.
DOMAIN_NOTES: dict[str, str] = {
    "finance-decide":
        "This is a regulated financial context. Any statement about returns, "
        "performance, guarantees, approval limits or amounts is material. A "
        "performance figure presented without the reference text's own "
        "'not guaranteed' qualification is contradicted, not merely uncovered.",
    "support-copilot":
        "This is a customer-facing support context. Timescales, entitlements, "
        "refund eligibility and what the customer must do next are material. "
        "Tone, apology and empathy are not claims.",
    "recruit-screen":
        "This is a hiring context. Scores, thresholds, progression rules and any "
        "statement about a candidate's suitability are material. A statement that "
        "presents a recommendation as a decision is contradicted where the "
        "reference text reserves the decision to a human.",
    "it-ops-agent":
        "This is a production operations context. Change windows, approval "
        "requirements, environment restrictions and reversibility are material. "
        "An answer that describes an action as routine where the reference text "
        "calls it irreversible is contradicted.",
    "marketing-copilot":
        "This is an outbound marketing context. Audience size limits, approval "
        "tiers, pricing claims and recall are material. Creative and stylistic "
        "statements are not claims.",
}

_SYSTEM = (
    "You adjudicate an AI assistant's answer against supplied reference text. "
    "You are a verifier, not an assistant: you never answer the user's question, "
    "never add information, and never judge tone or helpfulness.\n\n"
    "You have TWO charges.\n\n"
    "CHARGE 1 - SUPPORT. For each numbered claim decide two things.\n"
    "  needs_evidence: does this claim assert a specific fact, figure, policy, "
    "entitlement or commitment that a reader could be harmed by if it were "
    "wrong? Pleasantries, offers to help and generic statements do not.\n"
    "  verdict: one of\n"
    "    supported    - the reference text states or directly entails it\n"
    "    contradicted - the reference text states something incompatible\n"
    "    uncovered    - the reference text does not settle it either way\n"
    "    not_a_claim  - it asserts nothing checkable\n"
    "Judge ONLY against the reference text supplied. Your own knowledge of the "
    "world is not evidence here; if the reference text does not settle a claim, "
    "the verdict is 'uncovered' even when you believe the claim is true.\n\n"
    "CHARGE 2 - SUFFICIENCY. Look at the QUESTION, the reference text and the "
    "whole answer together. Every sentence in an answer can be true and the "
    "answer can still defeat what the person was trying to do, because it left "
    "out the one line that governed them. Decide one of\n"
    "    complete                   - nothing in the reference text that bears on "
    "this question is missing from the answer\n"
    "    omits_condition            - the reference text carries a condition, "
    "limit, threshold, exception, approval requirement or warning that applies to "
    "this question, and the answer does not mention it\n"
    "    answers_different_question - the answer is about something adjacent and "
    "does not give what was asked for\n"
    "When it is omits_condition, quote the omitted sentence from the reference "
    "text verbatim in 'omitted'. Do not invent a condition that is not there: "
    "'complete' is the right answer far more often than not.\n\n"
    "CALIBRATION - worked examples of the boundaries that get judged wrong:\n"
    + "\n".join(f"  [{i + 1}] " + e.replace("\n", "\n      ")
                for i, e in enumerate(EXEMPLARS))
    + "\n\nReply with JSON only, no prose:\n"
    "{\"verdicts\":[{\"n\":1,\"needs_evidence\":true,\"verdict\":\"uncovered\","
    "\"confidence\":0.0-1.0,\"note\":\"under 15 words\"}],"
    "\"sufficiency\":{\"verdict\":\"complete\",\"confidence\":0.0-1.0,"
    "\"omitted\":\"\",\"note\":\"under 15 words\"}}"
)


def system_prompt(domain: str = "") -> str:
    """The judge's instructions, calibrated for the department it is judging."""
    note = DOMAIN_NOTES.get(domain or "")
    return _SYSTEM if not note else (
        _SYSTEM + "\n\nDOMAIN CALIBRATION for this system: " + note)


def build_prompt(claims: list[str], sources: list[str], question: str = "") -> str:
    text = "\n\n".join(sources)[:MAX_SOURCE_CHARS]
    numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(claims))
    return (f"QUESTION\n{(question or '(not recorded)')[:400]}\n\n"
            f"REFERENCE TEXT\n{text or '(no reference text was retrieved)'}\n\n"
            f"CLAIMS\n{numbered}")


def _parse(raw: str, claims: list[str]) -> tuple[list[ClaimVerdict], Sufficiency]:
    """Strict. A judge that returns something unparseable has not judged."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("the adjudicator did not return JSON")
    data = json.loads(text[start:end + 1])
    rows = data.get("verdicts")
    if not isinstance(rows, list):
        raise ValueError("the adjudicator returned no verdicts array")

    out: list[ClaimVerdict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            n = int(row.get("n", 0))
        except (TypeError, ValueError):
            continue
        if not 1 <= n <= len(claims):
            continue
        verdict = str(row.get("verdict", "")).strip().lower()
        if verdict not in VERDICTS:
            continue
        try:
            conf = float(row.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = min(1.0, max(0.0, conf))

        # The confidence floor. We would rather record "nobody can confirm this"
        # than accuse an answer of being wrong on a coin flip — and the downgrade
        # is written down, so nobody has to take our word for how often it fires.
        downgraded = ""
        if verdict == "contradicted" and conf < MIN_CONTRADICTION_CONFIDENCE:
            verdict, downgraded = "uncovered", "contradicted"

        out.append(ClaimVerdict(
            claim=claims[n - 1], needs_evidence=bool(row.get("needs_evidence", True)),
            verdict=verdict, confidence=conf,
            note=str(row.get("note", "")), downgraded_from=downgraded))
    if not out:
        raise ValueError("no usable verdict was returned")

    suff = Sufficiency()
    raw_suff = data.get("sufficiency")
    if isinstance(raw_suff, dict):
        v = str(raw_suff.get("verdict", "")).strip().lower()
        if v in SUFFICIENCY:
            try:
                sconf = float(raw_suff.get("confidence", 0.5))
            except (TypeError, ValueError):
                sconf = 0.5
            suff = Sufficiency(v, min(1.0, max(0.0, sconf)),
                               str(raw_suff.get("omitted", "")),
                               str(raw_suff.get("note", "")))
    return out, suff


# ------------------------------------------------------------------- run ---
def adjudicate(answer: str, sources: list[str], judge: Any,
               timeout_s: float = DEFAULT_TIMEOUT_S, *,
               question: str = "", domain: str = "") -> Adjudication:
    """Ask the judge. Any failure leaves the answer unverified, never cleared."""
    claims = extract_claims(answer)
    if not claims:
        return Adjudication(False, "no checkable claim", domain=domain)

    system = system_prompt(domain)
    prompt = build_prompt(claims, sources, question)
    sha = hashlib.sha256((system + prompt).encode()).hexdigest()[:16]
    started = time.perf_counter()
    try:
        raw, usage = judge.adjudicate(system, prompt, timeout_s=timeout_s)
        verdicts, suff = _parse(raw, claims)
    except Exception as exc:                                         # noqa: BLE001
        return Adjudication(
            False, "the adjudicator could not be reached or returned nothing usable",
            model=getattr(judge, "judge_model", ""), domain=domain,
            latency_ms=(time.perf_counter() - started) * 1000,
            prompt_sha256=sha, error=f"{type(exc).__name__}: {exc}"[:180])

    return Adjudication(
        True, "adjudicated", verdicts=verdicts, sufficiency=suff,
        model=getattr(judge, "judge_model", "") or getattr(judge, "name", ""),
        domain=domain,
        latency_ms=(time.perf_counter() - started) * 1000,
        tokens=int((usage or {}).get("totalTokens", 0)),
        prompt_sha256=sha)


# ---------------------------------------------------------------- scoring ---
def to_detector(adj: Adjudication, *, required: bool = False) -> DetectorResult:
    """Turn the judgement into an ordinary signal, priced like any other.

    Advisory by score, never by veto: an adjudicator that could fail a decision
    closed would be a model with the final word, which is the opposite of what
    this system is for. `required` says only that an *absent* judgement is a
    governance gap — not that its opinion binds anyone."""
    if not adj.ran:
        return DetectorResult(
            "adjudication",
            status="failed" if adj.error else "skipped_by_policy",
            error_code="adjudicator_unavailable" if adj.error else None,
            requirement=("mandatory" if (required and adj.error) else "advisory"),
            evidence=[adj.error or adj.reason],
            detail={**adj.as_dict(), "required": bool(required)})

    material = [v for v in adj.verdicts if v.needs_evidence]
    suff = adj.sufficiency

    if not material and not suff.flagged:
        return DetectorResult(
            "adjudication", score=0.0, confidence=0.6, requirement="advisory",
            evidence=["a second model found no claim that needed a source, and nothing "
                      "in the sources that the answer left out"],
            detail=adj.as_dict())

    contradicted = [v for v in material if v.verdict == "contradicted"]
    uncovered = [v for v in material if v.verdict == "uncovered"]

    # A contradiction is a fact about the text; an uncovered claim is an absence.
    # They are not worth the same and must not be averaged together.
    score = min(1.0, (len(contradicted) * 0.55 + len(uncovered) * 0.30)
                / max(1, len(material)) + (0.25 if contradicted else 0.0))

    # Charge 2. An omission is priced near a contradiction because it does the
    # same damage: the reader acts, and the thing they were trying to do fails.
    if suff.verdict == "omits_condition":
        score = min(1.0, max(score, 0.55) + 0.1)
    elif suff.verdict == "answers_different_question":
        score = min(1.0, max(score, 0.42))

    labels = [UNVERIFIABLE] if uncovered and not contradicted else []
    if contradicted:
        from .detectors import HALLUCINATION
        labels = [HALLUCINATION]
    if suff.flagged:
        from .purpose import PURPOSE_DEFEATED
        labels = sorted(set(labels) | {PURPOSE_DEFEATED})

    evidence = []
    if contradicted:
        evidence.append(f"a second model found {len(contradicted)} claim(s) that the "
                        f"sources contradict: \"{contradicted[0].claim[:110]}\"")
    if suff.verdict == "omits_condition":
        evidence.append("a second model found a condition in the sources that applies "
                        "here and is missing from the answer"
                        + (f": \"{suff.omitted[:150]}\"" if suff.omitted else ""))
    if suff.verdict == "answers_different_question":
        evidence.append("a second model found the answer addresses a different question "
                        "than the one asked"
                        + (f" — {suff.note[:100]}" if suff.note else ""))
    if uncovered:
        evidence.append(f"{len(uncovered)} of {len(material)} claim(s) that need a "
                        f"source are not settled by anything we hold: "
                        f"\"{uncovered[0].claim[:110]}\"")
    if not evidence:
        evidence.append(f"a second model found all {len(material)} material claim(s) "
                        f"supported by the retrieved sources, and nothing omitted")

    confidence = (round(sum(v.confidence for v in material) / len(material), 3)
                  if material else round(suff.confidence or 0.5, 3))

    return DetectorResult(
        "adjudication", score=round(score, 4), confidence=confidence,
        labels=labels, evidence=evidence, requirement="advisory",
        detail={**adj.as_dict(),
                "materialClaims": len(material),
                "contradicted": len(contradicted), "uncovered": len(uncovered),
                # A contradiction found here is a fact about the text, and the
                # contradiction floor in routing treats it as one.
                "contradiction": bool(contradicted),
                # And so is an omission the judge can quote from the source: it
                # takes the same car-wash floor as the deterministic check.
                "omittedCondition": suff.verdict == "omits_condition",
                "omissions": ([{"kind": "judged",
                                "explanation": "a second model found it missing",
                                "sentence": suff.omitted}]
                              if suff.verdict == "omits_condition" and suff.omitted
                              else [])})
