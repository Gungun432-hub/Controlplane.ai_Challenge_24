"""ControlPlane — a consequence-aware control plane for enterprise AI.

The runtime is `api.py` (HTTP surface) over `plane.py` (orchestration) over
`gate.py` (pricing, routing, governance status). Nothing else is the app.

Imports here are deliberately shallow: `providers/` is lazy so the offline
runtime never requires an HTTP client, and pulling the whole plane in at
package-import time would defeat that.
"""
from __future__ import annotations

import hashlib

__all__ = ["ControlPlane", "JsonlLedger", "__version__"]
__version__ = "2.0.0"


def __getattr__(name: str):
    if name == "ControlPlane":
        from .plane import ControlPlane
        return ControlPlane
    if name == "JsonlLedger":
        from .ledger import JsonlLedger
        return JsonlLedger
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ----------------------------------------------------------------- build ---
BUILD_NAME = "finale-v5.2"


def build_stamp() -> dict:
    """Which code is actually serving this page.

    A reviewer looked at one copy of this project and reported findings from
    another, and we spent a day establishing which was which. The cheapest
    possible cure is for the running process to say so itself: the fingerprint
    below is a digest of every module's bytes, so two checkouts that differ
    anywhere produce different stamps and the masthead shows it."""
    from pathlib import Path as _P

    here = _P(__file__).parent
    digest = hashlib.sha256()
    names = []
    for path in sorted(here.glob("*.py")) + sorted(here.glob("providers/*.py")):
        digest.update(path.read_bytes())
        names.append(path.name)
    return {"build": BUILD_NAME,
            "fingerprint": digest.hexdigest()[:12],
            "modules": len(names),
            "servingFrom": str(here),
            # The modules this build is expected to have. If one is missing you
            # are running an older checkout, whatever the folder is called.
            "hasModules": {name: (here / f"{name}.py").exists()
                           for name in ("harm", "abstain", "purpose", "scope",
                                        "adjudicator", "judge_eval",
                                        # v5
                                        "objective", "certainty", "plain",
                                        "supervisors",
                                        # v5.1
                                        "personal")}}
