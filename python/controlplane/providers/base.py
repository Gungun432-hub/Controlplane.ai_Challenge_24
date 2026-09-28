"""Provider seam: an agent proposes, it never decides.

The single most important property of this file is what an AgentProposal does
NOT contain. There is no route, no risk score, no approval and no override. A
model may propose which tool to call, what to say, and which sources it used.
Everything after that is deterministic policy.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

ACTIONS = ("read", "draft", "advise", "decide", "execute")


class ProposalError(ValueError):
    """The model returned something that is not a valid proposal.

    Raised rather than coerced. A malformed proposal is a governance event, not
    a formatting inconvenience, and must never be silently repaired into an
    allow.
    """


@dataclass
class AgentProposal:
    tool_id: str
    declared_action: str
    answer: str
    source_ids: list[str] = field(default_factory=list)   # what the model cited
    sources: list[str] = field(default_factory=list)      # server-resolved text
    unresolved_ids: list[str] = field(default_factory=list)
    rationale: str = ""
    raw: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    provider: str = "offline"
    # Set only when the live model was tried and failed. The receipt and the
    # user page both render it, because "which provider actually answered" is
    # not a detail — it is the difference between a model's answer and a
    # deterministic stand-in.
    fell_back_from: str = ""
    fallback_code: str = ""
    fallback_detail: str = ""
    latency_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "toolId": self.tool_id, "declaredAction": self.declared_action,
            "answer": self.answer, "sourceIds": self.source_ids,
            "sources": self.sources, "unresolvedSourceIds": self.unresolved_ids,
            "rationale": self.rationale, "provider": self.provider,
            "fellBackFrom": self.fell_back_from,
            "fallbackCode": self.fallback_code,
            "fallbackDetail": self.fallback_detail,
            "usage": self.usage, "latencyMs": round(self.latency_ms, 1),
        }


PROPOSAL_SCHEMA = {
    "tool_id": "string — the id of ONE registered tool you intend to use",
    "declared_action": f"string — one of {list(ACTIONS)}",
    "answer": "string — the text you would return to the user",
    "source_ids": "array of strings — the IDs of context entries you relied on, [] if none",
    "rationale": "string — one sentence on why this tool",
}

SYSTEM_PROMPT = (
    "You are an enterprise AI application operating behind a governance control "
    "plane. You propose an action; you do NOT decide whether it is allowed.\n\n"
    "Return ONLY a JSON object with exactly these keys:\n"
    + json.dumps(PROPOSAL_SCHEMA, indent=2)
    + "\n\nRules:\n"
    "- tool_id must be one of the tools offered to you. Never invent one.\n"
    "- CHOOSE THE WEAKEST TOOL THAT DOES THE JOB. The catalogue says what each\n"
    "  tool does. If you are only reading, explaining, quoting a policy or\n"
    "  answering a question, choose a tool that READS \u2014 never one that\n"
    "  DECIDES or EXECUTES. A tool that cannot be undone is for when the user\n"
    "  actually asked you to change something.\n"
    "- If the request needs no tool at all \u2014 a greeting, small talk, a\n"
    "  general explanation \u2014 use tool_id \"none\" with declared_action\n"
    "  \"read\". That is always available and is the right answer more often\n"
    "  than you think.\n"
    "- declared_action must describe what your answer DOES, honestly, and it\n"
    "  must not claim less than the tool you picked is capable of.\n"
    "- source_ids must be IDs from the context list. You cannot supply source TEXT;\n"
    "  the server resolves IDs itself, so inventing a source achieves nothing.\n"
    "- Do not include a decision, verdict, risk score, or approval of any kind.\n"
    "- No prose outside the JSON object."
)


def parse_proposal(raw: str, allowed_tools: list[str]) -> AgentProposal:
    """Validate strictly. Reject rather than repair."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ProposalError("no JSON object in model output")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ProposalError(f"proposal is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ProposalError("proposal is not an object")

    forbidden = sorted({"route", "outcome", "decision", "verdict", "allow",
                        "approved", "risk", "risk_price", "blast_radius",
                        "blastRadius", "override", "governance", "completeness"}
                       & set(data))
    if forbidden:
        raise ProposalError(f"proposal attempted to decide governance: {forbidden}")

    if "sources" in data:
        # Supplying source TEXT is an attempt to author its own evidence.
        raise ProposalError("proposal supplied source text; only source_ids are accepted")

    ALLOWED = {"tool_id", "declared_action", "answer", "source_ids", "rationale"}
    REQUIRED = {"tool_id", "declared_action", "answer"}

    missing = sorted(REQUIRED - set(data))
    if missing:
        raise ProposalError(f"proposal is missing required keys: {missing}")
    unknown = sorted(set(data) - ALLOWED)
    if unknown:
        # Reject rather than ignore. A field we do not understand is a field we
        # cannot govern, and silently dropping it hides a contract change.
        raise ProposalError(f"proposal contains unrecognised keys: {unknown}")

    # Types are checked, never coerced. str(123) == "123" would turn a malformed
    # proposal into a plausible one.
    for key in ("tool_id", "declared_action", "answer"):
        if not isinstance(data[key], str):
            raise ProposalError(f"'{key}' must be a string, got "
                                f"{type(data[key]).__name__}")
    if "rationale" in data and not isinstance(data["rationale"], str):
        raise ProposalError("'rationale' must be a string")
    if not data["answer"].strip():
        raise ProposalError("'answer' must not be empty")
    if len(data["answer"]) > 8000:
        raise ProposalError(f"'answer' exceeds 8000 characters ({len(data['answer'])})")

    tool = data["tool_id"].strip()
    if tool not in allowed_tools:
        raise ProposalError(f"tool '{tool}' is not registered for this application")

    action = data["declared_action"].strip().lower()
    if action not in ACTIONS:
        raise ProposalError(f"declared_action '{action}' is not one of {list(ACTIONS)}")

    ids = data.get("source_ids", [])
    if not isinstance(ids, list):
        raise ProposalError("source_ids must be an array")
    if any(not isinstance(x, str) or not x.strip() or len(x) > 128 for x in ids):
        raise ProposalError("source_ids must be non-empty strings under 128 characters")
    if len(ids) != len(set(ids)):
        raise ProposalError("source_ids contains duplicates")
    if len(ids) > 8:
        raise ProposalError(f"source_ids exceeds 8 entries ({len(ids)})")

    return AgentProposal(
        tool_id=tool, declared_action=action, answer=data["answer"],
        source_ids=[x.strip() for x in ids],
        rationale=data.get("rationale", "")[:280], raw=text,
    )


class Provider(Protocol):
    name: str
    live: bool

    def propose(self, message: str, *, tools: list[dict[str, Any]], context: list[str],
                deadline_s: float) -> AgentProposal: ...

    def decide_probe(self, text: str) -> str: ...
