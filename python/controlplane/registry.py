"""The registry is the trust foundation.

An application declares what it intends. A tool binding states what the tool can
actually do. When those disagree, the binding wins — which is the whole reason
blast radius is worth anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ACTION_RADIUS = {"read": 0.10, "draft": 0.35, "advise": 0.70, "decide": 0.90, "execute": 1.00}
RANK = {name: i for i, name in enumerate(ACTION_RADIUS)}
IRREVERSIBLE = {"decide", "execute"}


@dataclass
class ToolBinding:
    id: str
    name: str
    effective_action: str
    reversible: bool = True
    approval_required: bool = False
    allowed_environments: list[str] = field(default_factory=lambda: ["staging", "production"])
    max_amount_inr: float | None = None
    keywords: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "effectiveAction": self.effective_action,
                "reversible": self.reversible, "approvalRequired": self.approval_required,
                "allowedEnvironments": self.allowed_environments,
                "maxAmountInr": self.max_amount_inr, "capabilities": self.capabilities,
                "keywords": self.keywords}


#: Always offered, to every application, and it is not a loophole: it reads,
#: it is reversible, it holds no capabilities and it touches nothing.
#:
#: It exists because every proposal had to name a tool, so a greeting or a plain
#: explanation was forced to borrow one — and the tool it borrowed carried that
#: tool's blast radius. *"hey gemini"* went down an account-lookup path and was
#: blocked for proposing to act. Making "no tool" expressible is what stops an
#: answer being priced for something it never proposed to do.
NO_TOOL = ToolBinding("none", "No tool — answer only", "read",
                      keywords=[], capabilities=[])


@dataclass
class Application:
    system_id: str
    name: str
    owner: str
    department: str
    # Where this system's briefings go. Editable from the console and replayed
    # from the ledger, so it survives a restart and is never hardcoded.
    owner_email: str = ""
    environment: str = "production"
    policy_profile: str = "customer_support"
    jurisdiction: str | None = None
    audience: str = "internal"
    regulated: bool = False
    budget_inr_month: float = 20000.0
    review_minutes_week: float = 600.0
    max_action: str = "advise"            # ceiling for UNBOUND work
    authorised_actions: list[str] = field(
        default_factory=lambda: ["read", "draft", "advise"])   # explicit grants
    # What this system is registered to be asked. A question outside its
    # declared purpose is held, not silently answered — the mentor's point that
    # you cannot know a team's business logic but you can tell what a prompt is
    # for. Empty means no scope restriction.
    allowed_intents: list[str] = field(default_factory=list)
    # Some systems legitimately handle personal data. An HR or finance system
    # that must see an identifier is configured to, rather than fighting the
    # control every time.
    allow_prompt_pii: bool = False
    # "soft" warns; "hard" refuses new questions once the week's reviewer
    # capacity is gone. Spend is deliberately never a hard cap — see
    # `ControlPlane.capacity` for why attention is the budget worth enforcing.
    # Words this organisation has decided its own assistants will not process —
    # an unreleased codename, a customer under NDA, a slur the company has ruled
    # on. Configuration, not code: a blocklist that needs a deploy to add a word
    # is a blocklist nobody keeps current. Editable from the console and replayed
    # from the ledger like every other row here.
    blocked_terms: list[str] = field(default_factory=list)
    review_mode: str = "soft"
    # And the same choice for money. Default soft, because a token cap that
    # bites would need thousands of questions — but one system runs it hard so
    # the behaviour is demonstrable rather than merely described.
    spend_mode: str = "soft"
    # The employee this system serves, and the questions they plausibly ask.
    # Both live here rather than in the user page's JavaScript so that the
    # control plane and the user page can never disagree about who is asking or
    # which department they are in — they read the same registry row. Editable at
    # runtime like the owner, because a demo where the names are frozen in a
    # source file is a demo you cannot adapt in the room.
    end_user: str = ""
    sample_questions: list[dict[str, str]] = field(default_factory=list)
    spend_baseline_inr: float = 0.0
    review_baseline_minutes: float = 0.0
    tools: dict[str, ToolBinding] = field(default_factory=dict)
    state: str = "healthy"

    def as_dict(self) -> dict[str, Any]:
        return {"systemId": self.system_id, "name": self.name, "owner": self.owner,
                "ownerEmail": self.owner_email,
                "department": self.department, "environment": self.environment,
                "policyProfile": self.policy_profile, "jurisdiction": self.jurisdiction,
                "audience": self.audience, "regulated": self.regulated,
                "budgetInrMonth": self.budget_inr_month,
                "reviewMinutesWeek": self.review_minutes_week,
                "maxAction": self.max_action, "authorisedActions": self.authorised_actions,
                "allowedIntents": self.allowed_intents,
                "blockedTerms": list(self.blocked_terms),
                "allowPromptPii": self.allow_prompt_pii,
                "reviewMode": self.review_mode,
                "spendMode": self.spend_mode,
                "endUser": self.end_user or "Employee",
                "sampleQuestions": self.sample_questions,
                "state": self.state,
                "spendBaselineInr": self.spend_baseline_inr,
                "reviewBaselineMinutes": self.review_baseline_minutes,
                "tools": [t.as_dict() for t in self.tools.values()]}


@dataclass
class Capability:
    declared_action: str
    effective_action: str
    blast_radius: float
    mismatch: bool
    reversible: bool
    approval_required: bool
    denied: str | None = None
    reasons: list[str] = field(default_factory=list)
    snapshot_hash: str = ""
    tool_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"toolId": self.tool_id,
                "declaredAction": self.declared_action, "effectiveAction": self.effective_action,
                "blastRadius": round(self.blast_radius, 4), "capabilityMismatch": self.mismatch,
                "reversible": self.reversible, "approvalRequired": self.approval_required,
                "denied": self.denied, "reasons": self.reasons,
                "capabilitySnapshotHash": self.snapshot_hash}


class Registry:
    def __init__(self) -> None:
        self.applications: dict[str, Application] = {}

    def register(self, app: Application) -> Application:
        self.applications[app.system_id] = app
        return app

    def get(self, system_id: str) -> Application | None:
        return self.applications.get(system_id)

    def resolve_capability(self, system_id: str, tool_id: str | None, declared_action: str,
                           *, amount_inr: float | None = None) -> Capability:
        # Every early return below is a fail-closed path, and each one should
        # still say which tool was being resolved. Stamping it once here is
        # safer than remembering to pass it at eight separate return sites.
        cap = self._resolve_capability(system_id, tool_id, declared_action,
                                       amount_inr=amount_inr)
        cap.tool_id = tool_id
        return cap

    def _resolve_capability(self, system_id: str, tool_id: str | None, declared_action: str,
                            *, amount_inr: float | None = None) -> Capability:
        import hashlib, json

        app = self.get(system_id)
        if app is None:
            # Unregistered traffic is governed under the strictest reading, never
            # waved through. We notice; we do not claim to discover.
            return Capability(declared_action, "execute", ACTION_RADIUS["execute"], True,
                              False, True, denied="unregistered application",
                              reasons=[f"system_id '{system_id}' is not in the registry"])

        reasons: list[str] = []
        binding = app.tools.get(tool_id or "")
        if binding is None and tool_id == NO_TOOL.id:
            # `none` is bound to every application by construction. It reads, it
            # is reversible and it holds no capabilities, so an answer that needed
            # no tool is priced for what it actually is.
            binding = NO_TOOL
        if tool_id and binding is None:
            return Capability(declared_action, "execute", ACTION_RADIUS["execute"], True,
                              False, True, denied="unregistered tool",
                              reasons=[f"tool '{tool_id}' is not bound to {system_id}"])

        if binding is None:
            if declared_action not in RANK:
                return Capability(str(declared_action), "execute", ACTION_RADIUS["execute"],
                                  True, False, True,
                                  denied="unrecognised declared action",
                                  reasons=[f"declared_action '{declared_action}' is not one of "
                                           f"{list(RANK)}"], snapshot_hash="")
            effective = declared_action
            if RANK[effective] > RANK[app.max_action]:
                effective = app.max_action
                reasons.append(f"capped at the application's authorised ceiling "
                               f"'{app.max_action}'")
            reversible, approval = effective not in IRREVERSIBLE, False
        else:
            effective = binding.effective_action
            reversible, approval = binding.reversible, binding.approval_required
            if app.environment not in binding.allowed_environments:
                return Capability(declared_action, effective, ACTION_RADIUS[effective], True,
                                  reversible, True,
                                  denied="tool not permitted in this environment",
                                  reasons=[f"'{binding.id}' is allowed in "
                                           f"{binding.allowed_environments}, this application "
                                           f"runs in {app.environment}"],
                                  snapshot_hash="")
            if binding.max_amount_inr is not None and (amount_inr or 0) > binding.max_amount_inr:
                # Exceeding a transaction limit is out of policy. It does not make
                # the action "more execute" — it makes it unauthorised.
                return Capability(declared_action, effective, ACTION_RADIUS[effective], True,
                                  reversible, True,
                                  denied="transaction exceeds the tool's authorised limit",
                                  reasons=[f"₹{amount_inr:,.0f} exceeds the ₹"
                                           f"{binding.max_amount_inr:,.0f} limit on "
                                           f"'{binding.id}'"], snapshot_hash="")

        # An unrecognised declared action is a malformed request, not a
        # harmless under-declaration. Fail closed rather than ranking it lowest.
        if declared_action not in RANK:
            return Capability(str(declared_action), effective, ACTION_RADIUS[effective],
                              True, reversible, True,
                              denied="unrecognised declared action",
                              reasons=[f"declared_action '{declared_action}' is not one of "
                                       f"{list(RANK)}"], snapshot_hash="")

        # A binding is an explicit grant, but only within what the application is
        # authorised for. A tool proving an action the application was never
        # approved for is a configuration fault, and a control plane must not
        # resolve a configuration fault in favour of more capability.
        if effective not in app.authorised_actions:
            return Capability(declared_action, effective, ACTION_RADIUS[effective], True,
                              reversible, True,
                              denied="tool proves an action the application is not authorised for",
                              reasons=[f"'{tool_id}' proves '{effective}' but {system_id} is "
                                       f"authorised for {app.authorised_actions}"],
                              snapshot_hash="")

        mismatch = RANK[declared_action] < RANK[effective]
        if mismatch:
            reasons.insert(0, f"declared '{declared_action}' but the tool binding proves "
                              f"'{effective}'")

        radius = ACTION_RADIUS[effective]
        radius *= 1.15 if app.audience == "external" else 1.0
        radius *= 1.2 if app.regulated else 1.0
        radius = min(1.0, radius)

        snapshot = hashlib.sha256(json.dumps(
            {"app": app.system_id, "tool": tool_id, "effective": effective,
             "env": app.environment, "audience": app.audience,
             "regulated": app.regulated}, sort_keys=True).encode()).hexdigest()[:16]

        return Capability(declared_action, effective, radius, mismatch, reversible,
                          approval, None, reasons, snapshot)
