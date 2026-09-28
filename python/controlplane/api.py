"""HTTP surface. Thin on purpose — every decision is made in the plane."""
from __future__ import annotations

import contextlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from .env import load as load_dotenv

# Before anything reads os.getenv. A real environment variable always wins, so
# this never overrides a deliberate export.
_DOTENV = load_dotenv()

from .ledger import JsonlLedger
from .org import SCENARIOS, build, catalogue
from .plane import ControlPlane
from .providers import get_provider

HERE = Path(__file__).parent


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]

# Mutating routes require an operator token. This is a prototype boundary, not
# enterprise IAM — but a control plane whose controls anyone can apply is not a
# control plane, and "approvedBy" as caller-supplied text proves nothing.
OPERATOR_TOKEN = os.getenv("CONTROLPLANE_OPERATOR_TOKEN", "operator-dev-token")

# How much synthetic history a cold start manufactures. Configurable so a test
# suite or a rehearsal reset does not have to pay for 110 turns.
SEED_TURNS = int(os.getenv("CONTROLPLANE_SEED_TURNS", "110"))


def operator(x_controlplane_actor: str = Header(default=""),
             x_controlplane_token: str = Header(default="")) -> dict[str, str]:
    if x_controlplane_token != OPERATOR_TOKEN:
        raise HTTPException(401, "operator token required for mutating routes "
                                 "(header X-ControlPlane-Token)")
    if not x_controlplane_actor.strip():
        raise HTTPException(400, "X-ControlPlane-Actor is required so the control can be "
                                 "attributed to a person")
    return {"actor": x_controlplane_actor.strip()}


def viewer(x_controlplane_token: str = Header(default="")) -> dict[str, str]:
    """A read that can expose a person's words needs the same token a control does.

    The split is by *content*, not by HTTP verb. Aggregate and configuration
    reads — the fleet roll-up, the policy in force, the scope index, the judge's
    score — carry no individual's data and stay open, because the portfolio and
    the developer page are meant to be readable. Anything that can return the
    text of somebody's question, the body of an uploaded policy document, or a
    receipt containing either is behind the token.

    That is a prototype boundary, and we say so on the developer page: it is a
    shared secret, not authenticated identity, and a real deployment needs SSO
    and per-role access. What it is not any more is nothing at all — the review
    queue and every employee's chat transcript used to be readable by anyone who
    could reach the port."""
    if x_controlplane_token != OPERATOR_TOKEN:
        raise HTTPException(401, "this route can return the text of a person's "
                                 "question or document and requires "
                                 "X-ControlPlane-Token")
    return {"reader": "operator"}


class TurnIn(BaseModel):
    systemId: str
    message: str
    toolHint: str | None = None
    amountInr: float | None = None
    shadowProfile: str | None = None


class AskIn(BaseModel):
    systemId: str
    message: str = Field(max_length=4000)
    sessionId: str = Field(default="", max_length=64)
    user: str = Field(default="user", max_length=60)
    toolHint: str | None = None
    amountInr: float | None = None


class PurposeCheckIn(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=6000)
    sources: list[str] | None = None


class PolicyVariant(BaseModel):
    label: str = Field(default="", max_length=60)
    profile: str | None = None
    jurisdiction: str | None = None


class PolicyABIn(BaseModel):
    systemId: str
    message: str = Field(max_length=4000)
    variants: list[PolicyVariant]


class ReviewIn(BaseModel):
    heldId: str
    decision: str = Field(pattern="^(pass|block)$")
    note: str = Field(default="", max_length=400)


class OwnerIn(BaseModel):
    systemId: str
    owner: str | None = Field(default=None, max_length=80)
    ownerEmail: str | None = Field(default=None, max_length=254)


class NotifyIn(BaseModel):
    systemId: str
    to: list[str] = Field(default_factory=list, max_length=5)
    note: str = Field(default="", max_length=600)


class ControlIn(BaseModel):
    systemId: str
    kind: str = Field(description="suspend | quarantine | tool_restricted | require_human | "
                                  "promote_inline | tighten | enable_cache")
    reason: str = "applied from the operations console"
    approvedBy: str | None = None
    ruleId: str | None = None
    ttlS: int = 3600


