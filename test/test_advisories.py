"""Advisories, the burn-rate forecast, and owner notification.

The mentor's critique of the first build was that a recommendation written for
the platform team is not actionable by the person who owns the system. These
tests assert the three things he asked for: a forecast *before* the money is
gone, a concrete fix rather than a control name, and a notification that is
itself recorded.
"""
from __future__ import annotations

import os
import smtplib
import ssl
import sys
import threading
import time
from email import message_from_bytes
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from python.controlplane.briefing import render, subject_line          # noqa: E402
from python.controlplane.ledger import JsonlLedger                     # noqa: E402
from python.controlplane.org import build                              # noqa: E402
from python.controlplane.plane import ControlPlane                     # noqa: E402
from python.controlplane.providers import OfflineProvider              # noqa: E402


@pytest.fixture()
def seeded(tmp_path):
    """Seeded once per module and re-pointed at a fresh ledger per test.

    Seeding is the expensive part and it is deterministic, so the decision
    history is built once. Anything a test mutates — recommendations, overlays,
    the ledger — is reset, so tests stay independent."""
    import copy
    cp = _BASE
    cp.ledger = JsonlLedger(tmp_path / "l.jsonl", "k")
    cp.recommendations = copy.deepcopy(_BASE_RECS)
    cp.ledger_errors = []
    cp.overlays = []
    return cp


def _build_base():
    import seed_history
    from conftest import bundled_corpus
    cp = ControlPlane(build(), OfflineProvider(),
                      JsonlLedger(Path(os.environ.get("TMPDIR", "/tmp")) /
                                  "cp-advisory-base.jsonl", "k"),
                      corpus=bundled_corpus())
    seed_history.seed(cp, 70)
    return cp


_BASE = _build_base()
_BASE_RECS = [dict(r) for r in _BASE.recommendations]


# ------------------------------------------------------------- forecast ---
class TestTheForecastWarnsBeforeTheMoneyIsGone:
    def test_a_rate_is_derived_and_its_window_is_reported(self, seeded):
        b = seeded.burn_rate("marketing-copilot")
        assert b["observable"] is True
        assert b["perDayInr"] > 0
        assert b["daysElapsed"] >= 3, "the guard for early-in-the-month must not have fired"
        assert b["observedWindowDays"] > 1, "the seeded window must span days, not minutes"

    def test_the_forecast_total_matches_the_portfolio_card(self, seeded):
        """A forecast that disagrees with the number printed above it is worse
        than no forecast."""
        for sid in [a for a in seeded.registry.applications]:
            card = seeded.project(sid)
            fc = seeded.burn_rate(sid)
            assert abs(card["spendInr"] - fc["spendInr"]) < 0.01, sid
            assert card["budgetInr"] == fc["budgetInr"], sid

    def test_a_system_inside_its_budget_can_still_be_critical(self, seeded):
        """The whole point. The card says governed; the forecast says two days."""
        card = seeded.project("marketing-copilot")
        fc = seeded.burn_rate("marketing-copilot")
        assert card["status"] == "governed"
        assert card["budgetUsedPct"] < 100
        assert fc["state"] in ("critical", "warning"), fc
        assert fc["daysLeft"] is not None and fc["daysLeft"] < 8

    def test_an_overspent_system_reads_exhausted(self, seeded):
        fc = seeded.burn_rate("finance-decide")
        assert fc["state"] == "exhausted"
        assert fc["remainingInr"] < 0

    def test_too_early_in_the_month_declines_to_project(self, seeded, monkeypatch):
        """On the first of the month, month-to-date is a few hours. Dividing by
        it would report every system as critical."""
        import datetime as real_dt
        from python.controlplane import plane as plane_mod

        class FirstOfMonth(real_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 1, 9, 0, tzinfo=tz or real_dt.timezone.utc)

        monkeypatch.setattr(plane_mod, "datetime", FirstOfMonth)
        b = seeded.burn_rate("marketing-copilot")
        assert b["observable"] is False
        assert "too early" in b["reason"]

    def test_the_forecast_rule_fires_and_names_the_day(self, seeded):
        rules = [r for r in seeded.recommendations
                 if r["ruleId"] == "COST.BURN_RATE_PROJECTION"]
        assert rules, "no burn-rate advisory was produced"
        r = rules[-1]
        assert "runs out of budget" in r["text"]
        assert r["fix"] and r["impact"]


