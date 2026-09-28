"""The verdict in language the person who asked can read.

The correction that produced this file, in our own team lead's words:

> *"the answer or evaluation in the user AI with the answer from the controlplane
> has to be in simpler language so the users can also understand."*

He was right, and it was not a cosmetic complaint. The user page was showing a
colleague in Finance sentences like *"risk price 48, evidence tier parametric,
grounding: 2 of 3 claims unsourced, mandatory verification pending"*. Every word
of that is accurate. None of it tells Priya whether she can send the email.

So there are two registers now, and this module owns the first one:

**The verdict.** One sentence saying what happened, one or two saying why, and —
where there is one — the single thing to do about it. No scores, no tier names, no
detector names, no percentages. It is written for somebody who has never heard of
this system and is not going to read a second paragraph.

**The detail**, behind a toggle, unchanged: findings, evidence grade, the second
opinion, the price, the receipt id. Auditors, owners and jury members want that,
and hiding it would be its own kind of dishonesty.

Why this is computed here in Python and not in the page's JavaScript: three
surfaces render a verdict — the user page, the reviewer queue and the owner's
briefing — and when the wording lived in each of them they drifted. A reviewer
read "held for review" while the person who asked read "released with a warning",
about the same decision. One function, one wording, everywhere.

Rules this file keeps to, because they are the ones that were broken before:

* It never says an answer was verified when the check did not run.
* It never says "no sources were found" when sources were found and not cited.
* It never shows the person text that was not cleared for them.
* It describes what was done, not how sure a model was.
"""
from __future__ import annotations

from typing import Any

# Detector ids are engineering vocabulary. These are the words a colleague uses.
FRIENDLY = {
    "grounding": "whether the figures in the answer are actually in your documents",
    "privacy": "whether personal details were exposed",
    "fairness": "whether the answer treats people even-handedly",
    "cost": "how much this question cost to answer",
    "purpose": "whether the answer covers what you actually asked",
    "certainty": "whether the answer sounds more certain than the evidence allows",
    "toxicity": "whether the answer's language is acceptable to send",
    "abstention": "whether the assistant was honest about what it cannot do",
    "adjudication": "a second model's read of the same answer",
    "citation": "whether the answer points at the documents it used",
}

# The harm gate's own explanations are written for a receipt. These are written
# for the person who just had their question refused, which is a different job:
# say what it read as, do not lecture, and hand them something they can do.
_HARM_BECAUSE = {
    "harassment": "It reads as asking for help making one person's experience worse.",
    "discrimination": "It reads as asking to treat somebody differently because of "
                      "who they are.",
    "retaliation": "It reads as asking for help getting back at somebody.",
    "deception": "It reads as asking for help misleading the person we are serving.",
    "stereotype": "It asks for a generalisation about a whole group of people.",
    "abuse": "The language aimed at a person here is not something this assistant "
             "will write.",
}

# Verification states, in the words a colleague uses. `verification_summary`
# already decided which state it is; this only changes the register.
_VERIFY_BECAUSE = {
    "contradicted": "A figure in this answer does not match what your own documents "
                    "say.",
    "partly_verified": "Part of this answer checks out against your documents and "
                       "part of it is not covered by them either way.",
    "unverified": "Nothing in your own documents settles what this answer claims, so "
                  "it could not be checked.",
    "not_checked": "This answer was not checked at all, so treat it as unverified.",
    "nothing_asserted": "The assistant declined rather than asserting anything, so "
                        "there was nothing to check.",
}

_ACTION_HEADLINE = {
    "pass": "Checked, and you can use this.",
    "repair": "We edited this answer before you saw it.",
    "escalate": "You can read this, but check one thing before you act on it.",
    "block": "This answer was not cleared, so you are not seeing it.",
}


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value:
            return value
    return None


def _detector(record: dict[str, Any], name: str) -> dict[str, Any]:
    for d in record.get("detectors") or []:
        if d.get("detectorId") == name and d.get("status") == "ok":
            return d
    return {}


def _detail(record: dict[str, Any], name: str) -> dict[str, Any]:
    return _detector(record, name).get("detail") or {}


