"""Runtime configuration and policy loading.

Policies are data, not code: they live in YAML so that a governance owner can
change how the system behaves for one use case, or one jurisdiction, without a
deploy. This is a direct response to the brief's observation that regulatory
expectations differ by geography and industry and that rigid, hard-coded rules
age quickly.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
POLICY_DIR = ROOT / "policies"
DATA_DIR = ROOT.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    provider: str = field(default_factory=lambda: _env("CONTROLPLANE_PROVIDER", "offline"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    judge_model: str = field(default_factory=lambda: _env("GEMINI_JUDGE_MODEL", "gemini-flash-latest"))
    embed_model: str = field(default_factory=lambda: _env("GEMINI_EMBED_MODEL", "text-embedding-004"))
    ledger_key: str = field(default_factory=lambda: _env("LEDGER_SIGNING_KEY", "dev-only-not-a-secret"))

    @property
    def live(self) -> bool:
        return self.provider == "gemini" and bool(self.gemini_api_key)


SETTINGS = Settings()


class Policy:
    """A resolved policy: a use-case profile with an optional jurisdiction overlay."""

    def __init__(self, profile: dict[str, Any], jurisdiction: dict[str, Any] | None = None):
        self.raw_profile = profile
        self.jurisdiction = jurisdiction
        merged = copy.deepcopy(profile)

        if jurisdiction:
            for key, delta in (jurisdiction.get("threshold_delta") or {}).items():
                if key in merged["thresholds"]:
                    merged["thresholds"][key] = max(1, merged["thresholds"][key] - delta)
            for key, value in (jurisdiction.get("weight_overrides") or {}).items():
                merged["weights"][key] = value

        self.d = merged

    # -- convenience accessors -------------------------------------------------
    @property
    def id(self) -> str:
        base = self.d["id"]
        return f"{base}@{self.jurisdiction['id']}" if self.jurisdiction else base

    @property
    def name(self) -> str:
        return self.d["name"]

    @property
    def version(self) -> int:
        return int(self.d.get("version", 1))

    @property
    def thresholds(self) -> dict[str, int]:
        return self.d["thresholds"]

    @property
    def weights(self) -> dict[str, float]:
        return self.d["weights"]

    @property
    def latency_budget_ms(self) -> int:
        return int(self.d["latency_budget_ms"])

    @property
    def inline_detectors(self) -> list[str]:
        return list(self.d.get("inline_detectors", []))

    @property
    def async_detectors(self) -> list[str]:
        return list(self.d.get("async_detectors", []))

    @property
    def judge_cfg(self) -> dict[str, Any]:
        return self.d.get("llm_judge", {"enabled": False})

    @property
    def repair_actions(self) -> list[str]:
        return list(self.d.get("repair_actions", []))

    @property
    def hard_gate_action_classes(self) -> list[str]:
        return list(self.d.get("hard_gate_action_classes", []))

    @property
    def default_action_class(self) -> str:
        return self.d.get("default_action_class", "draft")

    @property
    def regime(self) -> list[str]:
        return list((self.jurisdiction or {}).get("regime", []))

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "jurisdiction": (self.jurisdiction or {}).get("id"),
            "thresholds": self.thresholds,
            "weights": self.weights,
            "latency_budget_ms": self.latency_budget_ms,
            "inline_detectors": self.inline_detectors,
            "async_detectors": self.async_detectors,
            "regime": self.regime,
        }


class PolicyRegistry:
    """Loads policy YAML from disk. Reload is cheap so policy can be hot-swapped."""

    def __init__(self, directory: Path = POLICY_DIR):
        self.directory = directory
        self.profiles: dict[str, dict] = {}
        self.jurisdictions: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        self.profiles = {}
        self.jurisdictions = {}
        for path in sorted(self.directory.glob("*.yaml")):
            doc = yaml.safe_load(path.read_text())
            self.profiles[doc["id"]] = doc
        for path in sorted((self.directory / "jurisdictions").glob("*.yaml")):
            doc = yaml.safe_load(path.read_text())
            self.jurisdictions[doc["id"]] = doc

    def get(self, profile_id: str, jurisdiction_id: str | None = None) -> Policy:
        if profile_id not in self.profiles:
            raise KeyError(f"unknown policy profile: {profile_id}")
        juris = self.jurisdictions.get(jurisdiction_id) if jurisdiction_id else None
        return Policy(self.profiles[profile_id], juris)

    def list_profiles(self) -> list[dict]:
        return [Policy(p).summary() for p in self.profiles.values()]

    def list_jurisdictions(self) -> list[dict]:
        return [
            {"id": j["id"], "name": j["name"], "regime": j.get("regime", [])}
            for j in self.jurisdictions.values()
        ]


REGISTRY = PolicyRegistry()