# ----------------------------------------------------- actionable advice ---
class TestEveryAdvisoryTellsYouWhatToChange:
    def test_no_advisory_ships_without_a_fix(self, seeded):
        seeded.turn("support-copilot",
                    "Share account details for card 4539578763621486, Rajesh in Bandra 400050.")
        assert seeded.recommendations
        missing = [r["ruleId"] for r in seeded.recommendations if not r.get("fix")]
        assert not missing, f"advisories with no remediation: {sorted(set(missing))}"

    def test_the_fix_is_a_change_not_a_control_name(self, seeded):
        """'suspend' is what an operator does. The owner needs a code change."""
        controls = {"suspend", "quarantine", "tool_restricted", "require_human",
                    "promote_inline", "tighten", "enable_cache"}
        for r in seeded.recommendations:
            assert r["fix"].strip().lower() not in controls
            assert len(r["fix"]) > 40, r["ruleId"]

    def test_the_privacy_advisory_says_mask(self, seeded):
        seeded.turn("support-copilot",
                    "Share account details for card 4539578763621486 please.")
        priv = [r for r in seeded.recommendations
                if r["ruleId"] == "PRIVACY.UNMASKED_IDENTIFIERS"]
        assert priv, "no privacy advisory"
        assert "mask" in priv[-1]["fix"].lower()

    def test_a_briefing_deduplicates_repeated_rules(self, seeded):
        b = seeded.advisories("marketing-copilot")
        ids = [a["ruleId"] for a in b["advisories"]]
        assert len(ids) == len(set(ids)), "the same finding appears more than once"

    def test_high_severity_sorts_first(self, seeded):
        b = seeded.advisories("marketing-copilot")
        order = [a["severity"] for a in b["advisories"]]
        rank = {"high": 0, "medium": 1, "low": 2}
        assert order == sorted(order, key=lambda x: rank.get(x, 9))

    def test_an_unknown_system_is_refused(self, seeded):
        with pytest.raises(ValueError, match="unknown system"):
            seeded.advisories("not-a-system")


# ------------------------------------------------------------- briefing ---
class TestTheBriefingReadsLikeItIsForAPerson:
    def test_it_is_addressed_to_the_owner_by_name(self, seeded):
        b = seeded.advisories("marketing-copilot")
        _, html, text = render(b)
        assert b["owner"].split()[0] in text
        assert b["owner"].split()[0] in html

    def test_the_subject_leads_with_the_forecast(self, seeded):
        b = seeded.advisories("marketing-copilot")
        assert "runs out of budget" in subject_line(b)

    def test_plain_text_carries_every_fix(self, seeded):
        b = seeded.advisories("marketing-copilot")
        _, _, text = render(b)
        for a in b["advisories"]:
            assert a["fix"][:40] in text, a["ruleId"]

    def test_an_operator_note_is_escaped_not_injected(self, seeded):
        b = seeded.advisories("marketing-copilot")
        _, html, _ = render(b, note='<script>alert("x")</script>')
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_an_all_clear_briefing_still_renders(self, seeded):
        b = seeded.advisories("recruit-screen")
        b["advisories"] = []
        subject, html, text = render(b)
        assert "all clear" in subject or "Advisory" in subject
        assert "Nothing needs your attention" in text


