"""The request that should never have reached a model.

    "I hate my customer. How do I irritate him step by step?"

The assistant refused, and refused well. That is not the point. **By the time it
refused, we had already paid for it** — the prompt cleared ingress, went to the
provider, came back, was scored, and was then released with a warning panel. The
control plane's own promise is that the cheapest governance is the kind that runs
before you pay for anything, and here it did not run at all.

Nothing in the existing ingress covers this. Injection, policy evasion, bulk
extraction and pasted identifiers are all *attacks on the system*. This is
something else: a legitimate user, correctly authenticated, asking the company's
own assistant to help them harm somebody. It is an attack on a person, and the
vocabulary is completely different.

Six families, and they are deliberately narrow:

``harassment``      help making a named person's experience worse — irritate,
                    provoke, humiliate, intimidate, wind up, get back at.
``discrimination``  treat somebody differently on a protected attribute. The
                    hiring rubric already forbids it; this refuses to draft it.
``retaliation``     punish, sabotage or settle a score with a colleague,
                    customer or candidate.
``deception``       help mislead the person the company is serving — hide a fee,
                    talk them out of a refund they are owed, make a problem look
                    like their fault.
``stereotype``      assert something about a whole group — *"why are they all
                    so unreliable"*, *"are women worse at this"*, *"write a joke
                    about that community"*. Distinct from ``discrimination``,
                    which is about acting differently toward one person.
``abuse``           abusive language aimed at a person, whether the assistant is
                    asked to produce it (*"write an email calling him an idiot"*)
                    or it arrives in the question. Refused as a language matter,
                    not an accusation: a colleague venting after a bad call is
                    not a wrongdoer.

And one family that is not ours at all: ``blocked_term``, the words **this
organisation** decided its assistants will not process. An unreleased codename, a
customer under NDA, a term the company has already ruled on. It lives in the
registry row next to the budget, editable from the console, because a blocklist
that needs a deploy to add a word is a blocklist nobody keeps current — and no
general-purpose safety classifier could ever have known about *Project Meridian*.

What makes a check like this trustworthy is not the patterns. It is the
**exclusions**, because the questions that look most like these are the ones a
support agent asks all day:

* *"How do I avoid irritating the customer?"* — the goal is the opposite.
* *"The customer says he hates our service."* — quoting somebody else.
* *"How should I handle an angry customer who is being abusive?"* — this is the
  person asking for help, not offering harm.
* *"Why did the candidate complain about age discrimination?"* — asking about a
  complaint is not asking to discriminate.

Every one of those is in the test battery, and the check is scored on them the
same way the adjudicator is scored on its labelled set: catch rate reported next
to false-alarm rate, because for a gate on the front door the false alarm is what
gets it switched off.

This is a **refusal, not a hold.** There is nothing for a reviewer to adjudicate
and making them click Pass on it would be insulting; but unlike a wrong-assistant
redirect it *is* a governance incident, so it is recorded, counted and shown to
the owner. The person gets an immediate, useful alternative — we will help you
write a firm professional reply — because a gate that only says no teaches people
to route around it.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

HARASSMENT = "harassment"
DISCRIMINATION = "discrimination"
RETALIATION = "retaliation"
DECEPTION = "deception"
STEREOTYPE = "stereotype"
ABUSE = "abuse"
BLOCKED_TERM = "blocked_term"

# --------------------------------------------------------------- exclusions ---
# Checked FIRST. If any of these fire, the question is one of the ordinary ones
# that merely shares vocabulary with a harmful request, and we stop looking.

# "how do I avoid upsetting", "without annoying", "so I don't irritate"
_AVOIDANCE = re.compile(
    r"\b(?:avoid|prevent|stop|without|not\s+to|don'?t|do\s+not|never|"
    r"minimi[sz]e|reduce|de-?escalate|defuse)\b[^.?!]{0,40}?"
    r"\b(?:irritat\w+|annoy\w+|upset\w+|anger\w+|offend\w+|frustrat\w+|"
    r"provok\w+|humiliat\w+|antagoni[sz]\w+|discriminat\w+|bias\w*)\b", re.I)

# the same idea the other way round: "irritating the customer is something to avoid"
_AVOIDANCE_TRAILING = re.compile(
    r"\b(?:irritat\w+|annoy\w+|upset\w+|offend\w+|provok\w+|discriminat\w+)\b"
    r"[^.?!]{0,40}?\b(?:avoid|prevent|without|should\s+not|must\s+not|"
    r"is\s+wrong|is\s+prohibited|complaint|complained|allegation)\b", re.I)

# somebody else's words, or a report of an event
_REPORTED = re.compile(
    r"\bcustomer\s+(?:says|said|claims|claimed|wrote|is\s+saying|alleges)\b"
    r"|\b(?:he|she|they|the\s+\w+)\s+(?:says|said|wrote|claims|alleged)\s+"
    r"(?:that\s+)?(?:he|she|they)?\s*\b(?:hates?|hated)\b"
    r"|\b(?:complaint|complained|allegation|alleged|grievance|feedback|review)\b"
    r"|[\"“][^\"”]{10,}[\"”]", re.I)

# the person asking is the one on the receiving end
_RECEIVING = re.compile(
    r"\b(?:is\s+being|was\s+being|has\s+been)\s+(?:abusive|rude|aggressive|"
    r"threatening|hostile)\b"
    r"|\bangry\s+customer\b|\bdifficult\s+customer\b|\birate\b"
    r"|\bhow\s+(?:do|should)\s+I\s+(?:handle|deal\s+with|respond\s+to|"
    r"manage|calm|de-?escalate)\b", re.I)

# "the client was annoyed about the delay" describes a state somebody is already
# in. It is the single most common sentence in a support queue and it shares its
# only keyword with a request to put them in that state.
_STATE_REPORT = re.compile(
    r"\b(?:was|were|is|are|got|has\s+been|had\s+been|seems?|sounds?|appears?|"
    r"became|feels?|felt)\s+(?:very\s+|quite\s+|really\s+|understandably\s+|"
    r"clearly\s+|a\s+bit\s+)?"
    r"(?:annoyed|irritated|upset|angry|offended|frustrated|humiliated|"
    r"intimidated|harassed|discriminated)\b", re.I)

_EXCLUSIONS = (
    ("state_report", _STATE_REPORT,
     "the question reports how somebody already feels, rather than asking how to "
     "make them feel that way"),
    ("avoidance", _AVOIDANCE, "the question asks how to AVOID this, not how to do it"),
    ("avoidance", _AVOIDANCE_TRAILING, "the question treats this as something to avoid"),
    ("reported", _REPORTED, "the question reports somebody else's words or a complaint"),
    ("receiving", _RECEIVING, "the person asking is the one being treated badly"),
)

# ------------------------------------------------------------------ targets ---
# Harm needs somebody to land on. Without a target this is abstract and we say
# nothing — "irritating design choices" is not a request to hurt anyone.
_TARGET = re.compile(
    r"\b(?:my|the|this|that|a|our)\s+(?:customer|client|user|candidate|applicant|"
    r"colleague|coworker|co-?worker|employee|manager|supplier|vendor|tenant|"
    r"patient|student|subscriber|member|guy|woman|man|person|team\s?mate)s?\b"
    r"|\b(?:him|her|them|his|their|this\s+person|that\s+person|"
    r"the\s+complainant)\b", re.I)

# -------------------------------------------------------------- the families ---
_HARASSMENT = re.compile(
    # \w* not \w+ — the bare verb has no suffix, and "how can I annoy this
    # client" is the exact sentence this check exists for.
    r"\b(?:irritat\w*|annoy\w*|provok\w*|wind\s+(?:him|her|them)\s+up|"
    r"humiliat\w*|embarrass\w*|belittl\w*|demean\w*|intimidat\w*|"
    r"antagoni[sz]\w*|harass\w*|troll\w*|bully\w*|torment\w*|"
    r"make\s+(?:his|her|their|the\s+\w+'?s?)\s+life\s+(?:hell|difficult|hard)|"
    r"ruin\s+(?:his|her|their)\s+day|get\s+under\s+(?:his|her|their)\s+skin|"
    r"mess\s+with|string\s+(?:him|her|them|(?:the|this|my|our)\s+\w+)\s+along|"
    r"waste\s+(?:his|her|their)\s+time|drag\s+(?:this|it)\s+out)\b", re.I)

# A stated animus toward a person the asker works with.
#
# This used to fire only alongside a request for a method — the reasoning being
# that hatred on its own is not a request for anything, and refusing somebody for
# saying how they feel is heavy-handed. Watching it on screen changed our mind.
# *"I hate my colleague"* reached the model, came back with a sympathetic
# paragraph, and was then priced as an unverifiable claim — which is three wrong
# answers in a row: we paid for it, a workplace assistant became a venting
# channel about a named person, and the governance verdict was about citations.
#
# It is now a finding on its own, at **medium** severity, and the refusal says so
# plainly rather than treating the person as a wrongdoer. What it offers instead
# is the thing that actually helps: write it down factually, or draft something
# professional. Reporting somebody else's words is still excluded, as ever.
_HATE_STATEMENT = re.compile(
    r"\bI\s+(?:hate|despise|can'?t\s+stand|can\s?not\s+stand|loathe|detest)\s+"
    r"(?:my|the|this|that)\s+"
    r"(?:person\s+)?(?:\w+\s+){0,2}?"
    r"(?:customer|client|candidate|colleague|co-?worker|coworker|manager|boss|"
    r"user|employee|teammate|team\s?mate|supervisor|subordinate|reportee|"
    r"vendor|supplier|tenant|guy|woman|man|person)\b",
    re.I)

_DISCRIMINATION = re.compile(
    r"\b(?:rank|score|rate|mark|grade|place|sort|filter|screen|shortlist|"
    r"prioriti[sz]e|deprioriti[sz]e|reject|exclude|pass\s+over|weed\s+out)\b"
    r"[^.?!]{0,60}?\b(?:because|due\s+to|based\s+on|on\s+account\s+of|since|"
    r"as\s+(?:he|she|they)\s+(?:is|are))\b[^.?!]{0,50}?"
    r"\b(?:age|older|younger|disab\w+|handicap\w+|gender|sex|male|female|"
    r"woman|women|man|men|pregnan\w+|marital|caste|religion|religious|muslim|"
    r"hindu|christian|sikh|race|racial|ethnic\w*|nationality|foreign\w*|"
    r"accent|postcode|pincode|locality|neighbourhood|neighborhood|"
    r"orientation|gay|lesbian|transgender)\b"
    # and the short form: "should I rank this candidate lower, he is older"
    r"|\b(?:rank|score|rate|place|put|sort)\s+(?:\w+\s+){1,3}?"
    r"(?:lower|down|last|below|behind|at\s+the\s+bottom)\b",
    re.I)

_PROTECTED = re.compile(
    r"\b(?:age|older|younger|disab\w*|handicap\w*|gender|sex|male|female|"
    r"pregnan\w*|marital|caste|dalit|religion|religious|muslim|hindu|christian|"
    r"sikh|jewish|buddhist|race|racial|ethnic\w*|nationality|foreign\w*|accent|"
    r"orientation|gay|lesbian|transgender)\b", re.I)

_RETALIATION = re.compile(
    r"\b(?:get\s+back\s+at|get\s+even|revenge|retaliat\w*|punish|"
    r"teach\s+(?:him|her|them|(?:this|the|my|our)\s+\w+)\s+a\s+lesson|"
    r"make\s+(?:him|her|them)\s+(?:pay|suffer|regret)|"
    r"sabotage|settle\s+(?:a\s+)?score|pay\s+(?:him|her|them)\s+back)\b", re.I)

_DECEPTION = re.compile(
    r"\b(?:mislead|deceive|trick|fool|dupe|con)\b[^.?!]{0,30}?"
    r"\b(?:customer|client|candidate|user|him|her|them)\b"
    r"|\b(?:hide|conceal|bury|obscure|downplay)\b[^.?!]{0,40}?"
    r"\b(?:fee|charge|cost|penalty|term|condition|clause|refund|right|"
    r"entitlement)s?\b"
    r"|\btalk\s+(?:him|her|them|the\s+customer)\s+out\s+of\b"
    r"|\bmake\s+it\s+(?:look|seem|sound)\s+like\b[^.?!]{0,50}?"
    r"\b(?:fault|problem|mistake|error)\b", re.I)


# ------------------------------------------------------- bias / stereotype ---
# Different from `discrimination` above, which is about *acting* differently
# toward one person. This is about asking the assistant to assert something
# about a whole group — and it is the request that most often arrives looking
# innocent, as a joke, a "is it true that", or an idle why-are-they-all.
_GROUP = re.compile(
    r"\b(?:women|men|girls|boys|muslims?|hindus?|christians?|sikhs?|jews?|"
    r"buddhists?|dalits?|brahmins?|bengalis?|biharis?|marathis?|tamils?|"
    r"gujaratis?|punjabis?|malayalis?|north\s+indians?|south\s+indians?|"
    r"africans?|chinese|indians?|pakistanis?|americans?|nigerians?|"
    r"immigrants?|foreigners?|refugees?|"
    r"(?:old|older|elderly|young|younger|disabled|pregnant|gay|lesbian|trans|"
    r"transgender|lower[\s-]caste|upper[\s-]caste)\s+(?:people|employees|"
    r"candidates?|workers?|staff|women|men)|"
    r"people\s+(?:from|of)\s+(?:that\s+)?(?:\w+\s+){0,2}?"
    r"(?:community|caste|religion|region|state|country|background)|"
    r"(?:that|this|their|those|the)\s+(?:\w+\s+){0,1}?"
    r"(?:community|communities|caste|castes|religion|religions|tribe|tribes|"
    r"ethnicity|nationality|lot|crowd))\b", re.I)

_STEREOTYPE = re.compile(
    # "why are women so bad at", "why do biharis always"
    r"\bwhy\s+(?:are|do|is|does)\b[^.?!]{0,40}?"
    r"\b(?:so|always|never|all|generally|usually|naturally|inherently)\b"
    # "are muslims more likely to default", "do women take more leave"
    r"|\b(?:are|do|is|does|aren'?t|don'?t)\b[^.?!]{0,30}?"
    r"\b(?:more|less)\s+likely\s+to\b"
    # "are women worse at maths", "do older people learn slower"
    r"|\b(?:are|do|can|should)\b[^.?!]{0,30}?"
    r"\b(?:less|more|worse|better|inferior|superior|slower|faster|"
    r"naturally|inherently|genetically)\b[^.?!]{0,30}?"
    r"\b(?:than|at|in|when\s+it\s+comes)\b"
    # a flat generalisation stated as fact
    r"|\b(?:are|is)\s+(?:all\s+|mostly\s+|generally\s+|usually\s+|just\s+)?"
    r"(?:lazy|dishonest|corrupt|stupid|dirty|criminal|violent|greedy|aggressive|"
    r"unreliable|untrustworthy|backward|primitive|emotional|hysterical|"
    r"incompetent|cheap|loud|rude)\b"
    # asked for outright
    r"|\b(?:joke|jokes|meme|memes|stereotype|stereotypes|generali[sz]ation)\b"
    r"|\b(?:make\s+fun\s+of|poke\s+fun\s+at|mock)\b", re.I)

# ---------------------------------------------------- abusive language -------
# Two shapes: asking the assistant to *produce* abuse, and abuse of a person in
# the question itself. Both are refused before the model, but the second is
# refused as a language matter rather than an accusation — a colleague venting
# after a bad call is not a wrongdoer, and treating them as one is the fastest
# way to lose the room.
_SLUR = (r"f+u+c+k\w*|sh[i1]t+\w*|bastard\w*|assh[o0]le\w*|arsehole\w*|"
         r"b[i1]tch\w*|dickhead\w*|prick\w*|cunt\w*|motherf\w+|"
         r"wanker\w*|bugger\w*|piss\s+off|screw\s+(?:him|her|them|you)")
_INSULT = (r"idiot\w*|moron\w*|imbecile\w*|stupid|dumb|brainless|"
           r"incompetent|useless|pathetic|loser\w*|clown\w*|worthless|"
           r"jerk\w*|scum\w*|nutcase|halfwit")
_ADDRESSEE = (r"him|her|them|you|the\s+customer|the\s+client|the\s+candidate|"
              r"the\s+vendor|the\s+supplier|my\s+\w+|this\s+\w+")

_ABUSE = re.compile(
    # "write an email calling him an idiot", "tell them to fuck off"
    rf"\b(?:call|calling|called|tell|telling|say\s+to|write)\b[^.?!]{{0,40}}?"
    rf"\b(?:{_INSULT}|{_SLUR})\b"
    # "my customer is an idiot", "he is completely useless"
    rf"|\b(?:he|she|they|this|that|the|my|our)\s+(?:\w+\s+){{0,2}}?"
    rf"(?:is|are|'s|was|were)\s+"
    rf"(?:a\s+|an\s+|such\s+a\s+|so\s+|totally\s+|completely\s+|"
    rf"absolutely\s+|bloody\s+)*(?:{_INSULT})\b"
    # profanity landing on a person, either order
    rf"|\b(?:{_SLUR})\b[^.?!]{{0,25}}?\b(?:{_ADDRESSEE})\b"
    rf"|\b(?:{_ADDRESSEE})\b[^.?!]{{0,15}}?\b(?:{_SLUR})\b"
    # said straight to somebody's face: "you moron", "you are an absolute idiot"
    rf"|\byou\s+(?:are\s+|'?re\s+)?(?:an?\s+|such\s+an?\s+)?"
    rf"(?:absolute\s+|complete\s+|total\s+|bloody\s+|utter\s+)?"
    rf"(?:{_INSULT})\b", re.I)

# Abuse carries its own target when it is said in the second person. This is
# scoped to `abuse` alone and deliberately not added to `_TARGET`: putting "you"
# in the general target list would mean almost every question has a target,
# which would gut the guard that keeps `harassment` and `retaliation` quiet.
_FAMILY_TARGET = {ABUSE: re.compile(r"\byou\b", re.I)}
_NEVER = re.compile(r"(?!x)x")

# Asking about a policy, the law, training or a complaint is not asking for the
# thing. This exclusion is scoped to the two new families only: it must never
# excuse *"our policy is to rank older candidates lower"*, which is the sentence
# `discrimination` exists for.
_POLICY_CONTEXT = re.compile(
    r"\b(?:policy|policies|law|legal|legislation|act|rubric|guideline|guidance|"
    r"compliance|handbook|code\s+of\s+conduct|training|awareness|prevent\w*|"
    r"anti-?bias|anti-?discrimination|unconscious\s+bias|report\w*|escalat\w*|"
    r"grievance|investigat\w*|audit|posh|prohibited|forbidden|not\s+allowed|"
    r"is\s+it\s+ok(?:ay)?\s+to)\b", re.I)

_FAMILIES: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    (HARASSMENT, _HARASSMENT, "high",
     "a request for help making a specific person's experience worse"),
    (DISCRIMINATION, _DISCRIMINATION, "high",
     "a request to treat someone differently because of a protected characteristic"),
    (RETALIATION, _RETALIATION, "high",
     "a request for help retaliating against a specific person"),
    (DECEPTION, _DECEPTION, "high",
     "a request for help misleading the person this company is serving"),
    (STEREOTYPE, _STEREOTYPE, "high",
     "a request for a generalisation about a group of people"),
    (ABUSE, _ABUSE, "medium",
     "abusive language aimed at a person"),
    (HARASSMENT, _HATE_STATEMENT, "medium",
     "a statement of hostility toward a specific person the asker works with"),
)

# Families that do not need a named target, and why.
_NO_TARGET_NEEDED = frozenset({
    DISCRIMINATION,   # naming a protected attribute as a reason is harmful alone
    STEREOTYPE,       # the target is the group, which is named by _GROUP instead
})

# Families the policy/law/training exclusion applies to.
_POLICY_EXCUSABLE = frozenset({STEREOTYPE, ABUSE})

# What we offer instead. A gate that only says no teaches people to route around
# it; every refusal here names something the assistant will still happily do.
ALTERNATIVES = {
    HARASSMENT: "I can help you write a firm, professional reply that holds your "
                "position without giving anything away \u2014 or, if this is about a "
                "colleague, help you set down what happened factually so you can "
                "raise it with someone who can act on it.",
    DISCRIMINATION: "I can score this candidate against the published rubric — "
                    "experience, demonstrated skills, progression and communication.",
    RETALIATION: "I can help you document what happened factually and raise it "
                 "through the proper channel.",
    DECEPTION: "I can help you explain the charge accurately, including what the "
               "customer is entitled to.",
    STEREOTYPE: "I can give you what the evidence actually shows on this, or help "
                "you write it in terms of the individual rather than the group.",
    ABUSE: "I can write the same message in language you would be comfortable "
           "having read back to you in a meeting.",
    BLOCKED_TERM: "I can help with the same request without that term.",
}


@dataclass
class HarmFinding:
    family: str
    severity: str
    matched: str
    explain: str

    def as_dict(self) -> dict[str, Any]:
        return {"family": self.family, "severity": self.severity,
                "matched": self.matched[:90], "explain": self.explain}


@dataclass
class HarmResult:
    refuse: bool
    findings: list[HarmFinding] = field(default_factory=list)
    excluded_by: str = ""
    latency_ms: float = 0.0

    @property
    def family(self) -> str:
        return self.findings[0].family if self.findings else ""

    @property
    def alternative(self) -> str:
        return ALTERNATIVES.get(self.family, "")

    def as_dict(self) -> dict[str, Any]:
        return {"refuse": self.refuse, "family": self.family,
                "findings": [f.as_dict() for f in self.findings],
                "excludedBy": self.excluded_by,
                "alternative": self.alternative,
                "latencyMs": round(self.latency_ms, 3)}


def blocklist_hits(text: str, terms: list[str] | None) -> list[str]:
    """Terms this organisation has decided its assistants will not process.

    Configured, never compiled in: a blocklist is a business decision that
    changes on a Tuesday, and a control that needs a code change to add a word
    is a control nobody uses. Whole-word and case-insensitive, so `bar` does not
    fire on `barcode`."""
    found = []
    for term in terms or []:
        term = (term or "").strip()
        if len(term) < 3:
            continue
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I):
            found.append(term)
    return found[:4]


def inspect(question: str, blocklist: list[str] | None = None) -> HarmResult:
    """Deterministic, local, sub-millisecond, and it runs before the model.

    Exclusions first, always. The cost of a false positive here is a support
    agent being told their ordinary question is abusive, which is the fastest
    way to get a safety control switched off."""
    started = time.perf_counter()
    text = question or ""

    # The organisation's own blocklist is checked before anything else and is
    # never excused. The exclusions below exist to stop *our* patterns firing on
    # ordinary questions; they have no business overriding a word the company
    # itself decided will not be sent to a third-party model.
    banned = blocklist_hits(text, blocklist)
    if banned:
        return HarmResult(True, [HarmFinding(
            BLOCKED_TERM, "high", term,
            f"the question contains \u201c{term}\u201d, which this organisation has "
            f"put on its own blocklist for this assistant") for term in banned],
            latency_ms=(time.perf_counter() - started) * 1000)

    for name, pattern, why in _EXCLUSIONS:
        if pattern.search(text):
            return HarmResult(False, excluded_by=f"{name}: {why}",
                              latency_ms=(time.perf_counter() - started) * 1000)

    has_target = bool(_TARGET.search(text))
    has_group = bool(_GROUP.search(text))
    policy_question = bool(_POLICY_CONTEXT.search(text))
    findings: list[HarmFinding] = []

    for family, pattern, severity, explain in _FAMILIES:
        match = pattern.search(text)
        if not match:
            continue
        # Harm needs somebody to land on. Two families are exempt for reasons
        # given at `_NO_TARGET_NEEDED`.
        if (not has_target and family not in _NO_TARGET_NEEDED
                and not _FAMILY_TARGET.get(family, _NEVER).search(text)):
            continue
        if family == DISCRIMINATION and not _PROTECTED.search(text):
            continue
        if family == STEREOTYPE and not has_group:
            # "write a joke" is fine. "write a joke about that community" is not.
            continue
        if family in _POLICY_EXCUSABLE and policy_question:
            # Asking what the policy is, how to report it, or how training
            # covers it, is the opposite of asking for the thing.
            continue
        findings.append(HarmFinding(family, severity,
                                    " ".join(match.group(0).split())[:90], explain))

    # Next to a request for a method, the stated animus is the whole picture and
    # it is what makes the refusal explicable. On its own it is still a finding —
    # see `_HATE_STATEMENT` — but a milder one, so the richer explanation is
    # promoted to the front only when a method was asked for too.
    hate = _HATE_STATEMENT.search(text)
    if hate and any(f.severity == "high" for f in findings):
        findings = [f for f in findings if f.matched != " ".join(hate.group(0).split())]
        findings.insert(0, HarmFinding(
            HARASSMENT, "high",
            " ".join(hate.group(0).split())[:90],
            "the question opens by stating hostility toward a specific person"))

    return HarmResult(bool(findings), findings,
                      latency_ms=(time.perf_counter() - started) * 1000)


def message(result: HarmResult, system_name: str = "This assistant") -> str:
    """What the person reads. Plain, not preachy, and it offers a way forward."""
    if not result.refuse:
        return ""
    first = result.findings[0]
    return (f"{system_name} will not help with this. It reads as "
            f"{first.explain}, and that is refused before the question reaches "
            f"the model — so nothing was generated and nothing was spent. "
            f"{result.alternative}")

# ------------------------------------------------ the answer side of this ---
# The same vocabulary, pointed the other way. Everything above runs before the
# model; this runs after it, on what the model produced, because a control plane
# that screens the question and then releases an abusive answer has governed the
# wrong end of the call.
#
# Three families carry over. `discrimination`, `retaliation` and `deception` do
# not: they describe *requests* for a course of action, and their patterns fire
# on answers that are correctly explaining a policy — an answer that says "we do
# not hide fees" should not be scored as hiding fees.
TOXIC_ANSWER = "toxic_answer"
_ANSWER_FAMILIES = frozenset({HARASSMENT, ABUSE, STEREOTYPE})


def screen_answer(answer: str) -> HarmResult:
    """Did the model produce something we should not hand to a person?"""
    result = inspect(answer or "")
    keep = [f for f in result.findings if f.family in _ANSWER_FAMILIES]
    return HarmResult(bool(keep), keep, excluded_by=result.excluded_by,
                      latency_ms=result.latency_ms)


def toxicity(answer: str = "", **_: Any) -> "DetectorResult":
    """A mandatory check, and the one finding in this system that withholds text.

    Everything else here escalates: a flagged answer is released with the finding
    attached, because a warned reader is better served than a blocked one. Not
    this. An answer that insults the person it is addressed to, or generalises
    about a group, has no version worth releasing with a warning panel — so the
    score is high enough to block on every profile and the released text is
    empty by construction (see `gate.decision`)."""
    from .detectors import DetectorResult

    if not (answer or "").strip():
        return DetectorResult("toxicity", score=0.0, confidence=0.4,
                              requirement="mandatory",
                              evidence=["no answer text to screen"],
                              detail={"toxicAnswer": False})
    r = screen_answer(answer)
    if not r.refuse:
        return DetectorResult(
            "toxicity", score=0.0, confidence=0.7, requirement="mandatory",
            evidence=["the answer contains no abusive language, no generalisation "
                      "about a group, and nothing aimed at making a person's "
                      "experience worse"],
            detail={"toxicAnswer": False, "excludedBy": r.excluded_by,
                    "latencyMs": round(r.latency_ms, 3)})
    first = r.findings[0]
    return DetectorResult(
        "toxicity", score=0.95, confidence=0.8, requirement="mandatory",
        labels=[TOXIC_ANSWER, first.family],
        evidence=[f"the answer itself contains {first.explain} "
                  f"(\u201c{first.matched}\u201d) — this is not a finding to release "
                  f"with a warning, so nothing is released"],
        detail={"toxicAnswer": True, **r.as_dict()})
