"""When the assistant declines, that is the system working — not a risk.

Three of the nine screenshots in our last review showed the same failure, and it
is the most damaging kind this product can have: **the assistant did exactly the
right thing and the control plane made it look broken.**

> *"I cannot make a guess regarding your eligibility, as refund decisions must be
> based on the specific criteria outlined in our policy."*
>
> → risk price 80 · 2 of 2 claims not settled by anything we hold · ⚠️ check this
> before you act on it

That is a correct, safe refusal being priced like a hallucination. The cause is
simple and it was hiding in plain sight: our claim extractor matches on words
like *policy*, *criteria* and *must*, so the refusal reads as a checkable
assertion. Grounding then looks for support in the corpus, finds none — of course
it doesn't, the sentence is about the assistant's own limits, not about the world
— and reports it as unverifiable.

The fix is a distinction the whole pipeline was missing:

**An abstention is a statement about the system, not about the world.** The
system is authoritative about its own limits, so there is nothing to verify and
nothing to cite. "I cannot advise on ranking candidates by age" needs a source
exactly as much as "I would be glad to help" does — which is to say, none.

Three things fall out of getting this right, and all three matter to a reader:

1. **A full abstention is a clean outcome.** Every material sentence declines,
   defers to a human, or explains a limit; nothing asserts a fact. It passes,
   and the user is told plainly that the assistant declined rather than being
   shown a warning panel about an answer that contains no claims.

2. **A partial abstention is split, not waved through.** *"I cannot guess whether
   you qualify — refund decisions follow the 30-day window for unused services"*
   declines **and** asserts. The refusal needs no source. The 30-day window very
   much does, and it is checked exactly as it would be in any other answer. This
   is the case a cruder rule gets wrong in one direction or the other.

3. **A capability claim is checked against the registry.** *"I would need to look
   up your account details and transaction history"* tells the reader this
   assistant can reach their account. Whether it can is not a matter of opinion —
   the registry says which tools are bound to this application and what each one
   is allowed to read. An answer that claims an ability the registry does not
   grant is making a false promise about the system itself, and that is worth
   catching: it is how a user ends up waiting for a lookup that will never
   happen.

None of this weakens any control. An abstention that also asserts is still
checked on what it asserts, an abstention is never allowed to carry a side
effect, and an abstention on an irreversible action does not lift the evidence
floor — there is simply nothing there for the floor to be applied to.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .detectors import DetectorResult

OVERCLAIM = "capability_overclaim"

# A first-person statement about what this assistant can, cannot or will not do.
# Deliberately narrow: it must be the assistant talking about itself. "The policy
# cannot be waived" is a claim about the world and must not match.
_ABSTAIN = re.compile(
    r"\bI\s+(?:cannot|can't|can\s+not|am\s+not\s+able|am\s+unable|do\s+not|don't|"
    r"will\s+not|won't|must\s+not|should\s+not|am\s+not\s+(?:authoris|authoriz)ed|"
    r"am\s+not\s+permitted|am\s+not\s+allowed|lack|do\s+not\s+have)\b"
    r"|\b(?:I'm|I\s+am)\s+(?:not\s+able|unable|not\s+in\s+a\s+position)\b"
    r"|\bI\s+(?:would|will)\s+need\s+to\b"
    # A reviewer found this hole with a real screenshot: the assistant said
    # "I cannot fulfill this request." and then "My purpose is to assist with
    # ..." — the second sentence was not recognised, so half of a clean refusal
    # was measured as an unsupported factual claim and the whole answer
    # escalated. Every ordinary way an assistant describes its own remit
    # belongs here.
    r"|\bmy\s+(?:role|purpose|job|function|remit|scope)\s+(?:is|here\s+is)\b"
    r"|\bI\s+am\s+(?:designed|built|here|intended|meant|configured)\s+to\b"
    r"|\bI\s+(?:can|could)\s+only\s+(?:help|assist|answer|provide)\b"
    r"|\bI\s+(?:do\s+not|don't)\s+have\s+(?:access|the\s+ability|permission)\b"
    r"|\bthat\s+(?:is|falls)\s+outside\s+(?:the\s+)?scope\b"
    r"|\bI'?m\s+(?:only|just)\s+able\s+to\b"
    r"|\bfor\s+(?:that|this)\s+you'?ll\s+need\b"
    r"|\bthat\s+is\s+outside\s+(?:my|this\s+assistant'?s)\b"
    r"|\bthis\s+(?:assistant|system)\s+(?:cannot|does\s+not|is\s+not)\b",
    re.I)

# Deferring to a person or a process is the other half of a good refusal. On its
# own it asserts nothing either.
_DEFER = re.compile(
    r"\b(?:a\s+)?(?:named\s+)?(?:human|person|colleague|manager|engineer|recruiter|"
    r"approver|reviewer|specialist|agent)\s+(?:can|will|should|must|would|needs?\s+to)\b"
    r"|\bplease\s+(?:contact|speak|check|raise|ask)\b"
    r"|\bI\s+can\s+(?:help|assist)\s+you\s+(?:with|by)\b"
    r"|\bso\s+that\s+a\s+\w+\s+(?:can|could)\b",
    re.I)

# What an answer promises this assistant is able to DO. Distinct from a promise
# about the world: this one the registry can settle outright.
_CAPABILITY_CLAIM = re.compile(
    r"\bI\s+(?:can|could|will|shall|am\s+able\s+to)\s+"
    r"(?P<verb>look\s+up|check|retrieve|fetch|pull|access|read|view|see|open|"
    r"query|search|issue|refund|send|restart|reboot|deploy|approve|cancel|"
    r"update|change|schedule|book|escalate|raise|create|delete)\b"
    r"|\bI\s+(?:would|will)\s+need\s+to\s+"
    r"(?P<verb2>look\s+up|check|retrieve|access|read|query|pull)\b"
    r"|\bI\s+have\s+access\s+to\b"
    r"|\blet\s+me\s+(?P<verb3>look\s+up|check|retrieve|access|pull|fetch)\b",
    re.I)

# What the promised verb would actually require, in registry terms. An assistant
# that can only read policy documents has no business offering to read an
# account.
_VERB_CAPABILITY: dict[str, tuple[str, ...]] = {
    "look up": ("read_customer", "read_candidate", "read_credit", "read_logs",
                "read_segment"),
    "check": ("read_customer", "read_candidate", "read_credit", "read_logs",
              "read_segment"),
    "retrieve": ("read_customer", "read_candidate", "read_credit", "read_logs"),
    "fetch": ("read_customer", "read_candidate", "read_credit", "read_logs"),
    "pull": ("read_customer", "read_candidate", "read_credit", "read_logs"),
    "access": ("read_customer", "read_candidate", "read_credit", "read_logs",
               "read_segment"),
    "read": ("read_customer", "read_candidate", "read_credit", "read_logs",
             "read_segment"),
    "view": ("read_customer", "read_candidate", "read_credit", "read_logs"),
    "query": ("read_customer", "read_candidate", "read_credit", "read_logs"),
    "search": ("read_customer", "read_candidate", "read_credit", "read_logs"),
    "issue": ("approve_credit",),
    "refund": ("approve_credit",),
    "send": ("send_campaign", "write_ticket"),
    "restart": ("restart_service",),
    "reboot": ("restart_service",),
    "deploy": ("restart_service",),
    "approve": ("approve_credit", "schedule_interview"),
    "schedule": ("schedule_interview",),
    "book": ("schedule_interview",),
    "update": ("write_ticket",),
    "create": ("write_ticket", "send_campaign"),
    "delete": (),
    "cancel": (),
}

# The subject a capability claim is about. This is what makes the check precise
# rather than merely suspicious: "look up" needs *some* read capability, but
# "look up your account" needs the one that reads a customer, and an assistant
# holding only `read_segment` promising an account lookup is making a promise it
# cannot keep.
_SUBJECT = re.compile(
    r"\b(account|transaction|payment|card|statement|balance|order|ticket|case|"
    r"candidate|application|profile|log|trace|incident|segment|campaign|"
    r"history|record)s?\b", re.I)

_READ_VERBS = frozenset({"look up", "check", "retrieve", "fetch", "pull", "access",
                         "read", "view", "query", "search"})

_SUBJECT_CAPABILITY: dict[str, tuple[str, ...]] = {
    "account": ("read_customer",), "transaction": ("read_customer", "read_credit"),
    "payment": ("read_customer", "read_credit"), "card": ("read_customer",),
    "statement": ("read_customer",), "balance": ("read_customer",),
    "order": ("read_customer",), "history": ("read_customer", "read_credit"),
    "ticket": ("read_customer", "write_ticket"),
    "case": ("read_customer", "write_ticket"),
    "candidate": ("read_candidate",), "application": ("read_candidate",),
    "profile": ("read_candidate", "read_customer"),
    "log": ("read_logs",), "trace": ("read_logs",), "incident": ("read_logs",),
    "segment": ("read_segment",), "campaign": ("read_segment", "send_campaign"),
    "record": ("read_customer", "read_candidate"),
}

_SENT = re.compile(r"(?<=[.!?])\s+")
MIN_SENTENCE = 12

# A refusal very often carries its reason, and the reason is a claim about the
# world: *"I cannot guess whether you qualify, **as refund decisions follow the
# 30-day window for unused services**"*. Splitting only on sentences would let
# that 30-day rule ride into the clear on the back of the refusal in front of
# it. These are the joints where the assistant stops talking about itself and
# starts talking about the world.
_REASON = re.compile(
    r",\s*(?:as|because|since|given\s+that)\s+"
    r"|\s+such\s+as\s+"
    r"|,\s*(?:which|whose)\s+"
    r"|\.\s+(?:This|That|The\s+policy|Our\s+policy)\s+", re.I)


# A refusal's reason is only worth checking when it carries a *particular* — a
# number, a period, a threshold. "…as that would violate anti-discrimination
# policy" is the assistant justifying its own decline in general terms, and
# hunting for a source for it produces a finding nobody can act on. "…as refund
# decisions follow the 30-day window" names a rule, and that we check.
_SPECIFIC = re.compile(
    r"\d|\b(day|days|week|weeks|month|months|year|years|hour|hours|rupee|rupees|"
    r"percent|per\s+cent|threshold|limit|window|deadline|tier|grade|score|points?|"
    r"approver|sign-?off)\b", re.I)


def _clauses(sentence: str) -> tuple[str, str]:
    """(the part where it declines, the part where it asserts a reason)."""
    match = _REASON.search(sentence)
    if not match:
        return sentence, ""
    head, tail = sentence[:match.start()], sentence[match.end():].strip()
    # Only a tail long enough to carry a real claim, and specific enough to be
    # checkable, is worth separating.
    if len(tail) >= 20 and _SPECIFIC.search(tail):
        return head, tail
    return sentence, ""

NONE, PARTIAL, FULL = "none", "partial", "full"


def is_abstention(sentence: str) -> bool:
    """Does this sentence decline, defer, or describe the assistant's limits?

    Shared with the claim extractor, the grounding pool and the judge, so there
    is exactly one definition of "asserts nothing about the world" rather than
    three that drift apart."""
    s = sentence or ""
    return bool(_ABSTAIN.search(s) or _DEFER.search(s))


def split(answer: str) -> tuple[list[str], list[str]]:
    """(sentences that decline, sentences that assert).

    The second list is what every other check in the system should be looking
    at. The first list is the assistant talking about itself."""
    declines, asserts = [], []
    for raw in _SENT.split((answer or "").strip()):
        s = raw.strip()
        if len(s) < MIN_SENTENCE:
            continue
        if not is_abstention(s):
            asserts.append(s)
            continue
        head, reason = _clauses(s)
        declines.append(head)
        # The refusal needs no source. Its stated reason is an ordinary claim and
        # goes through every check any other claim would.
        if reason and not is_abstention(reason):
            asserts.append(reason)
    return declines, asserts


def posture(answer: str) -> str:
    """none / partial / full."""
    declines, asserts = split(answer)
    if not declines:
        return NONE
    return FULL if not asserts else PARTIAL


@dataclass
class Overclaim:
    verb: str
    subject: str
    sentence: str
    needed: list[str] = field(default_factory=list)
    granted: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"verb": self.verb, "subject": self.subject,
                "sentence": self.sentence[:220],
                "capabilityNeeded": self.needed, "capabilityGranted": self.granted}


def _verb_of(match: re.Match[str]) -> str:
    for key in ("verb", "verb2", "verb3"):
        value = match.groupdict().get(key)
        if value:
            return " ".join(value.lower().split())
    return "access"


def overclaims(answer: str, granted: list[str]) -> list[Overclaim]:
    """Abilities the answer promises that the registry does not grant.

    The registry is the authority here, not the model. An application is bound to
    a set of tools and each tool declares what it may read or do; anything the
    answer promises beyond that is a false statement about the system, and the
    person reading it will act on it."""
    have = {c.lower() for c in (granted or [])}
    out: list[Overclaim] = []
    for raw in _SENT.split((answer or "").strip()):
        sentence = raw.strip()
        if len(sentence) < MIN_SENTENCE:
            continue
        for match in _CAPABILITY_CLAIM.finditer(sentence):
            verb = _verb_of(match)
            needed = _VERB_CAPABILITY.get(verb)
            if not needed:
                # We do not have a mapping for this verb. Saying nothing is the
                # only honest option — inventing a requirement would produce a
                # confident finding out of an unmapped word.
                continue
            subject = ""
            found = _SUBJECT.search(sentence[match.end():] or sentence)
            if found:
                subject = found.group(0).lower().rstrip("s")
            # Narrow the requirement by what the claim is about — but only for a
            # READ, where the subject really does decide which capability is
            # needed. "Restart the payment gateway" is about restarting, not
            # about payments, and narrowing it by its noun would ask for the
            # wrong capability and produce a confidently wrong finding.
            specific = _SUBJECT_CAPABILITY.get(subject) if verb in _READ_VERBS else None
            required = tuple(specific) if specific else tuple(needed)
            if have & set(required):
                continue
            out.append(Overclaim(verb=verb, subject=subject, sentence=sentence,
                                 needed=sorted(required), granted=sorted(have)))
            break
        if len(out) >= 3:
            break
    return out


# ------------------------------------------------------------- detector ---
def abstention(answer: str = "", capabilities: list[str] | None = None,
               **_: Any) -> DetectorResult:
    """Records the posture, and prices only the capability overclaim.

    Declining is not a risk, so the score here is zero for any honest refusal.
    The one thing that *is* a risk is an answer promising the reader an ability
    this application does not have — which is a claim the registry settles
    outright, with no model and no corpus involved."""
    stance = posture(answer)
    bad = overclaims(answer, capabilities or [])

    declines, asserts = split(answer)
    detail = {
        "posture": stance,
        "declined": len(declines),
        "asserted": len(asserts),
        "declinedSentences": [s[:180] for s in declines[:3]],
        "overclaims": [o.as_dict() for o in bad],
        # The flag other checks read so a refusal is never counted as an
        # unsupported claim.
        "assertsNothing": stance == FULL and not bad,
    }

    if bad:
        first = bad[0]
        target = f" the customer's {first.subject}" if first.subject else " that"
        return DetectorResult(
            "abstention", score=0.55, confidence=0.82, labels=[OVERCLAIM],
            evidence=[f"the answer tells the reader it can {first.verb}{target}, but "
                      f"this application is not bound to any tool that grants "
                      f"{' or '.join(first.needed[:2])}"],
            detail=detail)

    if stance == FULL:
        return DetectorResult(
            "abstention", score=0.0, confidence=0.9,
            evidence=["the assistant declined and asserted nothing that needs a "
                      "source, so there is nothing here to verify"],
            detail=detail)
    if stance == PARTIAL:
        return DetectorResult(
            "abstention", score=0.0, confidence=0.75,
            evidence=[f"the assistant declined in {len(declines)} sentence(s) and "
                      f"asserted {len(asserts)}; only what it asserted is checked"],
            detail=detail)
    return DetectorResult(
        "abstention", score=0.0, confidence=0.6,
        evidence=["the answer makes no refusal or capability claim"], detail=detail)