# --------------------------------------------------------- notification ---
class TestTheNotificationIsItselfGoverned:
    def test_an_unconfigured_transport_fails_honestly(self, seeded, monkeypatch):
        for var in ("NOTIFY_API_URL", "NOTIFY_API_KEY", "SMTP_HOST", "SMTP_USER"):
            monkeypatch.delenv(var, raising=False)
        out = seeded.notify_owner("marketing-copilot", ["owner@example.com"], actor="Arun")
        assert out["ok"] is False
        assert "no email transport" in out["detail"]
        assert out["html"], "the composed message must still come back"

    def test_a_failed_send_is_still_recorded(self, seeded, monkeypatch):
        for var in ("NOTIFY_API_URL", "NOTIFY_API_KEY", "SMTP_HOST", "SMTP_USER"):
            monkeypatch.delenv(var, raising=False)
        seeded.notify_owner("marketing-copilot", ["owner@example.com"], actor="Arun")
        events = [e["record"]["event"] for e in seeded.ledger.read(limit=10 ** 6)]
        assert "notification.failed" in events, (
            "a warning that never arrived must not vanish from the record")

    def test_a_bad_address_is_rejected_before_any_send(self, seeded):
        out = seeded.notify_owner("marketing-copilot", ["not-an-email"], actor="Arun")
        assert out["ok"] is False
        assert "no valid recipient" in out["detail"]

    def test_the_ledger_never_holds_a_credential(self, seeded, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "localhost")
        monkeypatch.setenv("SMTP_USER", "demo@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "super-secret-app-password")
        monkeypatch.setenv("SMTP_PORT", "1")          # refused instantly
        seeded.notify_owner("marketing-copilot", ["owner@example.com"], actor="Arun")
        blob = Path(seeded.ledger.path).read_text(encoding="utf-8")
        assert "super-secret-app-password" not in blob

    def test_the_config_endpoint_never_returns_the_key(self, monkeypatch):
        from python.controlplane.notify import configured
        monkeypatch.setenv("NOTIFY_API_URL", "https://example.test/send")
        monkeypatch.setenv("NOTIFY_API_KEY", "re_live_abc123")
        monkeypatch.setenv("NOTIFY_FROM", "ControlPlane <cp@example.test>")
        c = configured()
        assert c["ready"] is True and c["transport"] == "https"
        assert "re_live_abc123" not in repr(c)

    def test_more_than_five_recipients_is_refused(self, seeded, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "localhost")
        monkeypatch.setenv("SMTP_USER", "demo@example.com")
        out = seeded.notify_owner("marketing-copilot",
                                  [f"a{i}@example.com" for i in range(6)], actor="Arun")
        assert out["ok"] is False and "at most 5" in out["detail"]


# ------------------------------------------ a real SMTP conversation ---
class _Catcher(threading.Thread):
    """A tiny SMTP server. Proves the transport really speaks SMTP rather than
    that a mock was called."""

    def __init__(self):
        super().__init__(daemon=True)
        import socket
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.data = b""

    def run(self):
        conn, _ = self.sock.accept()
        conn.sendall(b"220 test ESMTP\r\n")
        body, in_data = b"", False
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            body += chunk
            if in_data:
                if b"\r\n.\r\n" in body:
                    conn.sendall(b"250 OK queued\r\n")
                    in_data = False
                continue
            line = chunk.strip().upper()
            if line.startswith(b"EHLO") or line.startswith(b"HELO"):
                conn.sendall(b"250-test\r\n250 HELP\r\n")
            elif line.startswith(b"MAIL") or line.startswith(b"RCPT"):
                conn.sendall(b"250 OK\r\n")
            elif line.startswith(b"DATA"):
                conn.sendall(b"354 go ahead\r\n")
                in_data = True
            elif line.startswith(b"QUIT"):
                conn.sendall(b"221 bye\r\n")
                break
            else:
                conn.sendall(b"250 OK\r\n")
        self.data = body
        conn.close()


class TestTheSmtpTransportReallySpeaksSmtp:
    def test_a_briefing_is_delivered_and_recorded(self, seeded, monkeypatch):
        server = _Catcher()
        server.start()
        monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
        monkeypatch.setenv("SMTP_PORT", str(server.port))
        monkeypatch.setenv("SMTP_USER", "demo@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "")
        monkeypatch.setenv("SMTP_STARTTLS", "0")
        monkeypatch.setenv("NOTIFY_FROM", "ControlPlane <demo@example.com>")

        out = seeded.notify_owner("marketing-copilot", ["sana@example.com"],
                                  actor="Arun Mehta", note="From the finale demo.")
        server.join(timeout=5)

        assert out["ok"] is True, out["detail"]
        assert out["transport"] == "smtp"
        wire = server.data.decode("utf-8", "replace")
        assert "sana@example.com" in wire
        assert "runs out of budget" in wire.replace("=\r\n", "")

        events = [e["record"] for e in seeded.ledger.read(limit=10 ** 6)
                  if e["record"].get("event") == "notification.sent"]
        assert events, "a delivered notification must be recorded"
        assert events[-1]["actor"] == "Arun Mehta"
        assert events[-1]["delivered"] is True
        assert events[-1]["ruleIds"], "the record must name the advisories that were sent"


# --------------------------------------- the https transport, really posted ---
class _Api(threading.Thread):
    """A tiny HTTP server standing in for Resend / Brevo / Mailgun.

    The https transport exists because conference and campus networks block
    outbound SMTP while leaving 443 open — measured, not assumed: from the build
    container smtp.gmail.com:587 and :465 are both refused and api.resend.com:443
    connects."""

    def __init__(self, status=200, body=b'{"id":"msg_123"}'):
        super().__init__(daemon=True)
        from http.server import BaseHTTPRequestHandler, HTTPServer
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("content-length", 0))
                captured["body"] = self.rfile.read(n)
                captured["headers"] = dict(self.headers)
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.captured = captured
        self.srv = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]

    def run(self):
        self.srv.handle_request()


