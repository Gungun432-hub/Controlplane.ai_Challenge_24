"""Did the answer serve what the person was actually trying to do?

Our mentor's example, and the one he told us to build the demo around:

> *"My car wash station is two kilometres from my house, but I'm a fitness freak
> and I want to burn 200 calories today. Should I walk or should I drive?"*
>
> *"The answer was: since you're a fitness freak, I suggest you walk. **Then what
> is the purpose of going to a car wash?** The purpose is lost."*

He was explicit about why this case and not a violent one: *"if you say 'I want
to kill my employee', you go and check with Gemini, it will block you — their
models are sophisticated. If you can think about something that the models will
**not** block, think about it."* This is that thing. No frontier model refuses
it, nothing in the answer is false, and the person drives away without a clean
car.

Why this needs its own check
----------------------------
We already had an off-topic check, and it cannot see this. It fires only when the
answer shares **no subject word at all** with the question — and here the overlap
is substantial: *walk*, *calories*, *fitness*, *kilometres*. Measured at the level
of the whole answer, this looks perfectly on topic. It is.

The failure is one level down. A question does not have one topic; it has one or
more **objectives** — things the person is trying to achieve — and an answer can
be entirely on topic while silently abandoning one of them. So this file works at
the level of the objective:

1. **Pull the objectives out of the question.** Two kinds, and both matter:
   * a **goal** the person states outright — *"I want to burn 200 calories"*,
     *"I need to return this order"*, *"so that I can close the ticket"*;
   * an **errand**, the thing the trip or the request is *for* — *"to my car wash
     station"*, *"for a refund"*, *"at the post office"*. This is the one that
     gets dropped, because it is usually assumed rather than argued for.
2. **Check the answer engages with each one.** Not that it succeeds — that it
   addresses it at all.
3. **Report the objective the answer never touched**, by name, in the person's
   own words.

The trade-off shape gets special treatment, because it is where this failure
lives. *"Should I do X or Y?"* invites the model to pick a side, and picking a
side is exactly when an objective gets quietly traded away. When the question
offers a choice **and** an objective goes unserved, that is the car wash, and it
is scored highest.

Deliberately conservative
-------------------------
An objective counts as served if the answer engages **any** of its distinctive
words, matched on a long shared prefix so *return*/*returning*/*returns* are one
thing. A single content word in common is enough. That is a low bar on purpose:
the expensive error for a checker is the false alarm, and telling somebody their
perfectly good answer ignored them is the fastest way to get the whole control
plane switched off — which is the slide this deck opens with.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import abstain

GOAL = "goal"
ERRAND = "errand"
SUBJECT = "subject"

# Function words plus the vocabulary of asking, which never carries an objective.
_STOP = set("""
a an the and or but so if then than that this these those there here it its is
are was were be been being am do does did done have has had having will would
shall should can could may might must
i me my mine we us our ours you your yours he him his she her hers they them
their theirs
to at in on of for from by with without about into over under near around
what which who whom whose when where why how
please kindly just only very really quite some any all both each every other
now today tomorrow yesterday still yet also too much many more most
question answer help tell show give know think say said
""".split())

_WORD = re.compile(r"[a-z][a-z0-9'-]*")

# A goal the person states in so many words.
_GOAL = re.compile(
    r"\bI\s+(?:want|need|would\s+like|would\s+love|am\s+trying|'m\s+trying|"
    r"intend|plan|am\s+hoping|'m\s+hoping|am\s+looking)\s+to\s+(?P<g>[^.,;?!]{4,70})"
    r"|\bso\s+(?:that\s+)?I\s+can\s+(?P<g2>[^.,;?!]{4,70})"
    r"|\bin\s+order\s+to\s+(?P<g3>[^.,;?!]{4,70})"
    r"|\bmy\s+(?:goal|aim|plan|intention)\s+is\s+to\s+(?P<g4>[^.,;?!]{4,70})"
    r"|\bI\s+have\s+to\s+(?P<g5>[^.,;?!]{4,70})", re.I)

# The errand: what the trip, the request or the action is *for*. Almost always
# left implicit in the answer, which is precisely why it is the one that gets
# dropped.
_ERRAND = re.compile(
    r"\b(?:to|at|for)\s+(?:my|the|a|an|our|this)\s+"
    r"(?P<e>[a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,3}?)"
    r"(?=\s*(?:[.,;?!]|$|\b(?:is|are|was|were|and|but|or|so|because|which|that|"
    r"when|while|today|tomorrow|now|instead|rather)\b))", re.I)

# The thing the question is built around, when the person names it as theirs:
# *"**My car wash place** is two kilometres away."* Not every question with a
# possessive has an objective in it, so this one is only ever held against an
# answer in the trade-off shape below — see `inspect`.
_SUBJECT = re.compile(
    r"\bmy\s+(?P<s>[a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,2}?)\s+"
    r"(?:is|are|was|were|has|have)\b", re.I)

# "Should I walk or drive?" — the invitation to trade one objective for another.
# Two options have to be on the table: a bare *"what should I do?"* is a request
# for advice, not a trade-off, and treating it as one made the check noisy.
_CHOICE = re.compile(
    r"\bshould\s+I\s+[^.?!]{2,60}\bor\b"
    r"|\bis\s+it\s+better\s+to\s+[^.?!]{2,60}\bor\b"
    r"|\b(?:which|what)\s+(?:is|would\s+be)\s+(?:better|best)\b"
    r"|\bdo\s+you\s+recommend\s+[^.?!]{2,60}\bor\b"
    r"|\bor\s+should\s+I\b", re.I)

MIN_TERMS = 1
PREFIX_MATCH = 5

# Four concept families, and only four. A goal is usually stated in one
# vocabulary and answered in another — somebody who asks to "cut costs" is
# answered with "the saving", and a checker that calls that unaddressed is
# worse than no checker. These are the families that recur in the questions a
# workplace assistant actually gets, kept short deliberately: every word added
# here is a case the check can no longer see.
_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset("""cost costs costly cheap cheaper cheapest save saves saving savings
        spend spending spent money budget price prices pricey expensive
        rupees fee fees bill billed billing charge charges""".split()),
    frozenset("""time timing fast faster quick quicker quickest sooner soon
        delay delays deadline late overnight hours minutes weeks
        immediately urgent urgently""".split()),
    frozenset("""calories calorie exercise exercising fitness fit walk walks
        walking steps step burn burns burning workout cardio""".split()),
    frozenset("""free spare leisure weekend weekends holiday evening""".split()),
)
_FAMILY_OF: dict[str, int] = {w: i for i, f in enumerate(_FAMILIES) for w in f}


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower())
            if w not in _STOP and len(w) > 2]


def _related(a: str, b: str) -> bool:
    """One word engages another if they share a long prefix.

    `return`/`returning`/`returns` are the same objective; `car`/`care` are not,
    which is why the prefix floor is five characters rather than three. A plain
    plural is allowed below that floor — `demo`/`demos` must not count as two
    different things — and the concept families above close the gap between the
    words a person uses for a goal and the words an answer uses for it."""
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if long == short + "s":
        return True
    if len(short) >= PREFIX_MATCH and long.startswith(short):
        return True
    family = _FAMILY_OF.get(a)
    return family is not None and family == _FAMILY_OF.get(b)


@dataclass
class Objective:
    kind: str
    text: str
    terms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text[:90], "terms": self.terms[:6]}


@dataclass
class ObjectiveResult:
    objectives: list[Objective] = field(default_factory=list)
    unserved: list[Objective] = field(default_factory=list)
    is_choice: bool = False
    declined: bool = False

    @property
    def defeated(self) -> bool:
        return bool(self.unserved)

    @property
    def headline(self) -> Objective | None:
        """The errand first — it is the one people actually lose."""
        if not self.unserved:
            return None
        for kind in (ERRAND, SUBJECT):
            named = [o for o in self.unserved if o.kind == kind]
            if named:
                return named[0]
        return self.unserved[0]

    def as_dict(self) -> dict[str, Any]:
        return {"objectives": [o.as_dict() for o in self.objectives],
                "unserved": [o.as_dict() for o in self.unserved],
                "offersAChoice": self.is_choice,
                "answerDeclined": self.declined,
                "purposeDefeated": self.defeated}


def objectives(question: str) -> list[Objective]:
    """What the person is trying to achieve, in their own words."""
    text = question or ""
    found: list[Objective] = []
    seen: set[str] = set()

    def add(kind: str, phrase: str) -> None:
        phrase = " ".join(phrase.split()).strip(" ,.;:")
        terms = _terms(phrase)
        if not terms:
            return
        key = " ".join(sorted(terms))
        if key in seen:
            return
        seen.add(key)
        found.append(Objective(kind, phrase, terms))

    for match in _GOAL.finditer(text):
        for group in ("g", "g2", "g3", "g4", "g5"):
            value = match.groupdict().get(group)
            if value:
                add(GOAL, value)
                break

    for match in _ERRAND.finditer(text):
        add(ERRAND, match.group("e"))

    for match in _SUBJECT.finditer(text):
        add(SUBJECT, match.group("s"))

    return found[:4]


def inspect(question: str, answer: str) -> ObjectiveResult:
    """Which of the person's objectives the answer never engages with."""
    goals = objectives(question)
    result = ObjectiveResult(objectives=goals,
                             is_choice=bool(_CHOICE.search(question or "")))
    if not goals:
        return result

    if abstain.posture(answer) == abstain.FULL:
        # An assistant that declines outright has not served the objective, but
        # it has not pretended to either. Honest declines are the abstention
        # detector's business; calling them a defeated purpose here would
        # punish exactly the behaviour we want more of.
        result.declined = True
        return result

    answer_terms = _terms(answer)
    if len(answer_terms) < 4:
        # Too little answer to judge. Saying nothing beats guessing.
        return result

    for objective in goals:
        if objective.kind == SUBJECT and not result.is_choice:
            # A possessive on its own is not an objective. It becomes one when
            # the question asks the model to choose, because that is when a
            # thing the person named gets quietly traded away.
            continue
        served = any(_related(term, word)
                     for term in objective.terms for word in answer_terms)
        if not served:
            result.unserved.append(objective)
    return result


def describe(result: ObjectiveResult) -> str:
    """One sentence a person reads without decoding anything."""
    target = result.headline
    if target is None:
        return ""
    if target.kind in (ERRAND, SUBJECT):
        return (f"You asked about “{target.text}” and the answer never "
                f"comes back to it.")
    return (f"You said you wanted to “{target.text}” and the answer "
            f"does not address that.")