PAYLOADS = {
    "suspend": {"suspend": True},
    "quarantine": {"quarantine": True, "max_action": "read"},
    "tool_restricted": {"tool_restricted": True},
    "require_human": {"require_human": True},
    "promote_inline": {"promote_inline": ["fairness", "cost"]},
    "tighten": {"tighten": {"pass": 6, "repair": 6, "escalate": 14}},
    "enable_cache": {"enable_cache": True},
}
HUMAN_ONLY = {"suspend", "quarantine"}


def create_app() -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        from .gate import shutdown as pool_shutdown
        pool_shutdown(wait=False)

    app = FastAPI(title="ControlPlane", version="2.0",
                  description="Consequence-aware control plane for enterprise AI.",
                  lifespan=lifespan)
    ledger = JsonlLedger(os.getenv("LEDGER_PATH", "data/ledger.jsonl"),
                         os.getenv("LEDGER_SIGNING_KEY", "development-only"))
    state: dict[str, Any] = {}

    def boot(turns: int = SEED_TURNS, force_seed: bool = False) -> ControlPlane:
        """Recover from the ledger first. Seed only when there is nothing to
        recover, and mark what was seeded as synthetic."""
        import sys
        sys.path.insert(0, str(HERE.parent.parent))
        from seed_history import seed
        from .ingest import Corpus
        corpus = Corpus(os.getenv("CORPUS_PATH", "data/corpus"))
        restored = corpus.load()
        if restored == 0:
            # First start: ingest the documents shipped with the repo through
            # exactly the same path an upload uses. There is no privileged
            # built-in knowledge — the demo corpus is just files that arrive first.
            bundled = HERE.parent.parent / "corpus"
            for doc in sorted(bundled.glob("*/*")):
                if doc.is_file() and doc.suffix.lower() in (".md", ".txt"):
                    try:
                        corpus.add(doc.parent.name, doc.name, doc.read_bytes(),
                                   origin="bundled", uploaded_by="repo")
                    except Exception:                                # noqa: BLE001
                        continue
        state["corpus"] = corpus.stats()

        cp = ControlPlane(build(), get_provider(), ledger, corpus=corpus)
        recovered = cp.recover()
        if force_seed or recovered.get("recovered", 0) == 0:
            seed(cp, turns)
            state["seeded"] = True
        else:
            state["seeded"] = False
        state["recovered"] = recovered
        state["cp"] = cp
        state["started"] = time.time()
        return cp

    def reset(turns: int = SEED_TURNS, actor: str = "operator") -> ControlPlane:
        """A reset starts a new epoch. The old ledger is preserved beside it, so
        history is never silently blended with fresh synthetic traffic."""
        nonlocal ledger
        if ledger.path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archived = ledger.path.with_suffix(f".{stamp}.jsonl")
            ledger.path.rename(archived)
            state["archivedLedger"] = str(archived)
        ledger = JsonlLedger(str(ledger.path), os.getenv("LEDGER_SIGNING_KEY",
                                                        "development-only"))
        ledger.append({"event": "epoch.started", "systemId": "-",
                       "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                       "actor": actor, "synthetic": True,
                       "note": "seeded demonstration traffic follows"})
        return boot(turns, force_seed=True)

    def plane() -> ControlPlane:
        return state.get("cp") or reset()

    boot()

    # ------------------------------------------------------------------ views ---
    # Three surfaces, three jobs. The portfolio is the landing page because the
    # first question anyone asks is "what have we got and is any of it on fire",
    # not "show me the decision stream".
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def overview() -> str:
        return (HERE / "overview.html").read_text(encoding="utf-8")

    @app.get("/console", response_class=HTMLResponse, include_in_schema=False)
    def console() -> str:
        return (HERE / "dashboard.html").read_text(encoding="utf-8")

    # A control plane that logs a 404 for every page load is not a good look on
    # a projector with the console open.
    _FAVICON = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="7" fill="#2E1C55"/>'
        '<circle cx="16" cy="16" r="8.5" fill="none" stroke="#B57BFF" stroke-width="3"/>'
        '<circle cx="16" cy="16" r="2.6" fill="#B57BFF"/></svg>')

    @app.get("/favicon.svg", include_in_schema=False)
    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(_FAVICON, media_type="image/svg+xml",
                        headers={"cache-control": "public, max-age=86400"})

    @app.get("/chat", response_class=HTMLResponse, include_in_schema=False)
    def chat_page() -> str:
        return (HERE / "chat.html").read_text(encoding="utf-8")

    @app.get("/review", response_class=HTMLResponse, include_in_schema=False)
    def review_page() -> str:
        return (HERE / "review.html").read_text(encoding="utf-8")

    @app.get("/advisor", response_class=HTMLResponse, include_in_schema=False)
    def advisor() -> str:
        return (HERE / "advisor.html").read_text(encoding="utf-8")

    @app.get("/developer", response_class=HTMLResponse, include_in_schema=False)
    def developer() -> str:
        return (HERE / "developer.html").read_text(encoding="utf-8")

    @app.get("/health")
    def health(verify_ledger: bool = True) -> dict[str, Any]:
        """Status, and the evidence for it.

        `status` used to be the string "ok" no matter what, including when the
        append-only log this whole product rests on no longer verified. A health
        endpoint that cannot go unhealthy is decoration, so the chain is
        recomputed here and a broken one is reported as `degraded`, with the
        index it broke at."""
        cp = plane()
        chain: dict[str, Any] = {"checked": False}
        if verify_ledger and cp.ledger is not None:
            try:
                chain = {"checked": True, **cp.ledger.verify(),
                         "chainWarnings": getattr(cp.ledger, "chain_warnings", 0),
                         "signatureWarnings": getattr(cp.ledger,
                                                      "signature_warnings", 0)}
            except Exception as exc:                                 # noqa: BLE001
                chain = {"checked": True, "valid": False,
                         "reason": f"{type(exc).__name__}: {exc}"[:160]}
        degraded = bool(cp.ledger_errors) or (
            chain.get("checked") and not chain.get("valid", True))
        from . import build_stamp
        return {"status": "degraded" if degraded else "ok",
                "buildStamp": build_stamp(),
                "provider": cp.provider.name, "live": cp.provider.live,
                # Two applications call the model now — the assistant and the
                # adjudicator. Saying which credential each uses is what turns
                # "oversight cost us this much" from a claim into a measurement.
                "judge": {"model": getattr(cp.provider, "judge_model", ""),
                          "separateKey": bool(getattr(cp.provider,
                                                      "judge_key_is_separate", False))},
                "decisions": len(cp.decisions),
                "recovered": state.get("recovered"),
                "containsSyntheticSeedData": bool(state.get("seeded")),
                "config": {"dotenvLoaded": bool(_DOTENV), "keys": sorted(_DOTENV)},
                "corpus": cp.corpus.stats(),
                "ledger": chain,
                "heldQuestions": len(cp.held),
                "openForReview": sum(1 for h in cp.held.values()
                                     if h["status"] in ("held", "refused")),
                "capacity": {sid: cp.capacity(sid)["state"]
                             for sid in cp.registry.applications},
                "ledgerErrors": len(cp.ledger_errors),
                "droppedVerification": len(cp.dropped_verification),
                "uptimeS": round(time.time() - state["started"], 1)}

    # ------------------------------------------------------------------- data ---
    @app.get("/api/fleet")
    def fleet() -> dict[str, Any]:
        return plane().fleet()

    @app.get("/api/stream")
    def stream(after: int = 0, limit: int = 60, _v: dict = Depends(viewer)) -> dict[str, Any]:
        cp = plane()
        rows = [d for d in cp.decisions if d["sequence"] > after][-limit:]
        return {"cursor": cp._seq, "rows": [{
            "requestId": d["requestId"], "sequence": d["sequence"], "systemId": d["systemId"],
            "at": d["createdAt"], "declared": (d["capability"] or {}).get("declaredAction"),
            "effective": (d["capability"] or {}).get("effectiveAction"),
            "mismatch": (d["capability"] or {}).get("capabilityMismatch"),
            "action": d["decision"]["action"], "price": d["risk"].get("price"),
            "governance": d["governance"]["status"],
            "decisionLatencyMs": d["decisionLatencyMs"],
            "verification": d["verificationStatus"],
            # Where this row came from. A console that mixes simulated load in
            # with questions people actually typed, and does not say which is
            # which, is asking a jury to take the liveness on trust.
            "origin": d.get("origin", "ambient"),
        } for d in rows]}

    @app.get("/api/supervisors")
    def supervisor_charters() -> dict[str, Any]:
        """The two charters and the arbitration rules, from the same place the
        code reads them — so the page cannot describe an architecture the
        running system does not have."""
        from .supervisors import charters
        return charters()

    @app.post("/api/purpose-check")
    def purpose_check(body: PurposeCheckIn) -> dict[str, Any]:
        """Did the answer serve what the person was trying to do?

        Open on purpose: it calls no model, spends nothing, and reads nothing
        belonging to anybody. It runs the production `purpose` detector on a
        question and an answer you type — which is the only way to demonstrate
        the car-wash case, because that question belongs to no department and so
        can never be asked through /chat."""
        from .objective import describe, inspect as inspect_objectives
        from .purpose import purpose as run

        sources = [s for s in (body.sources or []) if s.strip()]
        result = run(answer=body.answer, prompt=body.question,
                     sources=sources, retrieved=sources)
        objectives = inspect_objectives(body.question, body.answer)
        return {"detector": result.as_dict(),
                "objectives": objectives.as_dict(),
                "plainEnglish": describe(objectives),
                "purposeServed": not objectives.defeated}

    @app.get("/api/decision/{request_id}")
    def decision(request_id: str, _v: dict = Depends(viewer)) -> dict[str, Any]:
        record = plane().by_id.get(request_id)
        if record is None:
            raise HTTPException(404, "no such decision")
        return record

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, Any]:
        cp = plane()
        from . import build_stamp
        return {"scenarios": SCENARIOS, "buildStamp": build_stamp(),
                "systems": [a.as_dict() for a in cp.registry.applications.values()]}

    @app.get("/api/live")
    def live(window_minutes: int = 30) -> dict[str, Any]:
        """What the people on /chat have just done to the portfolio's numbers.

        The portfolio polls this. It is the difference between "we also built a
        chatbot" and "this is one governed system with two faces"."""
        return plane().live_traffic(
            window_s=max(1, min(720, window_minutes)) * 60.0)

    @app.post("/api/policy-ab")
    def policy_ab(body: PolicyABIn, who: dict = Depends(operator)) -> dict[str, Any]:
        """One answer, two policies, one model call.

        The problem statement says a single checking approach rarely works
        everywhere. This is the demonstration: identical bytes, identical
        detector results, and the decision changes because the rules did."""
        cp = plane()
        try:
            return cp.policy_ab(body.systemId, body.message,
                                [v.model_dump() for v in body.variants])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/policy-ab/presets")
    def policy_ab_presets() -> dict[str, Any]:
        from .org import POLICY_AB
        return {"presets": POLICY_AB}

    @app.get("/api/scope")
    def scope_index(systemId: str = "", question: str = "") -> dict[str, Any]:
        """The subject scope each system is registered for, derived from its own
        documents — and, optionally, the verdict on one question so a developer
        can see exactly why a redirect happened."""
        cp = plane()
        out: dict[str, Any] = {"index": cp.scope.stats()}
        if systemId and question:
            out["verdict"] = cp.scope.check(systemId, question).as_dict()
            out["ranked"] = [
                {"systemId": sid,
                 "name": cp.scope.names.get(sid, sid),
                 "distinctiveness": round(score, 4),
                 "coverage": round(cp.scope.coverage(sid, question), 3),
                 "matched": matched[:6]}
                for sid, score, matched in cp.scope.ranked(question)]
        return out

    @app.get("/api/judge/eval")
    def judge_eval(live: bool = False) -> dict[str, Any]:
        """Score the adjudicator against its labelled set, on demand.

        "You used a model to check a model — how do you know the checker is any
        good?" is the question, and this is the answer: a catch rate, a false
        alarm rate and a confusion matrix over cases that are in the repository
        for anyone to read. `live=false` scores the deterministic reference judge
        and costs nothing."""
        from .judge_eval import run
        from .providers.offline import OfflineProvider
        cp = plane()
        judge = cp.provider if live else OfflineProvider()
        return run(judge)

    @app.get("/api/judge/cases")
    def judge_cases() -> dict[str, Any]:
        from .judge_cases import CASES
        return {"cases": [{"id": c.id, "domain": c.domain, "question": c.question,
                           "answer": c.answer, "sources": c.sources,
                           "expectVerdict": c.expect_verdict,
                           "expectSufficiency": c.expect_sufficiency,
                           "why": c.why, "tags": c.tags} for c in CASES]}

    @app.get("/api/policy/{system_id}")
    def policy(system_id: str) -> dict[str, Any]:
        """The resolved snapshot a system is actually being judged under.

        A developer who is told "you were flagged" and cannot see the rule is
        being audited, not helped. base profile + jurisdiction overlay + active
        control overlays, with the arithmetic shown."""
        from .gate import JURISDICTIONS, PROFILES, resolve_profile
        cp = plane()
        app_ = cp.registry.get(system_id)
        if app_ is None:
            raise HTTPException(404, "no such system")
        overlay = cp.overlay_for(system_id)
        base = PROFILES.get(app_.policy_profile) or PROFILES["customer_support"]
        resolved = resolve_profile(app_.policy_profile, app_.jurisdiction, overlay)
        controls = [{"id": o.id, "kind": o.kind, "reason": o.reason,
                     "approvedBy": o.approved_by, "version": o.version,
                     "expiresAtUtc": datetime.fromtimestamp(
                         o.expires_at, timezone.utc).isoformat().replace("+00:00", "Z")}
                    for o in cp.overlays if o.live and o.system_id == system_id]
        return {
            "systemId": system_id, "owner": app_.owner, "department": app_.department,
            "audience": app_.audience, "regulated": app_.regulated,
            "jurisdiction": app_.jurisdiction,
            "maxAction": app_.max_action,
            "authorisedActions": list(app_.authorised_actions),
            "tools": [t.as_dict() for t in app_.tools.values()],
            "layers": {
                "base": {"id": base.id, "name": base.name,
                         "thresholds": dict(base.thresholds),
                         "weights": dict(base.weights),
                         "latencyBudgetMs": base.latency_budget_ms,
                         "inline": list(base.inline), "deferred": list(base.deferred),
                         "mandatory": list(base.mandatory),
                         "hardGateActions": list(base.hard_gate_actions)},
                "jurisdiction": JURISDICTIONS.get((app_.jurisdiction or "").lower()),
                "controls": controls,
            },
            "resolved": {"id": resolved.id, "thresholds": dict(resolved.thresholds),
                         "weights": dict(resolved.weights),
                         "latencyBudgetMs": resolved.latency_budget_ms,
                         "inline": list(resolved.inline),
                         "deferred": list(resolved.deferred),
                         "mandatory": list(resolved.mandatory),
                         "hardGateActions": list(resolved.hard_gate_actions),
                         "audience": resolved.audience},
            # IDs only. The corpus text is what grounding is measured
            # against; handing it out over HTTP would let a caller
            # reverse-engineer a passing answer.
            "corpus": [c["id"] for c in catalogue(system_id)],
        }

    # ------------------------------------------------------ the user side ---
    @app.post("/api/ask")
    def ask(body: AskIn, who: dict = Depends(operator)) -> dict[str, Any]:
        """A person asks a question. Ingress first, then the model."""
        try:
            return plane().ask(body.systemId, body.message,
                               session_id=body.sessionId, user=body.user or who["actor"],
                               tool_hint=body.toolHint, amount_inr=body.amountInr)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.get("/api/chat/{session_id}")
    def chat(session_id: str, _v: dict = Depends(viewer)) -> dict[str, Any]:
        return {"sessionId": session_id, "turns": plane().chat(session_id)}

    @app.get("/api/review")
    def review_queue(status: str = "held", _v: dict = Depends(viewer)) -> dict[str, Any]:
        cp = plane()
        rows = cp.review_queue(status)
        counts = {}
        for h in cp.held.values():
            counts[h["status"]] = counts.get(h["status"], 0) + 1
        # Questions the subject-scope gate turned away. They are not in the
        # reviewer's queue and must not be — nobody has to decide anything about
        # them — but a system being asked the wrong questions all day is a fact
        # its owner needs, so they are listed here where somebody will see them.
        redirects = list(cp.redirected)[::-1]
        counts["redirected"] = len(redirects)
        harm = list(cp.harm_refusals)[::-1]
        counts["harmful"] = len(harm)
        # Same reasoning as the redirects above, one step further out: a work
        # assistant being used as a personal one all day is a fact its owner
        # needs and an auditor will ask about, and it is nobody's queue item.
        personal = list(cp.out_of_purpose)[::-1]
        counts["outOfPurpose"] = len(personal)
        return {"queue": rows, "counts": counts, "total": len(cp.held),
                "redirects": redirects[:60], "harmful": harm[:60],
                "outOfPurpose": personal[:60]}

    @app.post("/api/review")
    def review(body: ReviewIn, who: dict = Depends(operator)) -> dict[str, Any]:
        """A human passes or blocks a held question."""
        try:
            return plane().review_question(body.heldId, body.decision,
                                           actor=who["actor"], note=body.note)
        except ValueError as exc:
            code = 404 if "unknown held" in str(exc) else 400
            raise HTTPException(code, str(exc)) from None

    # -------------------------------------------------------- the evidence ---
    @app.get("/api/corpus/{system_id}")
    def corpus_list(system_id: str, _v: dict = Depends(viewer)) -> dict[str, Any]:
        cp = plane()
        return {"systemId": system_id, "documents": cp.corpus.catalogue(system_id),
                "stats": cp.corpus.stats(system_id)}

    @app.post("/api/corpus/{system_id}")
    async def corpus_upload(system_id: str, request: Request,
                            who: dict = Depends(operator)) -> dict[str, Any]:
        """Add a document. Chunked, indexed, and citable within the second."""
        from .ingest import MAX_UPLOAD_BYTES
        cp = plane()
        if cp.registry.get(system_id) is None:
            raise HTTPException(404, f"unknown system '{system_id}'")
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(400, "a file is required")
        data = await upload.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "the file is too large")
        try:
            doc = cp.corpus.add(system_id, upload.filename or "document.txt", data,
                                title=str(form.get("title") or "") or None,
                                uploaded_by=who["actor"], origin="uploaded")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        # Scope follows the evidence. An assistant that has just been given a
        # document must be allowed to answer questions about it in the same
        # second, and one whose document is removed must stop claiming it.
        cp.rebuild_scope()
        cp._event("corpus.document_added", system_id, {
            "actor": who["actor"], "docId": doc.doc_id, "title": doc.title,
            "filename": doc.filename, "sha256": doc.sha256,
            "chunks": len(doc.chunks), "chars": doc.chars})
        return {"document": doc.as_dict(), "stats": cp.corpus.stats(system_id)}

    @app.delete("/api/corpus/{system_id}/{doc_id}")
    def corpus_delete(system_id: str, doc_id: str,
                      who: dict = Depends(operator)) -> dict[str, Any]:
        cp = plane()
        doc = cp.corpus.documents.get(doc_id)
        if doc is None or doc.system_id != system_id:
            raise HTTPException(404, "no such document")
        cp.corpus.remove(doc_id)
        cp.rebuild_scope()
        cp._event("corpus.document_removed", system_id, {
            "actor": who["actor"], "docId": doc_id, "title": doc.title})
        return {"removed": doc_id, "stats": cp.corpus.stats(system_id)}

    @app.get("/api/advisories/{system_id}")
    def advisories(system_id: str, _v: dict = Depends(viewer)) -> dict[str, Any]:
        """The owner briefing for one system, in the owner's language."""
        try:
            return plane().advisories(system_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post("/api/owner")
    def owner(body: OwnerIn, who: dict = Depends(operator)) -> dict[str, Any]:
        """Rename a system's owner, or change where their briefings go."""
        try:
            return plane().set_owner(body.systemId, actor=who["actor"],
                                     owner=body.owner, owner_email=body.ownerEmail)
        except ValueError as exc:
            code = 404 if "unknown system" in str(exc) else 400
            raise HTTPException(code, str(exc)) from None

    @app.get("/api/notify/config")
    def notify_config() -> dict[str, Any]:
        """Whether Send will work, and from which address. Never the credential."""
        from .notify import configured
        return configured()

    @app.post("/api/notify")
    def notify(body: NotifyIn, who: dict = Depends(operator)) -> dict[str, Any]:
        """Email the owner their briefing. Recorded either way."""
        try:
            out = plane().notify_owner(body.systemId,
                                       [a.strip() for a in body.to if a.strip()],
                                       actor=who["actor"], note=body.note or "")
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None
        return out

    @app.post("/api/notify/preview")
    def notify_preview(body: NotifyIn) -> dict[str, Any]:
        """Render without sending, so an operator can read it before anyone else
        does. Read-only, so it needs no operator token."""
        from .briefing import render
        try:
            brief = plane().advisories(body.systemId)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None
        subject, html, text = render(brief, note=body.note or "")
        return {"subject": subject, "html": html, "text": text,
                "advisories": len(brief["advisories"]), "owner": brief["owner"]}

    @app.get("/api/recommendations")
    def recommendations(_v: dict = Depends(viewer)) -> dict[str, Any]:
        return {"recommendations": plane().recommendations[::-1][:20]}

    @app.get("/api/ledger")
    def ledger_read(limit: int = 30, who: dict = Depends(operator)) -> dict[str, Any]:
        # Receipts contain the original message and the agent's proposal.
        limit = max(1, min(int(limit), 200))
        return {"entries": ledger.read(limit), "verification": ledger.verify()}

    # ---------------------------------------------------------------- actions ---
    @app.post("/api/turn")
    def turn(body: TurnIn, who: dict = Depends(operator)) -> dict[str, Any]:
        cp = plane()
        if cp.registry.get(body.systemId) is None and body.systemId not in ("ghost-bot",):
            raise HTTPException(400, f"unknown system '{body.systemId}'")
        # The console bench, not a person: recorded as such so the portfolio's
        # live-traffic band means what it says.
        return cp.turn(body.systemId, body.message, tool_hint=body.toolHint,
                       amount_inr=body.amountInr, shadow_profile=body.shadowProfile,
                       origin="scenario")

    @app.post("/api/surge")
    def surge(turns: int = 40, concurrency: int = 16,
              who: dict = Depends(operator)) -> dict[str, Any]:
        """A real burst, not a loop.

        This used to issue `turns` calls sequentially, which is not a surge: each
        turn's deferred work drained while the next turn was still generating, so
        the queue never built a backlog and nothing ever degraded. Firing them
        concurrently makes the load real — and whatever the system does under it
        is then a measurement rather than a claim."""
        import random
        from concurrent.futures import ThreadPoolExecutor
        from .org import AMBIENT
        cp = plane()
        rng = random.Random()
        n = max(1, min(turns, 200))
        workers = max(1, min(concurrency, 32))
        before = len(cp.decisions)
        t0 = time.perf_counter()
        latencies: list[float] = []
        failures: list[str] = []

        def one() -> None:
            sid, msg = rng.choice(AMBIENT)
            try:
                r = cp.turn(sid, msg)
                latencies.append(r["decisionLatencyMs"])
            except Exception as exc:                                 # noqa: BLE001
                # Recorded, never swallowed. A surge that quietly drops turns is
                # the same dishonesty this product exists to remove.
                failures.append(f"{type(exc).__name__}: {exc}"[:160])

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda _: one(), range(n)))
        wall_ms = (time.perf_counter() - t0) * 1000

        f = cp.fleet()
        injected = len(cp.decisions) - before
        ordered = sorted(latencies)
        def pct(q: float) -> float | None:
            if not ordered:
                return None
            return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)
        return {"injected": injected, "requested": n, "concurrency": workers,
                "wallMs": round(wall_ms, 1),
                "throughputPerS": round(injected / (wall_ms / 1000), 1) if wall_ms else None,
                "decisionP50Ms": pct(0.50), "decisionP95Ms": pct(0.95),
                "decisionMaxMs": round(ordered[-1], 1) if ordered else None,
                "failures": len(failures), "failureSample": failures[:3],
                "verificationBacklog": f["verificationBacklog"],
                "deferredQueueDepth": f["deferredQueueDepth"],
                "staleExposure": f["staleExposure"],
                "governanceHealth": f["governanceHealth"]}

    @app.post("/api/control")
    def control(body: ControlIn, who: dict = Depends(operator)) -> dict[str, Any]:
        cp = plane()
        if body.kind not in PAYLOADS:
            raise HTTPException(400, f"unknown control '{body.kind}'")
        if body.kind in HUMAN_ONLY and not body.approvedBy:
            raise HTTPException(403, f"'{body.kind}' requires human approval")
        approver = who["actor"] if body.kind in HUMAN_ONLY else None
        overlay = cp.apply_overlay(body.systemId, body.kind, PAYLOADS[body.kind], body.reason,
                                  rule_id=body.ruleId, approved_by=approver,
                                  ttl_s=body.ttlS,
                                  expected={"exposurePer100": "decrease",
                                            "spendInr": "decrease"})
        return overlay.as_dict()

    @app.post("/api/control/{overlay_id}/rollback")
    def rollback(overlay_id: str, actor: str = "operator", who: dict = Depends(operator)) -> dict[str, Any]:
        overlay = plane().rollback_overlay(overlay_id, who["actor"])
        if overlay is None:
            raise HTTPException(404, "no active control with that id")
        return overlay.as_dict()

    @app.post("/api/budget")
    def budget(systemId: str, budgetInr: float | None = None,
               reviewMinutesWeek: float | None = None,
               who: dict = Depends(operator)) -> dict[str, Any]:
        cp = plane()
        try:
            change = cp.set_budget(systemId, actor=who["actor"], budget_inr=budgetInr,
                                   review_minutes_week=reviewMinutesWeek)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"change": change, "system": cp.project(systemId)}

    @app.post("/api/reset")
    def do_reset(turns: int = SEED_TURNS, who: dict = Depends(operator)) -> dict[str, Any]:
        cp = reset(turns, who["actor"])
        return {"ok": True, "decisions": len(cp.decisions),
                "archivedLedger": state.get("archivedLedger"),
                "note": "previous ledger preserved; this epoch is synthetic demo data"}

    @app.get("/api/reproduce/{request_id}")
    def reproduce(request_id: str, _v: dict = Depends(viewer)) -> dict[str, Any]:
        """Replay a recorded decision under the policy snapshot that was active
        when it was made, and show that the result is identical."""
        cp = plane()
        record = cp.by_id.get(request_id)
        if record is None:
            raise HTTPException(404, "no such decision")
        from .detectors import DetectorResult
        from .gate import governance_status, price, resolve_profile, route
        from .registry import Capability
        cap_d = record["capability"] or {}
        cap = Capability(cap_d.get("declaredAction", "advise"),
                         cap_d.get("effectiveAction", "advise"),
                         cap_d.get("blastRadius", 0.0), cap_d.get("capabilityMismatch", False),
                         cap_d.get("reversible", True), cap_d.get("approvalRequired", False),
                         cap_d.get("denied"), cap_d.get("reasons", []),
                         cap_d.get("capabilitySnapshotHash", ""))
        # Replay from the decision-time snapshot, never from the amended list.
        evidence = record.get("detectorsAtDecision") or record["detectors"]
        results = [DetectorResult(d["detectorId"], d["score"], d["confidence"], d["status"],
                                  requirement=d.get("requirement", "advisory"),
                                  labels=d.get("labels", []), detail=d.get("detail", {}))
                   for d in evidence]
        from .plane import profile_from_snapshot
        profile = profile_from_snapshot(record.get("policy"))
        risk = price(results, profile.weights, cap.blast_radius)
        gov = governance_status(results, profile, cap.effective_action)
        again = route((record["proposal"] or {}).get("answer", ""), results, risk, profile,
                      cap, gov)
        # Canonical comparison. Comparing only action and price would call a
        # replay "identical" while showing the viewer two different confidence
        # bands, which is worse than reporting a divergence.
        def canonical(action: dict[str, Any], r: dict[str, Any],
                      g: dict[str, Any]) -> dict[str, Any]:
            return {"action": action["action"],
                    "price": r.get("price"),
                    "band": list(r.get("band") or []),
                    "pFailure": r.get("pFailure"),
                    "dominant": r.get("dominant"),
                    "governance": g.get("status"),
                    "sideEffect": (action.get("sideEffect") or {}).get("state"),
                    "releasedTextSha256": _sha(action.get("releasedText", ""))}

        was = canonical(record["decision"], record["risk"], record["governance"])
        now = canonical(again, risk, gov)
        differences = sorted(k for k in was if was[k] != now[k])
        return {"requestId": request_id, "identical": not differences,
                "differences": differences,
                "canonical": {"recorded": was, "reproduced": now},
                "replayedFrom": ("detectorsAtDecision"
                                 if record.get("detectorsAtDecision") else "detectors"),
                "policySnapshot": record.get("policy"),
                "messageSha256": record.get("messageSha256"),
                "recorded": {"action": record["decision"]["action"],
                             "price": record["risk"].get("price"),
                             "band": record["risk"].get("band"),
                             "policy": (record.get("policy") or {}).get("id"),
                             "capabilitySnapshotHash": cap.snapshot_hash},
                "reproduced": {"action": again["action"], "price": risk["price"],
                               "band": risk["band"],
                               "policy": (record.get("policy") or {}).get("id"),
                               "capabilitySnapshotHash": cap.snapshot_hash}}

    return app


app = create_app()