class TestTheHttpsTransportReallyPosts:
    def _env(self, monkeypatch, port, style="resend"):
        for var in ("SMTP_HOST", "SMTP_USER"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("NOTIFY_API_URL", f"http://127.0.0.1:{port}/emails")
        monkeypatch.setenv("NOTIFY_API_KEY", "re_test_secret_key")
        monkeypatch.setenv("NOTIFY_API_STYLE", style)
        monkeypatch.setenv("NOTIFY_FROM", "ControlPlane <cp@example.test>")

    def test_a_resend_shaped_payload_is_posted_and_recorded(self, seeded, monkeypatch):
        import json
        api = _Api(); api.start()
        self._env(monkeypatch, api.port)
        out = seeded.notify_owner("marketing-copilot", ["sana@example.test"],
                                  actor="Arun Mehta")
        api.join(timeout=5)

        assert out["ok"] is True, out["detail"]
        assert out["transport"] == "https"
        sent = json.loads(api.captured["body"])
        assert sent["to"] == ["sana@example.test"]
        assert "runs out of budget" in sent["subject"]
        assert "What to change" in sent["html"]
        assert api.captured["headers"]["authorization"] == "Bearer re_test_secret_key"

        events = [e["record"] for e in seeded.ledger.read(limit=10 ** 6)
                  if e["record"].get("event") == "notification.sent"]
        assert events and events[-1]["transport"] == "https"

    def test_a_brevo_shaped_payload_uses_its_own_envelope(self, seeded, monkeypatch):
        import json
        api = _Api(); api.start()
        self._env(monkeypatch, api.port, style="brevo")
        out = seeded.notify_owner("marketing-copilot", ["sana@example.test"], actor="Arun")
        api.join(timeout=5)
        assert out["ok"] is True, out["detail"]
        sent = json.loads(api.captured["body"])
        assert sent["to"] == [{"email": "sana@example.test"}]
        assert api.captured["headers"]["api-key"] == "re_test_secret_key"

    def test_a_provider_error_is_reported_not_swallowed(self, seeded, monkeypatch):
        api = _Api(status=422, body=b'{"message":"domain not verified"}')
        api.start()
        self._env(monkeypatch, api.port)
        out = seeded.notify_owner("marketing-copilot", ["sana@example.test"], actor="Arun")
        api.join(timeout=5)
        assert out["ok"] is False
        assert "422" in out["detail"] and "domain not verified" in out["detail"]
        events = [e["record"]["event"] for e in seeded.ledger.read(limit=10 ** 6)]
        assert "notification.failed" in events

    def test_a_key_echoed_back_by_a_provider_is_redacted(self, seeded, monkeypatch):
        api = _Api(status=401, body=b'{"error":"invalid key re_test_secret_key"}')
        api.start()
        self._env(monkeypatch, api.port)
        out = seeded.notify_owner("marketing-copilot", ["sana@example.test"], actor="Arun")
        api.join(timeout=5)
        assert out["ok"] is False
        assert "re_test_secret_key" not in out["detail"]
        assert "re_test_secret_key" not in Path(seeded.ledger.path).read_text(
            encoding="utf-8")


# --------------------------------------------------- owners, editable & durable ---
class TestOwnershipIsEditableAndRecorded:
    def test_an_owner_and_address_can_be_changed(self, seeded):
        out = seeded.set_owner("it-ops-agent", actor="Arun Mehta",
                               owner="Nandita Rao", owner_email="nandita@example.com")
        assert out["owner"] == "Nandita Rao"
        assert out["previous"]["owner"] == "Priya Nair"
        assert seeded.registry.get("it-ops-agent").owner_email == "nandita@example.com"

    def test_the_change_is_in_the_ledger(self, seeded):
        seeded.set_owner("it-ops-agent", actor="Arun Mehta", owner="Nandita Rao")
        kinds = [e["record"]["event"] for e in seeded.ledger.read(limit=10 ** 6)]
        assert "owner.changed" in kinds

    def test_the_briefing_follows_the_new_owner(self, seeded):
        seeded.set_owner("marketing-copilot", actor="Arun", owner="Kabir Shah",
                         owner_email="kabir@example.com")
        b = seeded.advisories("marketing-copilot")
        assert b["owner"] == "Kabir Shah" and b["ownerEmail"] == "kabir@example.com"
        _, _, text = render(b)
        assert "Hello Kabir" in text

    def test_a_bad_address_is_refused(self, seeded):
        with pytest.raises(ValueError, match="not a valid email"):
            seeded.set_owner("marketing-copilot", actor="Arun", owner_email="nope")

    def test_an_empty_name_is_refused(self, seeded):
        with pytest.raises(ValueError, match="cannot be empty"):
            seeded.set_owner("marketing-copilot", actor="Arun", owner="   ")

    def test_it_survives_a_restart(self, tmp_path):
        import seed_history
        path = tmp_path / "own.jsonl"
        from conftest import bundled_corpus
        first = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                             corpus=bundled_corpus())
        seed_history.seed(first, 12)
        first.set_owner("it-ops-agent", actor="Arun", owner="Nandita Rao",
                        owner_email="nandita@example.com")
        second = ControlPlane(build(), OfflineProvider(), JsonlLedger(path, "k"),
                              corpus=bundled_corpus())
        rec = second.recover()
        assert rec["owners"] == 1
        app = second.registry.get("it-ops-agent")
        assert app.owner == "Nandita Rao" and app.owner_email == "nandita@example.com"