def _cited_line(record: dict[str, Any], checked: bool) -> str:
    """Where the answer's material came from.

    Two rules, and both were broken on screen before this function existed.
    **Never say no sources were found when sources were found and ignored** —
    those are different failures and the second is worse. And **never say the
    figures check out unless they were checked**: the page once printed "we
    checked the figures against it" directly above "nothing here is settled by
    anything we hold", about the same answer. `checked` is passed by the caller
    from the verification state rather than guessed from the citation count,
    because counting citations is not the act of checking a claim."""
    ver = record.get("verification") or {}
    cited = int(ver.get("sourcesCited") or 0)
    retrieved = len((record.get("retrieval") or {}).get("chunkIds") or [])
    if cited:
        many = cited > 1
        where = (f"It points at {cited} of your own document{'s' if many else ''}")
        if checked:
            return (f"{where}, and the figures in it check out against "
                    f"{'them' if many else 'it'}.")
        return f"{where}."
    if retrieved:
        return (f"Your own documents had {retrieved} relevant passage"
                f"{'s' if retrieved > 1 else ''} and the answer does not point at "
                f"any of them, so nothing in it could be checked against what you "
                f"actually hold.")
    return ("There was nothing in your own documents to check this against, so this "
            "is the model's general knowledge rather than your policy.")


