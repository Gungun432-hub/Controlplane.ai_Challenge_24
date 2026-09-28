"""Is this question even this assistant's business?

The mentor's example was a food-delivery bot asked about Chipotle's share price.
It answers. Nothing in it is unsafe, nothing in it is toxic, nothing about it
trips a hallucination check — and it is still wrong, because that assistant was
never registered to answer it and nobody has ever reviewed a single word it is
about to say on the subject.

`allowed_intents` in the registry is about *what kind of act* a question is:
a lookup, a draft, an instruction. It has nothing to say about *subject*, and a
question can be a perfectly ordinary policy lookup about a completely foreign
domain. That is the gap this file closes.

**The scope of an assistant is defined by the evidence its owner gave it.**

We do not hand-write a topic list, because a hand-written list is stale the day
after it is written and does not survive a real deployment with hundreds of
systems. The lexicon is derived from the documents that were ingested for that
system, weighted by how *distinctive* each term is across the fleet. Upload an
HR handbook to the HR assistant and "probation", "notice period" and "grievance"
become in-scope for it, automatically, with no code change. Delete the document
and they stop being in scope. That is the property that makes this scale.

Three answers, not two, because there are three genuinely different situations:

``in_scope``      this system's own evidence covers the subject.
``foreign``       another registered system's evidence covers it, clearly and by
                  a margin. The person is redirected to that assistant by name.
                  No model call, no human review queue: being asked the wrong
                  question is a routing mistake, not a governance incident, and
                  treating it as one would bury the reviewer in noise.
``uncovered``     nobody's documents cover it. This is *not* a refusal — it is
                  the honest case the problem statement names, where there is no
                  ground truth to check against. It is allowed through with the
                  fact recorded, the evidence tier pinned to parametric, and the
                  adjudicator forced on, because an answer nobody can check is
                  exactly the answer that needs a second opinion.
"""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field
from typing import Any

IN_SCOPE = "in_scope"
FOREIGN = "foreign"
UNCOVERED = "uncovered"

# A term has to carry subject matter. Function words, governance boilerplate and
# the vocabulary every policy document shares are useless for telling two
# departments apart, and leaving them in is how a scope check starts firing on
# the word "policy".
_STOP = set("""
the a an and or of to in for on at is are was were be been being this that these
those with as by from it its you your we our i me my they their he she his her
will shall can may might must should would could do does did done have has had
not no nor but if then than so such when where which who whom whose what how why
all any each every both few more most other some only own same too very just
about above after again against below between during into once over under until
up down out off again further here there both
policy policies procedure procedures process must required requires requirement
requirements approved approval approvals guide guideline guidelines section
version effective supersedes applies apply applicable document documented note
notes example examples general standard standards rule rules must never always
system systems team teams used use using user users work working
page pages line lines item items list lists table tables
""".split())

_TERM = re.compile(r"[a-z][a-z0-9\-]{2,}")

# A signature term must be at least this much more this system's than everyone
# else's. 0.55 means "more than half of all the mass of this term in the fleet
# sits in this one system's documents".
DISTINCTIVE = 0.55

# Thresholds. Deliberately asymmetric: the bar for redirecting somebody is much
# higher than the bar for deciding a question is our own, because a wrong
# redirect is a visible insult to the person asking and a missed one only costs
# a governed answer.
#
# And two independent signals, not one, because each is wrong on its own:
#
# * **Coverage** is the BM25 score of this system's own documents against the
#   question — the same retrieval that grounds the answer, reused. It is strong
#   where the corpus really does discuss the subject and useless where two
#   corpora share a common word ("send", "approval", "price").
# * **Distinctiveness** is the signature lexicon below. It is strong where one
#   department owns a vocabulary and blind where a subject is genuinely shared.
#
# A question counts as ours if *either* signal says so. It is only handed to
# somebody else when the other system wins on *both*. That asymmetry is the whole
# design: we would much rather answer a borderline question under full governance
# than turn a colleague away from the assistant that could have helped them.
MINE_FLOOR = 0.14        # distinctiveness: our own vocabulary plainly covers this
COVERAGE_FLOOR = 2.0     # coverage: our own documents retrieve strongly for it
FOREIGN_FLOOR = 0.42     # somebody else's vocabulary plainly does
FOREIGN_MARGIN = 2.6     # and by this multiple of ours
COVERAGE_MARGIN = 1.35   # and their documents retrieve this much better than ours
MIN_TERMS = 2            # too short to judge; do not guess


