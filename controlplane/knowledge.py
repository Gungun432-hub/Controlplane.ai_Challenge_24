"""Retrieval corpora for the three demonstration use cases.

The brief describes an enterprise running several assistants at once over "a
mix of well-governed and loosely governed internal data sources". That mix is
modelled here explicitly: each document carries a governance grade, and the
retriever reports it, because a claim grounded only in a loosely-governed
document is not as well supported as one grounded in an approved source.

Retrieval is deliberately simple - lexical scoring over a small corpus. The
point of this project is what happens to a model's answer after it exists, not
retrieval quality; using anything heavier would obscure that.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

GOVERNED = "governed"        # reviewed, owned, versioned
LOOSE = "loosely_governed"   # a wiki page nobody owns; usable but weaker


@dataclass
class Doc:
    id: str
    text: str
    grade: str
    owner: str


CORPORA: dict[str, list[Doc]] = {
    "customer_support": [
        Doc("fund-factsheet-v4",
            "The Horizon Balanced Fund targets 6 to 7 percent annualised over a rolling "
            "five-year period. Returns are not guaranteed and capital is at risk. An exit "
            "load of 1 percent applies if units are redeemed before 12 months. Minimum "
            "investment is INR 5,000.", GOVERNED, "product.compliance"),
        Doc("sla-policy-v2",
            "Priority 1 incidents carry a 30 minute response SLA and a 4 hour resolution "
            "target. Priority 2 is a 2 hour response and 1 business day resolution. "
            "Priority 3 is next business day.", GOVERNED, "service.ops"),
        Doc("refunds-v3",
            "Refunds are processed within 7 working days to the original payment method. "
            "Orders cancelled before dispatch are refunded in full. After dispatch a "
            "restocking fee of 2 percent applies.", GOVERNED, "finance.ops"),
        Doc("wiki-tax-notes",
            "Informal note: some customers ask about section 80C deductions on insurance "
            "premiums. We do not give tax advice. Refer them to a qualified adviser.",
            LOOSE, "unowned-wiki"),
    ],
    "internal_knowledge": [
        Doc("hr-leave-v7",
            "Band 8 employees accrue 21 days of annual leave per year. The notice period "
            "for band 8 is 60 days. A sabbatical requires three years of continuous "
            "service and director approval.", GOVERNED, "people.ops"),
        Doc("it-access-v2",
            "VPN access requires MFA. To reset MFA, raise a ticket with the service desk; "
            "self-service reset is not available for privileged accounts.", GOVERNED, "it.security"),
        Doc("wiki-expenses",
            "Informal note: expense claims over INR 25,000 usually need a second approver, "
            "but practice varies by team and this page has not been reviewed since 2024.",
            LOOSE, "unowned-wiki"),
    ],
    "decision_support": [
        Doc("underwriting-u7",
            "Underwriting rule U-7: approve where debt-to-income is below 40 percent and "
            "there is no default in the last 24 months. Decline where DTI exceeds 55 "
            "percent. Refer to a human underwriter between 40 and 55 percent.",
            GOVERNED, "credit.risk"),
        Doc("policy-hx4412",
            "Policy HX-4412 covers accidental damage up to INR 200,000 with a INR 5,000 "
            "deductible. Flood damage is excluded unless rider FL-2 is active. Claims must "
            "be filed within 30 days of the incident.", GOVERNED, "claims.policy"),
        Doc("treasury-controls",
            "Vendor payment runs require a matched purchase order and an approved invoice. "
            "Payments above INR 1,00,00,000 require dual authorisation.", GOVERNED, "treasury"),
    ],
}

_STOP = {"the","a","an","is","are","was","to","of","for","on","in","and","or","it","its",
         "this","that","with","at","by","as","from","your","you","we","our","what","how",
         "can","do","does","i","my","me","if","when","will","be"}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _STOP and len(w) > 2}


def retrieve(use_case: str, query: str, k: int = 2) -> list[dict]:
    """Return the top-k documents, each with its governance grade."""
    docs = CORPORA.get(use_case, [])
    q = _tokens(query)
    if not q:
        return []
    scored = []
    for d in docs:
        overlap = len(q & _tokens(d.text))
        if overlap:
            scored.append((overlap / len(q), d))
    scored.sort(key=lambda x: -x[0])
    return [{"id": d.id, "text": d.text, "grade": d.grade, "owner": d.owner,
             "score": round(s, 3)}
            for s, d in scored[:k]]
