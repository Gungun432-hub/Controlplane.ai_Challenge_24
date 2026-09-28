"""The ingress gate: checking the question, before the model is called.

Everything else in this system checks the *answer*. That is one of two risk
surfaces, and it is the expensive one — by the time an answer exists you have
already paid for the tokens that produced it.

A question carries its own risks, and they are different in kind:

* an instruction that tries to overwrite the system's own instructions
* personal data the user pasted, which is about to be sent to a third-party model
* a request to do something this system was never meant to do
* a request to work around a control

Every check here is **deterministic and local**. No model call, no network, no
measurable latency. That is the direct answer to the problem statement's
question about not slowing the AI down: **a question refused at ingress costs
zero tokens.** The cheapest governance is the kind that runs before generation.

None of this is a guarantee. Pattern matching catches the shapes of attacks that
have been seen before, and a novel phrasing will get through — which is exactly
why the egress gate still runs on everything that passes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Routes a question can take out of this gate.
ALLOW = "allow"
HOLD = "hold"          # a human decides before the model is ever called
REFUSE = "refuse"      # never reaches a human queue; nothing to review


@dataclass
class IngressFinding:
    check: str
    severity: str                       # high | medium | low
    matched: str                        # the phrase that fired, quoted back
    explain: str

    def as_dict(self) -> dict[str, Any]:
        return {"check": self.check, "severity": self.severity,
                "matched": self.matched, "explain": self.explain}


@dataclass
class IngressResult:
    route: str
    findings: list[IngressFinding] = field(default_factory=list)
    intent: str = "unclassified"
    intent_confidence: float = 0.0
    latency_ms: float = 0.0

    @property
    def allowed(self) -> bool:
        return self.route == ALLOW

    def as_dict(self) -> dict[str, Any]:
        return {"route": self.route, "intent": self.intent,
                "intentConfidence": round(self.intent_confidence, 3),
                "latencyMs": round(self.latency_ms, 3),
                "findings": [f.as_dict() for f in self.findings],
                "reasons": [f.explain for f in self.findings]}


# ------------------------------------------------------------- injection ---
# Shapes, not sentences. Each pattern is one recognisable manoeuvre.
_INJECTION = [
    (r"\bignore\s+(all\s+|any\s+)?(previous|prior|above|earlier|the)\s+"
     r"(instruction|instructions|rule|rules|prompt|prompts|direction)",
     "an instruction to discard the system's own instructions"),
    (r"\bdisregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|"
     r"instruction|rule|policy|guideline)",
     "an instruction to disregard the configured policy"),
    (r"\b(you\s+are\s+now|from\s+now\s+on\s+you|act\s+as|pretend\s+(to\s+be|you)|"
     r"roleplay\s+as|simulate\s+being)\b",
     "an attempt to reassign the system's role"),
    (r"\b(system\s+prompt|your\s+(instructions|prompt|rules|system\s+message)|"
     r"initial\s+prompt)\b.{0,40}\b(what|show|reveal|print|repeat|tell|reproduce|"
     r"output|give)\b",
     "a request to reveal the system's own configuration"),
    (r"\b(what|show|reveal|print|repeat|tell|reproduce|output|give)\b.{0,40}"
     r"\b(system\s+prompt|your\s+(instructions|prompt|rules|system\s+message))\b",
     "a request to reveal the system's own configuration"),
    (r"\b(developer|debug|god|admin|root|jailbreak|dan)\s+mode\b",
     "a request for a privileged mode that does not exist"),
    (r"\bwithout\s+(any\s+)?(restriction|restrictions|filter|filters|"
     r"guardrail|guardrails|limitation|limitations|censorship)\b",
     "a request to operate without controls"),
    (r"\b(do\s*not|don'?t|never)\s+(log|record|save|report|tell|mention|"
     r"flag|escalate)\b",
     "an instruction to avoid being recorded"),
    (r"\bthis\s+is\s+(a\s+)?(test|authorized|authorised|approved)\b.{0,30}"
     r"\b(so|therefore|hence)\b",
     "a claimed authorisation the system cannot verify"),
]

# --------------------------------------------------------- policy evasion ---
_EVASION = [
    (r"\b(skip|bypass|get\s+around|work\s+around|avoid|circumvent|override)\b"
     r".{0,30}\b(approval|approvals|check|checks|policy|review|sign-?off|control)\b",
     "a request to bypass an approval or control"),
    (r"\b(just|simply)\s+(approve|authorise|authorize|release|send|pay|refund|"
     r"issue)\b.{0,20}\b(it|this|them|anyway|without)\b",
     "a request to act without the required approval"),
    (r"\bsplit\b.{0,30}\b(payment|refund|transaction|amount)\b.{0,30}"
     r"\b(under|below|threshold|limit)\b",
     "a request to split a transaction under an approval threshold"),
    (r"\bbetween\s+(you\s+and\s+me|us)\b|\bkeep\s+this\s+(quiet|between|off)\b",
     "a request for the interaction to be concealed"),
]

# ------------------------------------------------------- data exfiltration ---
_EXFIL = [
    (r"\b(list|export|dump|download|send\s+me|give\s+me|show\s+me)\b.{0,25}"
     r"\b(all|every|entire|full|complete)\b.{0,25}"
     r"\b(customer|customers|user|users|employee|employees|candidate|candidates|"
     r"account|accounts|record|records|database|table)\b",
     "a bulk request for records rather than an answer to a question"),
    (r"\b(everyone|all\s+(the\s+)?(staff|people|users|customers))'?s?\b.{0,25}"
     r"\b(salary|salaries|address|addresses|phone|email|emails|number|numbers|"
     r"detail|details)\b",
     "a request for personal data about a population"),
    (r"\b(api[_\s-]?key|secret|token|password|credential|connection\s+string|"
     r"private\s+key)\b.{0,25}\b(what|show|print|give|tell|reveal|send)\b",
     "a request for a credential"),
    (r"\b(what|show|print|give|tell|reveal|send)\b.{0,25}"
     r"\b(api[_\s-]?key|secret|token|password|credential|connection\s+string|"
     r"private\s+key)\b",
     "a request for a credential"),
]

_COMPILED = {
    "injection": [(re.compile(p, re.I | re.S), why) for p, why in _INJECTION],
    "policy_evasion": [(re.compile(p, re.I | re.S), why) for p, why in _EVASION],
    "data_exfiltration": [(re.compile(p, re.I | re.S), why) for p, why in _EXFIL],
}

_SEVERITY = {"injection": "high", "policy_evasion": "high",
             "data_exfiltration": "high", "prompt_privacy": "high",
             "out_of_scope": "medium", "empty": "low", "oversized"
             : "medium"}

MAX_QUESTION_CHARS = 4000


def _quote(text: str, match: re.Match) -> str:
    start = max(0, match.start() - 10)
    end = min(len(text), match.end() + 10)
    snippet = text[start:end].strip().replace("\n", " ")
    return f"…{snippet}…" if (start or end < len(text)) else snippet


# ---------------------------------------------------------------- intent ---
# What is this prompt *for*? The mentor's framing, made mechanical: you cannot
# know a team's business logic, but you can tell a code-generation request from
# a policy question, and a system has a declared purpose it should stay inside.
_INTENTS = {
    "policy_lookup": r"\b(policy|rule|sop|procedure|guideline|allowed|permitted|"
                     r"eligib\w+|threshold|limit|approval|compliance|regulation)\b",
    "status_lookup": r"\b(status|where\s+is|track|tracking|when\s+will|delivered|"
                     r"dispatch\w*|order|ticket|refund|balance|progress)\b",
    "drafting": r"\b(draft|write|compose|reply|respond|email|message|summar\w+|"
                r"rephrase|rewrite)\b",
    # Explicit analytical verbs only. "should I" used to live here, and it is
    # how *"I need to return a product, the drop-off is two kilometres away and
    # I don't have a car — should I drive there?"* got classified as analysis,
    # found to be outside a support copilot's declared intents, and held for a
    # human. That is an ordinary customer question, and stopping it is the
    # opposite of what this product is for: the interesting thing about that
    # question is whether the ANSWER is any good, which we can only find out by
    # letting it through.
    "analysis": r"\b(compare|analyse|analyze|evaluate|assess|benchmark|"
                r"break\s+down|quantif\w+|forecast|model\s+out)\b",
    "code_generation": r"\b(code|script|function|sql|query|regex|python|java|"
                       r"bash|api\s+call|endpoint|debug)\b",
    # The verb must be used AS a verb. "how long does a refund take" is a status
    # question; "issue a refund" is a request to act. Without this the noun form
    # made every billing question look like an instruction to move money.
    "action_request": r"(?:^|(?<=[.!?]\s)|\b(?:please|kindly|can\s+you|could\s+you|"
                      r"you\s+should|go\s+ahead\s+and|now|just)\s+)"
                      r"(issue|refund|send|restart|reboot|delete|cancel|approve|"
                      r"transfer|pay|deploy|release|reset|suspend|revoke)\b",
}
_INTENT_RE = {k: re.compile(v, re.I) for k, v in _INTENTS.items()}


def classify_intent(question: str) -> tuple[str, float]:
    """Deterministic bucketing. Confidence is the share of the winning bucket's
    matches, so a question that looks like three things reports low confidence
    rather than a confident guess."""
    counts = {name: len(rx.findall(question or "")) for name, rx in _INTENT_RE.items()}
    total = sum(counts.values())
    if not total:
        return "general_question", 0.0
    # Action beats everything: a question that asks for something to be done is
    # an action request even when it is phrased as a policy query.
    if counts.get("action_request"):
        return "action_request", round(counts["action_request"] / total, 3)
    best = max(counts, key=lambda k: (counts[k], k))
    return best, round(counts[best] / total, 3)


# ------------------------------------------------------------------ gate ---
def inspect(question: str, *, system_id: str = "", allowed_intents: list[str] | None = None,
            allow_prompt_pii: bool = False) -> IngressResult:
    """Check a question. Deterministic, local, and measured in microseconds."""
    import time

    t0 = time.perf_counter()
    text = (question or "").strip()
    findings: list[IngressFinding] = []

    if not text:
        return IngressResult(REFUSE, [IngressFinding(
            "empty", "low", "", "the question is empty")],
            latency_ms=(time.perf_counter() - t0) * 1000)

    if len(text) > MAX_QUESTION_CHARS:
        findings.append(IngressFinding(
            "oversized", "medium", f"{len(text)} characters",
            f"the question is longer than the {MAX_QUESTION_CHARS} character limit; "
            f"very long prompts are a common way to bury an instruction"))

    for check, patterns in _COMPILED.items():
        for rx, why in patterns:
            m = rx.search(text)
            if m:
                findings.append(IngressFinding(check, _SEVERITY[check],
                                               _quote(text, m), why))
                break                      # one finding per check is enough to hold

    # Personal data the user pasted. It has not left the building yet — this is
    # the last point at which it can be stopped from reaching a third-party model.
    if not allow_prompt_pii:
        from .detectors import privacy
        priv = privacy(answer=text)
        if (priv.detail or {}).get("findings"):
            kinds = ", ".join(priv.detail.get("kinds", [])) or "personal identifier"
            findings.append(IngressFinding(
                "prompt_privacy", "high", kinds,
                f"the question contains a validated {kinds} in clear text, which "
                f"would be sent to the model provider as written"))

    intent, confidence = classify_intent(text)
    if allowed_intents and intent not in allowed_intents and confidence >= 0.4:
        findings.append(IngressFinding(
            "out_of_scope", "low", intent,
            f"this reads as a '{intent}' request and {system_id or 'this system'} "
            f"is registered for {', '.join(allowed_intents)}"))

    # An empty question has nothing for a human to adjudicate. Everything else
    # that fires here is held, because a false positive a reviewer can release in
    # one click is a far better failure than a silent refusal.
    #
    # With one exception, and it matters: **being outside a system's declared
    # intents is not a safety incident.** Nobody is attacking anything; at worst
    # the question is addressed to the wrong assistant, and there is a gate for
    # exactly that — the subject-scope check, which redirects by name instead of
    # queueing work for a person. Holding on intent alone filled the reviewer's
    # queue with ordinary questions and taught them to click Pass without
    # reading, which is how a review queue stops being a control.
    blocking = [f for f in findings if f.check != "out_of_scope"]
    if any(f.check == "empty" for f in findings):
        route = REFUSE
    elif blocking:
        route = HOLD
    else:
        route = ALLOW

    return IngressResult(route, findings, intent, confidence,
                         (time.perf_counter() - t0) * 1000)
