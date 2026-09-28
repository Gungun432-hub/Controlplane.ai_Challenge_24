"""Provider seam.

The live adapter is imported lazily: offline mode is the reference runtime and
must not require an HTTP client to be installed.
"""
from typing import Any

from .base import ACTIONS, AgentProposal, ProposalError, parse_proposal
from .offline import OfflineProvider

__all__ = ["ACTIONS", "AgentProposal", "ProposalError", "parse_proposal",
           "OfflineProvider", "get_provider", "GeminiProvider"]


def get_provider(name: str | None = None) -> Any:
    """Resolve a provider. Offline is the default and always works."""
    import os
    choice = (name or os.getenv("CONTROLPLANE_PROVIDER", "offline")).strip().lower()
    if choice in ("gemini", "live"):
        from .gemini import GeminiProvider
        return GeminiProvider()
    if choice in ("dual", "hybrid"):
        # Live for the question a person types, deterministic for everything
        # else. See dual.py for why that split is deliberate.
        from .dual import DualProvider
        return DualProvider()
    return OfflineProvider()


def __getattr__(attr: str) -> Any:
    if attr == "DualProvider":
        from .dual import DualProvider
        return DualProvider
    if attr == "GeminiProvider":
        from .gemini import GeminiProvider
        return GeminiProvider
    raise AttributeError(attr)