def verdict(record: dict[str, Any]) -> dict[str, Any]:
    """One sentence, a couple of reasons, and the one thing to do.

    Returns ``{"headline", "because": [...], "doThis", "register"}``. The page
    renders `headline` and `because` in the open, and everything technical stays
    behind a toggle."""
    status = record.get("status")
    decision = record.get("decision") or {}
    action = decision.get("action") or ""

    # ---- the paths where nothing was ever generated ----------------------
    if status == "refused_harmful":
        harm = (record.get("harm") or {})
        family = harm.get("family") or ""
        if family == "blocked_term":
            return {"headline": "This assistant will not process that wording.",
                    "because": ["Your organisation has put one of those words on its "
                                "own list of terms that must not be sent to an "
                                "outside AI model.",
                                "Nothing was sent and nothing was spent."],
                    "doThis": "Ask the same thing without that term.",
                    "register": "refused"}
        return {"headline": "This assistant will not help with that.",
                "because": [_HARM_BECAUSE.get(
                    family, "It reads as asking for help harming somebody."),
                            "It was stopped before the question reached the AI, so "
                            "nothing was written, nothing was sent to the model, and "
                            "nothing was spent."],
                "doThis": (harm.get("alternative") or ""),
                "register": "refused"}

    if status == "out_of_purpose":
        check = record.get("purposeCheck") or {}
        return {"headline": "That is not what this assistant is for.",
                "because": [f"You asked about {check.get('label', 'something personal')}, "
                            f"and every assistant here is registered for a particular "
                            f"job — this one is not registered for that, and nor is "
                            f"any of the others.",
                            "Nothing was sent to the AI, so nothing was written and "
                            "nothing was spent."],
                "doThis": "Ask this assistant something from its own department, or "
                          "use the picker above to switch to another one.",
                "register": "redirected"}

    if status == "budget_exhausted":
        spend = record.get("spend") or {}
        return {"headline": f"{spend.get('name', 'This assistant')} is out of money "
                            f"for the month.",
                "because": [f"It has spent ₹{spend.get('usedInr', 0):,.0f} of its "
                            f"₹{spend.get('budgetInr', 0):,.0f} budget.",
                            "Your question was not sent to the AI, so it cost nothing."],
                "doThis": f"{spend.get('owner') or 'The owner'} can raise the budget.",
                "register": "paused"}

    if status == "capacity_exhausted":
        cap = record.get("capacity") or {}
        return {"headline": f"{cap.get('name', 'This assistant')} has no reviewer time "
                            f"left this week.",
                "because": ["Answers from this assistant need a person to look at them, "
                            "and this week's reviewer time is used up.",
                            "Your question was not sent to the AI, so it cost nothing."],
                "doThis": f"{cap.get('owner') or 'The owner'} can raise the limit.",
                "register": "paused"}

    if status == "redirected":
        scope = record.get("scope") or {}
        other = scope.get("bestOtherName")
        return {"headline": "That is not this assistant's subject.",
                "because": [scope.get("reason") or
                            "This assistant does not hold documents about that.",
                            "No AI was called, so nothing was spent — being asked the "
                            "wrong question is a routing mistake, not a problem with "
                            "you or with the answer."],
                "doThis": f"Ask {other} instead." if other else "",
                "register": "redirected"}

    if status in ("held", "refused"):
        reasons = ((record.get("ingress") or {}).get("reasons")
                   or ["Something in the question needs a person to look at it first."])
        return {"headline": "Your question is waiting for a person to look at it.",
                "because": [reasons[0],
                            "It was stopped before it reached the AI, so nothing was "
                            "written and nothing was spent."],
                "doThis": "This page updates on its own when they decide.",
                "register": "held"}

    if status == "blocked":
        return {"headline": "A reviewer did not release this.",
                "because": [f"{record.get('reviewedBy') or 'A reviewer'} in your "
                            f"organisation looked at the question and decided not to "
                            f"let it through."],
                "doThis": record.get("reviewNote") or "", "register": "blocked"}

    if not action:
        return {"headline": "", "because": [], "doThis": "", "register": ""}

    # ---- the ordinary path: an answer came back and was checked ----------
    because: list[str] = []
    do_this = ""

    if decision.get("abstention") and action == "pass":
        return {"headline": "The assistant told you it could not answer this.",
                "because": ["That is the system working, not a failure: it did not "
                            "invent something to fill the gap.",
                            "There are no claims in the answer, so there was nothing "
                            "to check."],
                "doThis": "", "register": "declined"}

    headline = _ACTION_HEADLINE.get(action, "This answer was flagged.")

    floor = (decision.get("detail") or {}).get("floor")
    objective = _detail(record, "purpose").get("plainEnglish")
    certainty = _detail(record, "certainty")

    if action == "pass":
        because.append(_cited_line(record, checked=True))
        if (record.get("verification") or {}).get("secondOpinion"):
            because.append("A second, independent model read the same answer against "
                           "the same documents and agreed with it.")
    elif action == "block":
        if floor == "toxic_answer":
            headline = "The AI wrote something we will not show you."
            because.append("Its language was not acceptable to send to anybody, so it "
                           "was withheld rather than shown to you with a warning.")
            because.append("The draft went to the team that owns this assistant.")
            do_this = "Ask again, and it will try afresh."
        else:
            cap = record.get("capability") or {}
            if cap.get("capabilityMismatch"):
                because.append(
                    f"The assistant said it would only {cap.get('declaredAction')}, "
                    f"but the tool it picked can actually "
                    f"{cap.get('effectiveAction')} — so it would have changed "
                    f"something in the real world, which it is not allowed to do "
                    f"on its own.")
            else:
                because.append(decision.get("reason") or "")
            because.append("What it drafted was sent to the team that owns this "
                           "assistant instead of to you.")
    else:
        # repair and escalate — the cases where the person still gets the text
        if floor == "objective_unserved" and objective:
            headline = "This answers part of what you asked."
            because.append(objective)
            do_this = "Ask again for the part it skipped."
        elif floor == "confidently_wrong":
            headline = "This answer sounds more certain than the evidence behind it."
            sentence = (certainty.get("overbought") or [{}])[0].get("text") or ""
            because.append("One line in it is stated as settled when nothing in your "
                           "documents says so"
                           + (f": “{sentence[:160]}”" if sentence else "."))
            do_this = "Confirm that line with a person before you act on it."
        elif floor == "omitted_condition":
            headline = "This answer leaves out a condition that applies to you."
            omission = (decision.get("detail") or {}).get("omission") or {}
            because.append("Your own policy carries a line this answer did not mention"
                           + (f": “{str(omission.get('sentence', ''))[:160]}”"
                              if omission.get("sentence") else "."))
            do_this = "Check that condition before you act on this."
        elif floor == "judge_unavailable":
            headline = "This answer was not double-checked."
            because.append("Nothing authoritative covered it, so a second model should "
                           "have read it, and that check could not be run.")
            do_this = "Treat it as unchecked until somebody confirms it."
        else:
            state = (record.get("verification") or {}).get("status")
            because.append(_VERIFY_BECAUSE.get(state) or decision.get("reason") or "")
            if state in ("contradicted", "partly_verified"):
                because.append(_cited_line(record, checked=False))

        uncertainty = decision.get("surfacedUncertainty")
        if uncertainty and not do_this:
            do_this = str(uncertainty)
        if action == "repair":
            because.append("We changed the answer itself — personal details were "
                           "removed before it reached you.")
        side = (decision.get("sideEffect") or {})
        if side.get("kind") == "queued_for_approval":
            headline = "This needs somebody's approval before anything happens."
            because.append("The assistant proposed an action, not just an answer, so it "
                           "is waiting for a person rather than going ahead.")

    # A plain note about the answer's own honesty, when it is worth one.
    if certainty.get("confidentlyWrong") and floor != "confidently_wrong":
        because.append("It also states one thing more firmly than your documents "
                       "support.")

    return {"headline": headline,
            "because": [b for b in because if b][:3],
            "doThis": do_this,
            "register": action}
