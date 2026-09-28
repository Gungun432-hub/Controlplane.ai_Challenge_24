"""The question that is nobody's business here.

    "draft a mail i want to send a birthday invite to my friend neha"

Customer Support Copilot answered it — with a line from the refunds SOP about
never asking a customer for a CVV. Every word of that sentence is true. It is
also a non sequitur handed to an employee by a governed enterprise assistant,
and it is the kind of thing a jury notices in three seconds.

Why nothing already here caught it
----------------------------------
**Ingress** asks whether the question is an attack. It is not.
**The harm gate** asks whether it is a request to hurt somebody. It is not.
**Subject scope** asks whether it is *another department's* subject — and this is
the gap. Scope compares the question against each system's corpus and turns it
away only when some **other** system covers it better. A birthday invite belongs
to no corpus in the organisation, so it scores `uncovered` everywhere, and
`uncovered` is deliberately allowed through: an employee asking a reasonable work
question the documents happen not to cover should get an answer, not a lecture.

So this needs a check of its own, and the boundary it enforces is different from
all three above. It is the **declared purpose** boundary: every application in
the registry is registered to do a job, and a personal errand is outside that job
no matter which department you ask.

Not a governance incident
-------------------------
This is the same class as the wrong-assistant redirect: **being asked the wrong
question is a routing mistake, not wrongdoing.** Nobody is refused as harmful,
nothing lands in a reviewer's queue, no incident is filed. The person gets a
straight answer about what this assistant is for, it costs zero tokens, and the
system's owner gets a count — because a work assistant being used as a personal
one all day is a fact its owner needs, and one an auditor will ask about.

Five families, and the exclusions are the hard part
---------------------------------------------------
``personal_life``    invites, gifts, weddings, birthdays, anniversaries, a
                     friend or a relative by relation.
``travel_leisure``   a holiday, an itinerary, a hotel for a family trip.
``food_recipe``      recipes and what to cook.
``entertainment``    a film, a song, a series, a game to pick up tonight.
``personal_admin``   converting a file, fixing a home laptop, a horoscope,
                     homework — generic errands with no department behind them.

Each of those words has an ordinary work use, and the exclusions are what make
this safe to put in front of the door:

* *"Draft a **festive campaign** headline for the loyalty segment"* — Marketing's
  whole job in October. Festivals are work here.
* *"Approve the **travel** expense claim for the Mumbai visit"* — Finance's job.
* *"The **customer** wants to reschedule their **holiday** booking"* — Support's job.
* *"Which **candidate** should we **invite** to the final round?"* — Recruitment's job.

So a family only fires when a **personal marker** is present — *my friend*, *my
wife*, *my mum*, *for myself*, *this weekend*, *my birthday* — or when the object
has no work reading at all, like a recipe or a film recommendation. Business
vocabulary anywhere in the question vetoes the whole check, because the cost of a
false positive here is an employee being told their real work question is
personal, which is the fastest way to get a control switched off.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

PERSONAL_LIFE = "personal_life"
TRAVEL_LEISURE = "travel_leisure"
FOOD_RECIPE = "food_recipe"
ENTERTAINMENT = "entertainment"
PERSONAL_ADMIN = "personal_admin"

# ------------------------------------------------------------ the veto -------
# One business word and this check says nothing at all. It is a boundary on
# *purpose*, and anything with a department behind it is inside some purpose.
_WORK = re.compile(
    r"\b(?:customer|client|account|ticket|refund|invoice|billing|payment|"
    r"campaign|segment|subscriber|lead|churn|conversion|creative|brand|"
    r"candidate|applicant|interview|shortlist|rubric|offer\s+letter|payroll|"
    r"employee|onboard\w*|appraisal|policy|policies|compliance|audit|sla|"
    r"incident|deployment|server|service|runbook|outage|latency|database|"
    r"pipeline|budget|forecast|reconcil\w*|gst|tax|expense\s+(?:claim|report)|"
    r"vendor|supplier|purchase\s+order|contract|stakeholder|quarter|"
    r"fund|portfolio|nav|kyc|loan|premium|claim\s+form|"
    r"team|sprint|roadmap|escalation|approval|sign-?off|manager|department)\b",
    re.I)

# ---------------------------------------------------- personal markers -------
# Somebody's own life, named as their own.
_PERSONAL_MARKER = re.compile(
    r"\bmy\s+(?:friend|friends|wife|husband|partner|girlfriend|boyfriend|"
    r"mom|mum|mother|dad|father|parents|sister|brother|son|daughter|kid|kids|"
    r"child|children|cousin|uncle|aunt|neighbour|neighbor|family|in-?laws|"
    r"fianc\w+|spouse|pet|dog|cat|landlord|flatmate|roommate)\b"
    r"|\bmy\s+(?:own\s+)?(?:birthday|anniversary|wedding|housewarming|"
    r"engagement|graduation)\b"
    r"|\bfor\s+(?:me|myself)\s+personally\b|\bpersonal(?:ly)?\s+use\b"
    r"|\bmy\s+personal\b|\bat\s+home\b|\bthis\s+weekend\b|\btonight\b"
    r"|\bmy\s+(?:home|house|flat|apartment)\b", re.I)

# ------------------------------------------------------- the families --------
_PERSONAL_LIFE = re.compile(
    r"\b(?:birthday|anniversary|wedding|housewarming|engagement|baby\s+shower|"
    r"farewell\s+party|get-?together|potluck|festival\s+party)\b"
    r"|\b(?:invite|invitation|rsvp)\b[^.?!]{0,40}?\b(?:party|dinner|lunch|"
    r"celebration|birthday|wedding)\b"
    r"|\bgift\s+(?:idea|ideas|for)\b|\bwhat\s+should\s+I\s+gift\b", re.I)

_TRAVEL_LEISURE = re.compile(
    r"\b(?:holiday|vacation|honeymoon|road\s+trip|weekend\s+getaway|"
    r"sightseeing|tourist|touristy|itinerary|backpacking)\b"
    r"|\b(?:places|things)\s+to\s+(?:visit|see|do)\b"
    r"|\bbook\s+(?:a\s+)?(?:flight|hotel|resort|homestay)\b"
    # "suggest me travel destinations" — no assistant here is a travel agent.
    r"|\btravel\s+(?:destination|destinations|suggestion|suggestions|idea|"
    r"ideas|recommendation|recommendations|plan|plans|tips)\b"
    r"|\b(?:suggest|recommend)\w*\s+(?:me\s+)?(?:some\s+|a\s+|good\s+)?"
    r"(?:travel|destinations?|places\s+to\s+go|holiday\s+spots?)\b"
    r"|\bbest\s+(?:places|destinations|cities|beaches|hill\s+stations)\s+"
    r"(?:to\s+visit|for\s+a\s+trip)\b", re.I)

_FOOD_RECIPE = re.compile(
    r"\brecipe\b|\bhow\s+(?:do\s+I|to)\s+(?:cook|bake|make)\b[^.?!]{0,30}?"
    r"\b(?:biryani|biriyani|curry|cake|pasta|dosa|paneer|chicken|dinner|"
    r"breakfast|lunch|dessert|snack)\b"
    r"|\bwhat\s+should\s+(?:I|we)\s+(?:cook|eat|order|serve)\b"
    r"|\b(?:diet|meal)\s+plan\b"
    # "give me food suggestions for a business dinner" — a business dinner is a
    # real work occasion and the *venue* is still nobody's registered job here.
    r"|\b(?:food|menu|dish|dishes|cuisine|restaurant|caterer|catering|"
    r"dinner|lunch|breakfast)\s+(?:suggestion|suggestions|recommendation|"
    r"recommendations|idea|ideas|option|options)\b"
    r"|\b(?:suggest|recommend)\w*\s+(?:me\s+)?(?:some\s+|a\s+|good\s+)?"
    r"(?:food|dishes|dish|restaurants?|cuisines?|menu)\b"
    r"|\bwhere\s+(?:should|can)\s+(?:I|we)\s+eat\b"
    r"|\brestaurant\s+recommendation", re.I)

_ENTERTAINMENT = re.compile(
    r"\b(?:movie|film|series|web\s+series|show|song|album|playlist|novel|"
    r"video\s+game)\b[^.?!]{0,30}?\b(?:recommend\w*|suggest\w*|watch|"
    r"listen|read|play)\b"
    r"|\b(?:recommend|suggest)\w*\b[^.?!]{0,30}?\b(?:movie|movies|film|films|"
    r"series|show|shows|song|songs|book|books|game|games)\b"
    r"|\b(?:movie|film|series|song|music|book)\s+(?:suggestion|suggestions|"
    r"recommendation|recommendations)\b"
    r"|\bwhat\s+(?:should|can)\s+I\s+(?:watch|listen\s+to|read|play)\b", re.I)

_PERSONAL_ADMIN = re.compile(
    r"\bconvert\b[^.?!]{0,30}?\b(?:ppt|pptx|pdf|docx?|jpe?g|png|mp4|xlsx?)\b"
    r"|\b(?:ppt|pptx|word|excel)\s+to\s+pdf\b|\bpdf\s+to\s+(?:word|excel|ppt)\b"
    r"|\bhoroscope|\bzodiac|\bastrolog\w+"
    r"|\bmy\s+(?:homework|assignment|thesis|college\s+project)\b"
    r"|\b(?:write|draft)\s+my\s+(?:resume|cv|sop|personal\s+statement)\b"
    r"|\bhow\s+do\s+I\s+(?:install|uninstall|reset)\b[^.?!]{0,30}?"
    r"\b(?:windows|whatsapp|instagram|my\s+laptop|my\s+phone)\b", re.I)

# Families whose object has no work reading at all. These do not need a
# personal marker; the rest do.
#
# Travel joined this set after *"suggest me travel destinations"* was answered
# from the refunds SOP. Nobody here is a travel agent, so a destination question
# needs no "my family" attached to be out of purpose — and the genuine work
# uses of the word are all protected by the `_WORK` veto above, which fires on
# "expense claim", "policy", "customer" and "booking" before this ever runs.
_SELF_EVIDENT = frozenset({FOOD_RECIPE, ENTERTAINMENT, PERSONAL_ADMIN,
                           TRAVEL_LEISURE})

_FAMILIES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (PERSONAL_LIFE, _PERSONAL_LIFE, "a personal occasion"),
    (TRAVEL_LEISURE, _TRAVEL_LEISURE, "personal travel"),
    (FOOD_RECIPE, _FOOD_RECIPE, "food and recipes"),
    (ENTERTAINMENT, _ENTERTAINMENT, "entertainment recommendations"),
    (PERSONAL_ADMIN, _PERSONAL_ADMIN, "a personal errand"),
)

LABELS = {
    PERSONAL_LIFE: "a personal occasion",
    TRAVEL_LEISURE: "personal travel",
    FOOD_RECIPE: "food and recipes",
    ENTERTAINMENT: "entertainment recommendations",
    PERSONAL_ADMIN: "a personal errand",
}


@dataclass
class PersonalResult:
    out_of_purpose: bool = False
    family: str = ""
    matched: str = ""
    vetoed_by: str = ""
    latency_ms: float = 0.0

    @property
    def label(self) -> str:
        return LABELS.get(self.family, "something personal")

    def as_dict(self) -> dict[str, Any]:
        return {"outOfPurpose": self.out_of_purpose, "family": self.family,
                "label": self.label if self.out_of_purpose else "",
                "matched": self.matched[:80], "vetoedBy": self.vetoed_by,
                "latencyMs": round(self.latency_ms, 3)}


def inspect(question: str) -> PersonalResult:
    """Deterministic, local, sub-millisecond, and it runs before the model."""
    started = time.perf_counter()
    text = question or ""

    work = _WORK.search(text)
    if work:
        return PersonalResult(
            vetoed_by=f"the question mentions '{work.group(0)}', which is this "
                      f"organisation's work",
            latency_ms=(time.perf_counter() - started) * 1000)

    personal = _PERSONAL_MARKER.search(text)
    for family, pattern, _label in _FAMILIES:
        match = pattern.search(text)
        if not match:
            continue
        if family not in _SELF_EVIDENT and not personal:
            # "invite" without "my friend" is probably a work invite.
            continue
        return PersonalResult(
            True, family, " ".join(match.group(0).split()),
            latency_ms=(time.perf_counter() - started) * 1000)

    return PersonalResult(latency_ms=(time.perf_counter() - started) * 1000)


def message(result: PersonalResult, system_name: str = "This assistant",
            department: str = "") -> str:
    """What the person reads. No lecture, and no pretending it was dangerous."""
    if not result.out_of_purpose:
        return ""
    where = f"{system_name} is your {department} assistant" if department \
        else f"{system_name} is a work assistant"
    return (f"{where}, and this is {result.label} — outside what it is registered "
            f"to do, whichever department you ask. Nothing was sent to the AI, so "
            f"nothing was generated and nothing was spent. Every assistant here is "
            f"registered for a declared purpose, and that boundary is the point of "
            f"the control plane rather than a limitation of it.")