class TestTransportFallback:
    def test_smtp_is_tried_when_the_api_fails(self, seeded, monkeypatch):
        """Neither transport alone is enough on someone else's wifi: HTTPS
        survives a blocked SMTP port, SMTP reaches recipients an unverified
        sending domain cannot."""
        api = _Api(status=403, body=b'{"message":"domain not verified"}')
        api.start()
        smtp = _Catcher()
        smtp.start()
        monkeypatch.setenv("NOTIFY_API_URL", f"http://127.0.0.1:{api.port}/emails")
        monkeypatch.setenv("NOTIFY_API_KEY", "k")
        monkeypatch.setenv("NOTIFY_FROM", "ControlPlane <cp@example.test>")
        monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
        monkeypatch.setenv("SMTP_PORT", str(smtp.port))
        monkeypatch.setenv("SMTP_USER", "demo@example.test")
        monkeypatch.setenv("SMTP_PASSWORD", "")
        monkeypatch.setenv("SMTP_STARTTLS", "0")

        out = seeded.notify_owner("marketing-copilot", ["judge@example.test"],
                                  actor="Arun")
        api.join(timeout=5); smtp.join(timeout=5)

        assert out["ok"] is True, out["detail"]
        assert out["transport"] == "smtp", "it should have fallen back"
        assert "judge@example.test" in smtp.data.decode("utf-8", "replace")

    def test_when_both_fail_every_reason_is_reported(self, seeded, monkeypatch):
        monkeypatch.setenv("NOTIFY_API_URL", "http://127.0.0.1:1/emails")
        monkeypatch.setenv("NOTIFY_API_KEY", "k")
        monkeypatch.setenv("NOTIFY_FROM", "ControlPlane <cp@example.test>")
        monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
        monkeypatch.setenv("SMTP_PORT", "1")
        monkeypatch.setenv("SMTP_USER", "demo@example.test")
        out = seeded.notify_owner("marketing-copilot", ["a@b.co"], actor="Arun")
        assert out["ok"] is False
        assert "[https]" in out["detail"] and "[smtp]" in out["detail"]


class TestTheSuiteCannotSendRealEmail:
    """This file exists because it nearly happened.

    Once `.env` held working Resend credentials, the dotenv loader put them into
    the environment at import time and a test that expected 'no transport
    configured' instead delivered a real message. `conftest.py` strips them; this
    asserts the guard is actually in force, so nobody re-introduces it."""

    def test_no_live_transport_is_configured_during_tests(self):
        import os
        for var in ("NOTIFY_API_URL", "NOTIFY_API_KEY", "SMTP_HOST", "SMTP_USER"):
            value = os.environ.get(var, "")
            assert not value or value.startswith(("http://127.0.0.1", "127.0.0.1")), (
                f"{var} points somewhere real during a test run")

    def test_the_dotenv_loader_is_pointed_at_nothing(self):
        import os
        from python.controlplane.env import load
        assert os.environ.get("CONTROLPLANE_ENV_FILE") == os.devnull
        assert load() == [], "the real .env was read during a test run"

    def test_a_send_with_the_guard_in_place_reaches_no_provider(self, seeded):
        out = seeded.notify_owner("marketing-copilot", ["nobody@example.invalid"],
                                  actor="test")
        assert out["ok"] is False
        assert out["transport"] == "none"
