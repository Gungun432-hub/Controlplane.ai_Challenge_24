"""Test-session guards.

**No test may ever send a real email.** Once `.env` holds working Resend
credentials, the `.env` loader in `api.py` puts them into the environment at
import time — so without this file, running `pytest` would quietly deliver
messages to whatever addresses the tests use, and burn real send quota.

This strips every notification credential before any test is collected. Tests
that exercise a transport set their own environment against a local stub server,
which is the only kind of "sending" that should ever happen in a test run.
"""
from __future__ import annotations

import os

import pytest

# Anything that could make notify.py reach the outside world.
_LIVE_TRANSPORT_VARS = (
    "NOTIFY_API_URL", "NOTIFY_API_KEY", "NOTIFY_API_STYLE", "NOTIFY_FROM",
    "NOTIFY_PREFER", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
    "SMTP_STARTTLS",
)

for _var in _LIVE_TRANSPORT_VARS:
    os.environ.pop(_var, None)

# Belt and braces: the dotenv loader must not put them back.
os.environ["CONTROLPLANE_ENV_FILE"] = os.devnull

# Nor may a test reach a live model provider.
os.environ["CONTROLPLANE_PROVIDER"] = "offline"
os.environ.pop("GEMINI_API_KEY", None)


@pytest.fixture(autouse=True)
def _no_live_transport(monkeypatch):
    """Re-assert the guard around every test, so one that sets a real endpoint
    cannot leak into the next."""
    yield
    for var in _LIVE_TRANSPORT_VARS:
        if var in os.environ and not os.environ[var].startswith(("http://127.0.0.1",
                                                                 "127.0.0.1")):
            if var in ("NOTIFY_API_URL", "SMTP_HOST"):
                monkeypatch.delenv(var, raising=False)


# --------------------------------------------------------------- corpus ---
# Tests exercise the real evidence path: the bundled documents are ingested
# through exactly the same code an upload uses. A plane with an empty corpus
# would route everything to the evidence floor and tell us nothing.
_CORPUS_CACHE = {}


def bundled_corpus(tmp_path_factory=None):
    """A Corpus with the repo's `corpus/` documents ingested. Built once."""
    from pathlib import Path as _P
    from python.controlplane.ingest import Corpus

    key = "shared"
    if key in _CORPUS_CACHE:
        return _CORPUS_CACHE[key]

    import tempfile
    root = _P(tempfile.mkdtemp(prefix="cp-corpus-"))
    corpus = Corpus(root)
    for doc in sorted((_P(__file__).parent / "corpus").glob("*/*.md")):
        corpus.add(doc.parent.name, doc.name, doc.read_bytes(),
                   origin="bundled", uploaded_by="test")
    _CORPUS_CACHE[key] = corpus
    return corpus


@pytest.fixture(scope="session")
def corpus():
    return bundled_corpus()


# ------------------------------------------------- demo tuning vs testing ---
# The shipped registry is tuned for a demo: Marketing starts a few questions
# away from its weekly reviewer capacity and Finance starts *over* its monthly
# spend budget, both on purpose, so the enforcement can be shown live rather
# than described. Those are presentation choices and a test that exercises a
# detector must not inherit them — otherwise every Finance test starts failing
# the day somebody adjusts a baseline for the pitch.
#
# So tests get headroom by default. The budget behaviour itself is tested
# explicitly, by setting the baselines the test needs.
@pytest.fixture(autouse=True)
def _budget_headroom_for_tests(monkeypatch):
    """Patched at `Registry.register`, not at `org.build`.

    The test modules do `from ...org import build`, which binds the function in
    their own namespace at import time — so replacing `org.build` afterwards
    changes nothing. Every registry in the process goes through `register`,
    whichever way it was built, so that is where the headroom belongs."""
    from python.controlplane.registry import Registry

    original = Registry.register

    def register_with_headroom(self, app):
        app.budget_inr_month = max(app.budget_inr_month,
                                   app.spend_baseline_inr * 4 + 10_000)
        app.review_minutes_week = max(app.review_minutes_week,
                                      app.review_baseline_minutes * 4 + 1000)
        return original(self, app)

    monkeypatch.setattr(Registry, "register", register_with_headroom)
    yield
