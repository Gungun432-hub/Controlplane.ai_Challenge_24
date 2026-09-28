"""Owner notifications.

A control plane that can see a system is about to run out of money, and can only
show that on a screen nobody is watching, has done half the job. The mentor's
phrasing: *you give a warning, and along with that you say how to fix the
problem — that is your value add.*

Two transports, chosen by environment, never by code change:

* **https** — an email API over port 443 (Resend, Brevo, Mailgun and friends all
  take the same shape). Prefer this. Conference and campus networks routinely
  block outbound SMTP; almost nothing blocks 443.
* **smtp**  — a normal SMTP server with STARTTLS or implicit TLS.

If neither is configured the result is an honest failure with the composed
message attached, never a silent success. The caller records the attempt either
way, because a notification that was never delivered is exactly the kind of fact
this system exists to surface rather than hide.

**No credential is ever read from source, returned in a response, or written to
the ledger.** Configure them in `.env`, which is gitignored.
"""
from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")

MAX_RECIPIENTS = 5
TIMEOUT_S = float(os.getenv("NOTIFY_TIMEOUT_S", "12"))


def valid_address(addr: str) -> bool:
    return bool(_EMAIL.match((addr or "").strip())) and len(addr.strip()) <= 254


def available() -> list[str]:
    """Every transport that is configured, best first.

    Both can be set at once. HTTPS goes over 443 and works on networks that
    block SMTP; SMTP can reach any recipient without a verified sending domain.
    Neither property alone is enough for a demo on someone else's wifi, so if
    both are configured the second is tried when the first fails."""
    out = []
    if os.getenv("NOTIFY_API_URL") and os.getenv("NOTIFY_API_KEY"):
        out.append("https")
    if os.getenv("SMTP_HOST") and os.getenv("SMTP_USER"):
        out.append("smtp")
    if os.getenv("NOTIFY_PREFER", "").lower() == "smtp" and "smtp" in out:
        out.sort(key=lambda t: t != "smtp")
    return out


def transport_name() -> str:
    """Which transport will be tried first, without revealing anything about it."""
    got = available()
    return got[0] if got else "none"


def configured() -> dict[str, Any]:
    """What the console shows so an operator knows whether Send will work —
    the transport and the from-address only. Never the credential."""
    got = available()
    return {
        "transport": got[0] if got else "none",
        "transports": got,
        "ready": bool(got),
        "from": os.getenv("NOTIFY_FROM", "") if got else "",
        "note": ("no transport configured; set NOTIFY_API_URL + NOTIFY_API_KEY, "
                 "or SMTP_HOST + SMTP_USER + SMTP_PASSWORD in .env"
                 if not got else
                 "a second transport is configured and will be tried if the first fails"
                 if len(got) > 1 else ""),
    }


def _scrub(text: str) -> str:
    """Strip anything that looks like a credential.

    Both an exception message *and* a provider's own error body can echo a key
    back at us — a 401 that quotes the key it rejected is common — and either
    one ends up in the ledger and on screen."""
    for var in ("NOTIFY_API_KEY", "SMTP_PASSWORD", "SMTP_USER", "GEMINI_API_KEY"):
        secret = os.getenv(var)
        if secret and len(secret) > 3:
            text = text.replace(secret, "***")
    text = re.sub(r"(?i)(bearer|api[-_ ]?key|token)\s*[:=]?\s*\S+", r"\1 ***", text)
    return text[:300]


def _redact(exc: Exception) -> str:
    return _scrub(f"{type(exc).__name__}: {exc}")


# ----------------------------------------------------------------- https ---
def _send_https(to: list[str], subject: str, html: str, text: str) -> dict[str, Any]:
    import httpx                                    # lazy: offline needs no client

    url = os.environ["NOTIFY_API_URL"]
    key = os.environ["NOTIFY_API_KEY"]
    sender = os.getenv("NOTIFY_FROM") or ""
    style = (os.getenv("NOTIFY_API_STYLE") or "resend").lower()

    if style == "brevo":
        headers = {"api-key": key, "content-type": "application/json"}
        name, _, addr = sender.rpartition(" ")
        payload = {
            "sender": {"email": addr.strip("<>") or sender, "name": name or "ControlPlane"},
            "to": [{"email": a} for a in to],
            "subject": subject, "htmlContent": html, "textContent": text,
        }
    else:                                            # resend / mailgun-compatible
        headers = {"authorization": f"Bearer {key}", "content-type": "application/json"}
        payload = {"from": sender, "to": to, "subject": subject,
                   "html": html, "text": text}

    with httpx.Client(timeout=TIMEOUT_S) as client:
        r = client.post(url, json=payload, headers=headers)
    if r.status_code >= 400:
        return {"ok": False, "transport": "https",
                "detail": _scrub(f"the email API returned HTTP {r.status_code}: "
                                 f"{r.text[:200]}")}
    ident = ""
    try:
        body = r.json()
        ident = str(body.get("id") or body.get("messageId") or "")
    except Exception:                                                # noqa: BLE001
        pass
    return {"ok": True, "transport": "https", "detail": "accepted by the email API",
            "messageId": ident}


# ------------------------------------------------------------------ smtp ---
def _send_smtp(to: list[str], subject: str, html: str, text: str) -> dict[str, Any]:
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("NOTIFY_FROM") or user

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_S, context=context) as smtp:
            if password:
                smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=TIMEOUT_S) as smtp:
            smtp.ehlo()
            if os.getenv("SMTP_STARTTLS", "1") != "0":
                smtp.starttls(context=context)
                smtp.ehlo()
            if password:
                smtp.login(user, password)
            smtp.send_message(msg)
    return {"ok": True, "transport": "smtp", "detail": f"handed to {host}:{port}"}


# ------------------------------------------------------------------ send ---
def send(to: list[str], subject: str, html: str, text: str) -> dict[str, Any]:
    """Deliver, or explain why not. Never raises at the caller."""
    clean = [a.strip() for a in to if valid_address(a)]
    rejected = [a for a in to if not valid_address(a)]
    if not clean:
        return {"ok": False, "transport": transport_name(),
                "detail": "no valid recipient address", "rejected": rejected}
    if len(clean) > MAX_RECIPIENTS:
        return {"ok": False, "transport": transport_name(),
                "detail": f"at most {MAX_RECIPIENTS} recipients per notification"}

    got = available()
    if not got:
        return {"ok": False, "transport": "none", "rejected": rejected,
                "detail": "no email transport is configured; the message was composed "
                          "but not sent"}

    attempts: list[dict[str, Any]] = []
    for name in got:
        if name == "https" and not os.getenv("NOTIFY_FROM"):
            attempts.append({"transport": "https",
                             "detail": "NOTIFY_FROM is required for the https transport"})
            continue
        try:
            result = (_send_https(clean, subject, html, text) if name == "https"
                      else _send_smtp(clean, subject, html, text))
        except Exception as exc:                                     # noqa: BLE001
            result = {"ok": False, "transport": name, "detail": _redact(exc)}
        if result.get("ok"):
            result["recipients"] = clean
            if attempts:
                result["fellBackFrom"] = attempts
            if rejected:
                result["rejected"] = rejected
            return result
        attempts.append({"transport": name, "detail": result.get("detail")})

    # Everything failed. Report each attempt rather than only the last, so the
    # reason is legible instead of "it did not work".
    return {"ok": False, "transport": got[0], "recipients": clean,
            "rejected": rejected, "attempts": attempts,
            "detail": " · ".join(f"[{a['transport']}] {a['detail']}" for a in attempts)}