def terms(text: str) -> list[str]:
    return [t for t in _TERM.findall((text or "").lower())
            if t not in _STOP and len(t) > 2]


@dataclass
class ScopeVerdict:
    verdict: str
    system_id: str
    score: float = 0.0
    best_other: str = ""
    best_other_score: float = 0.0
    best_other_name: str = ""
    matched: list[str] = field(default_factory=list)
    foreign_matched: list[str] = field(default_factory=list)
    reason: str = ""
    coverage: float = 0.0
    best_other_coverage: float = 0.0

    @property
    def allowed(self) -> bool:
        """`uncovered` is allowed through. Only `foreign` is turned away."""
        return self.verdict != FOREIGN

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "score": round(self.score, 4),
                "reason": self.reason,
                "coverage": round(self.coverage, 3),
                "matched": self.matched[:8],
                "bestOther": self.best_other, "bestOtherName": self.best_other_name,
                "bestOtherScore": round(self.best_other_score, 4),
                "bestOtherCoverage": round(self.best_other_coverage, 3),
                "foreignMatched": self.foreign_matched[:8]}


class ScopeIndex:
    """Signature vocabulary per system, rebuilt whenever the corpus changes.

    Cheap enough to rebuild on every upload (tens of milliseconds over the whole
    fleet), which is what lets scope follow the evidence instead of lagging it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.lexicon: dict[str, dict[str, float]] = {}
        self.names: dict[str, str] = {}
        self.built_at: float = 0.0
        self.source_counts: dict[str, int] = {}
        self._corpus: Any = None

    # ------------------------------------------------------------- build ---
    def build(self, corpus: Any, registry: Any) -> dict[str, Any]:
        """Term mass per system from the ingested chunks, plus the registry's own
        declarations (name, department, tool keywords) as a floor so a system
        with no documents yet is still recognisable as itself."""
        raw: dict[str, dict[str, float]] = {}
        names: dict[str, str] = {}
        counts: dict[str, int] = {}

        apps = getattr(registry, "applications", {}) or {}
        for system_id, app in apps.items():
            names[system_id] = getattr(app, "name", system_id)
            bag: dict[str, float] = {}

            # The registry's own words, weighted like a small document. This is
            # what stops a brand-new system with an empty corpus looking like it
            # has no subject at all.
            declared = " ".join([
                getattr(app, "name", ""), getattr(app, "department", ""),
                *[k for t in getattr(app, "tools", {}).values()
                  for k in (getattr(t, "keywords", []) or [])],
                *[getattr(t, "name", "") for t in getattr(app, "tools", {}).values()],
            ])
            for t in terms(declared):
                bag[t] = bag.get(t, 0.0) + 3.0

            chunks = []
            if corpus is not None:
                chunks = list(getattr(corpus, "_by_system", {}).get(system_id, []) or [])
            counts[system_id] = len(chunks)
            for chunk in chunks:
                for t in terms(getattr(chunk, "text", "")):
                    bag[t] = bag.get(t, 0.0) + 1.0
            raw[system_id] = bag

        total: dict[str, float] = {}
        for bag in raw.values():
            for t, n in bag.items():
                total[t] = total.get(t, 0.0) + n

        # Signature weight: log-damped mass, kept only where this system holds
        # the clear majority of the term across the whole fleet.
        lexicon: dict[str, dict[str, float]] = {}
        for system_id, bag in raw.items():
            sig: dict[str, float] = {}
            for t, n in bag.items():
                share = n / total[t] if total.get(t) else 0.0
                if share < DISTINCTIVE:
                    continue
                sig[t] = round(math.log1p(n) * share, 5)
            lexicon[system_id] = sig

        with self._lock:
            self.lexicon, self.names, self.source_counts = lexicon, names, counts
            self._corpus = corpus
            self.built_at = __import__("time").time()
        return self.stats()

    # ---------------------------------------------------------- coverage ---
    def coverage(self, system_id: str, question: str) -> float:
        """How well this system's own documents retrieve for this question.

        The same BM25 index that grounds the answer, asked a different question.
        Reusing it rather than building a second similarity model is deliberate:
        one index means scope and grounding can never disagree about what a
        system holds."""
        if self._corpus is None:
            return 0.0
        try:
            hits = self._corpus.search(system_id, question, top_k=1)
        except Exception:                                            # noqa: BLE001
            return 0.0
        return float(hits[0][1]) if hits else 0.0

    def stats(self) -> dict[str, Any]:
        return {"builtAt": self.built_at,
                "systems": {sid: {"signatureTerms": len(lex),
                                  "chunks": self.source_counts.get(sid, 0),
                                  "top": sorted(lex, key=lex.get, reverse=True)[:10]}
                            for sid, lex in self.lexicon.items()}}

    # ------------------------------------------------------------- score ---
    def score(self, system_id: str, question: str) -> tuple[float, list[str]]:
        """Signature mass of the question that belongs to this system, per
        content word. Normalising by the question's own length is what keeps a
        long question from scoring higher than a short one on the same subject.
        """
        lex = self.lexicon.get(system_id) or {}
        content = terms(question)
        if not content:
            return 0.0, []
        hits = [(t, lex[t]) for t in dict.fromkeys(content) if t in lex]
        mass = sum(w for _, w in hits)
        return mass / math.sqrt(len(content)), [t for t, _ in
                                                sorted(hits, key=lambda kv: -kv[1])]

    def ranked(self, question: str) -> list[tuple[str, float, list[str]]]:
        rows = [(sid, *self.score(sid, question)) for sid in self.lexicon]
        return sorted(rows, key=lambda r: -r[1])

    # ------------------------------------------------------------- check ---
    def check(self, system_id: str, question: str) -> ScopeVerdict:
        content = terms(question)
        if len(content) < MIN_TERMS or not self.lexicon:
            return ScopeVerdict(IN_SCOPE, system_id, reason=(
                "the scope index is empty" if not self.lexicon else
                "too few subject words to judge scope; other checks apply"))

        mine, matched = self.score(system_id, question)
        mine_cov = self.coverage(system_id, question)
        others = [row for row in self.ranked(question) if row[0] != system_id]
        other_id, other_score, other_matched = (others[0] if others
                                                else ("", 0.0, []))
        other_cov = self.coverage(other_id, question) if other_id else 0.0

        def verdict(kind: str, reason: str) -> ScopeVerdict:
            return ScopeVerdict(kind, system_id, mine, other_id or "", other_score,
                                self.names.get(other_id or "", ""), matched,
                                other_matched, reason=reason,
                                coverage=mine_cov, best_other_coverage=other_cov)

        # Turning somebody away needs both signals to point at the same other
        # system, and to point there decisively: a distinctive vocabulary this
        # system does not share AND documents that retrieve materially better
        # than ours. One signal alone is how a scope check becomes the feature
        # everybody disables.
        #
        # This test runs BEFORE the in-scope floors, and that ordering is the
        # whole point. Departments share vocabulary — retail "returns" and
        # financial "returns" are the same word — so a support corpus will
        # happily retrieve something for a question about fund performance and
        # clear an absolute coverage floor on a subject it has no business
        # answering. Absolute coverage cannot see that; the comparison can.
        foreign = (other_score >= FOREIGN_FLOOR
                   and other_score >= max(mine, 0.02) * FOREIGN_MARGIN
                   and other_cov >= max(mine_cov * COVERAGE_MARGIN, 0.5))
        if foreign:
            return verdict(FOREIGN, (
                f"this subject belongs to "
                f"{self.names.get(other_id or '', other_id or 'another system')} — "
                f"its documents are the ones that cover "
                f"{', '.join(other_matched[:4])}, and nothing this system holds "
                f"does"))

        # Otherwise either signal is enough to keep the question. Coverage
        # first, because it is the one that reads the documents themselves.
        if mine_cov >= COVERAGE_FLOOR:
            return verdict(IN_SCOPE, f"this system's own documents retrieve strongly "
                                     f"for this question (score {mine_cov:.2f})")
        if mine >= MINE_FLOOR:
            return verdict(IN_SCOPE, f"this system's registered vocabulary covers "
                                     f"{', '.join(matched[:4])}")

        return verdict(UNCOVERED, (
            "no document held by any registered system covers this subject, so "
            "nothing we have can settle the answer either way"))


INDEX = ScopeIndex()
