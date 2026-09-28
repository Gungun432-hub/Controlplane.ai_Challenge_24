"""The owner briefing, as an email.

Written for the person whose name is on the system — a recruiting manager, a
marketing lead — not for the platform team. Every advisory carries what is
wrong, **what to change**, and what happens if nothing changes, because a
warning without a remedy just moves the anxiety around.

Plain text is generated alongside the HTML rather than as an afterthought: a
governance notification that only renders in a client with images enabled is a
governance notification that gets missed.
"""
from __future__ import annotations

from html import escape
from typing import Any

BRAND = "#6D28D9"
INK = "#16161F"
MUTED = "#55556B"
LINE = "#DCDCE6"
SEV = {"high": "#D62839", "medium": "#B26A00", "low": "#00875A"}


def _money(n: float | None) -> str:
    return "₹" + f"{round(n or 0):,}"


def subject_line(brief: dict[str, Any]) -> str:
    f = brief.get("forecast") or {}
    sid, name = brief["systemId"], brief["name"]
    if f.get("state") == "exhausted":
        return f"[ControlPlane] {name} is over its monthly budget"
    if f.get("state") == "critical" and f.get("daysLeft") is not None:
        return (f"[ControlPlane] {name} runs out of budget in "
                f"{f['daysLeft']:.0f} days")
    high = [a for a in brief["advisories"] if a.get("severity") == "high"]
    if high:
        return f"[ControlPlane] {len(high)} item(s) need your attention on {name}"
    if brief["advisories"]:
        return f"[ControlPlane] Advisory for {name}"
    return f"[ControlPlane] {name} — all clear ({sid})"


def _forecast_text(f: dict[str, Any]) -> str | None:
    if not f.get("observable"):
        return None
    if f["state"] == "exhausted":
        return (f"You are {_money(abs(f['remainingInr']))} over a "
                f"{_money(f['budgetInr'])} monthly budget, spending about "
                f"{_money(f['perDayInr'])} a day.")
    if f.get("daysLeft") is None:
        return None
    on = f" — on {f['exhaustsOn']}" if f.get("exhaustsOn") else ""
    return (f"At about {_money(f['perDayInr'])} a day you have "
            f"{f['daysLeft']:.0f} days of budget left{on}. Projected month-end "
            f"spend is {_money(f['projectedMonthInr'])} against a "
            f"{_money(f['budgetInr'])} budget.")


def render(brief: dict[str, Any], note: str = "") -> tuple[str, str, str]:
    """Returns (subject, html, text)."""
    subject = subject_line(brief)
    f = brief.get("forecast") or {}
    forecast = _forecast_text(f)
    advisories = brief["advisories"]
    owner = brief["owner"]
    first = owner.split()[0] if owner else "there"

    # ------------------------------------------------------------ plain ---
    lines = [f"Hello {first},", ""]
    lines.append(f"This is an automated briefing from ControlPlane about "
                 f"{brief['name']} ({brief['systemId']}), the AI system you own in "
                 f"{brief['department']}.")
    lines.append("")
    if note:
        lines += [note.strip(), ""]
    if forecast:
        lines += ["BUDGET", forecast, ""]
    lines.append(f"Spend this month   {_money(brief['spendInr'])} of "
                 f"{_money(brief['budgetInr'])}  ({brief['budgetUsedPct']:.0f}%)")
    lines.append(f"Reviewer time      {brief['reviewMinutes']:.0f} of "
                 f"{brief['reviewBudgetMinutes']:.0f} minutes "
                 f"({brief['reviewUsedPct']:.0f}%)")
    lines.append(f"Decisions governed {brief['decisions']}")
    lines.append("")

    if advisories:
        lines.append(f"WHAT NEEDS YOUR ATTENTION ({len(advisories)})")
        lines.append("")
        for i, a in enumerate(advisories, 1):
            lines.append(f"{i}. [{a.get('severity', '').upper()}] {a['text']}")
            if a.get("fix"):
                lines.append(f"   What to change: {a['fix']}")
            if a.get("fixDetail"):
                lines.append(f"   {a['fixDetail']}")
            if a.get("impact"):
                lines.append(f"   If nothing changes: {a['impact']}")
            lines.append(f"   (rule {a['ruleId']} v{a.get('ruleVersion', '1.0')})")
            lines.append("")
    else:
        lines += ["Nothing needs your attention right now.", ""]

    lines += [
        "Every item above was derived by a versioned rule from recorded evidence,",
        "not by a model's opinion, and the decision behind each one can be replayed.",
        "",
        "— ControlPlane",
        f"Generated {brief['generatedAt']}",
    ]
    text = "\n".join(lines)

    # ------------------------------------------------------------- html ---
    def card(a: dict[str, Any]) -> str:
        colour = SEV.get(a.get("severity", ""), MUTED)
        rows = [f'<div style="font:600 11px/1.4 Arial,sans-serif;letter-spacing:.8px;'
                f'text-transform:uppercase;color:{colour}">'
                f'{escape(str(a.get("severity", "")))}</div>',
                f'<div style="font:600 15px/1.45 Arial,sans-serif;color:{INK};'
                f'margin:5px 0 10px">{escape(a["text"])}</div>']
        if a.get("fix"):
            rows.append(
                f'<div style="background:#F6F4FF;border-left:3px solid {BRAND};'
                f'padding:11px 13px;border-radius:0 6px 6px 0;margin-bottom:9px">'
                f'<div style="font:700 11px Arial,sans-serif;color:{BRAND};'
                f'letter-spacing:.6px;text-transform:uppercase;margin-bottom:4px">'
                f'What to change</div>'
                f'<div style="font:400 13.5px/1.55 Arial,sans-serif;color:{INK}">'
                f'{escape(a["fix"])}</div>'
                + (f'<div style="font:400 12.5px/1.55 Arial,sans-serif;color:{MUTED};'
                   f'margin-top:6px">{escape(a["fixDetail"])}</div>'
                   if a.get("fixDetail") else "")
                + '</div>')
        if a.get("impact"):
            rows.append(f'<div style="font:400 12.5px/1.5 Arial,sans-serif;color:{MUTED}">'
                        f'<b style="color:{INK}">If nothing changes:</b> '
                        f'{escape(a["impact"])}</div>')
        rows.append(f'<div style="font:400 11px Arial,sans-serif;color:#9494B2;'
                    f'margin-top:9px">rule {escape(a["ruleId"])} '
                    f'v{escape(str(a.get("ruleVersion", "1.0")))} · derived from recorded '
                    f'evidence</div>')
        return (f'<td style="padding:16px 18px;border:1px solid {LINE};'
                f'border-left:4px solid {colour};border-radius:8px;background:#fff">'
                + "".join(rows) + "</td>")

    stat = (lambda label, value, sub: (
        f'<td style="padding:12px 14px;border:1px solid {LINE};border-radius:8px;'
        f'background:#FAFAFD" width="33%">'
        f'<div style="font:600 10px Arial,sans-serif;letter-spacing:.9px;'
        f'text-transform:uppercase;color:{MUTED}">{escape(label)}</div>'
        f'<div style="font:700 19px Arial,sans-serif;color:{INK};margin-top:4px">'
        f'{escape(value)}</div>'
        f'<div style="font:400 11px Arial,sans-serif;color:{MUTED};margin-top:2px">'
        f'{escape(sub)}</div></td>'))

    body = [
        f'<div style="background:linear-gradient(97deg,#2E1C55,#241544);padding:20px 24px;'
        f'border-radius:10px 10px 0 0">'
        f'<div style="font:700 19px Arial,sans-serif;color:#F2ECFF">Control'
        f'<span style="color:#B57BFF">Plane</span></div>'
        f'<div style="font:400 12px Arial,sans-serif;color:#C9BEE4;margin-top:3px">'
        f'Automated briefing for the owner of an AI system</div></div>',

        f'<div style="padding:24px">'
        f'<div style="font:400 15px/1.6 Arial,sans-serif;color:{INK}">'
        f'Hello {escape(first)},</div>'
        f'<div style="font:400 14px/1.65 Arial,sans-serif;color:{MUTED};margin-top:10px">'
        f'This is an automated briefing about <b style="color:{INK}">'
        f'{escape(brief["name"])}</b>, the AI system you own in '
        f'{escape(brief["department"])}.</div>',
    ]

    if note:
        body.append(f'<div style="font:400 14px/1.6 Arial,sans-serif;color:{INK};'
                    f'background:#FAFAFD;border:1px solid {LINE};border-radius:8px;'
                    f'padding:12px 14px;margin-top:14px">{escape(note)}</div>')

    if forecast:
        urgent = f.get("state") in ("critical", "exhausted")
        body.append(
            f'<div style="background:{"#FDF2F3" if urgent else "#FFF8EC"};'
            f'border:1px solid {"#D62839" if urgent else "#B26A00"};border-radius:8px;'
            f'padding:14px 16px;margin-top:18px">'
            f'<div style="font:700 11px Arial,sans-serif;letter-spacing:.8px;'
            f'text-transform:uppercase;color:{"#D62839" if urgent else "#B26A00"}">'
            f'Budget forecast</div>'
            f'<div style="font:400 14px/1.6 Arial,sans-serif;color:{INK};margin-top:5px">'
            f'{escape(forecast)}</div></div>')

    body.append(
        f'<table cellpadding="0" cellspacing="8" width="100%" '
        f'style="margin:16px -8px 0"><tr>'
        + stat("Spend this month", f"{_money(brief['spendInr'])}",
               f"of {_money(brief['budgetInr'])} · {brief['budgetUsedPct']:.0f}%")
        + stat("Reviewer time", f"{brief['reviewMinutes']:.0f} min",
               f"of {brief['reviewBudgetMinutes']:.0f} · {brief['reviewUsedPct']:.0f}%")
        + stat("Decisions governed", f"{brief['decisions']}",
               f"exposure {brief['exposurePer100']}/100 requests")
        + '</tr></table>')

    if advisories:
        body.append(f'<div style="font:700 13px Arial,sans-serif;color:{INK};'
                    f'margin:26px 0 12px">What needs your attention '
                    f'({len(advisories)})</div>')
        body.append('<table cellpadding="0" cellspacing="0" width="100%">'
                    + "".join(f'<tr>{card(a)}</tr><tr><td height="10"></td></tr>'
                              for a in advisories)
                    + '</table>')
    else:
        body.append(f'<div style="font:400 14px Arial,sans-serif;color:#00875A;'
                    f'background:#F0FBF6;border:1px solid #00875A;border-radius:8px;'
                    f'padding:14px 16px;margin-top:20px">'
                    f'Nothing needs your attention right now.</div>')

    body.append(
        f'<div style="font:400 12px/1.6 Arial,sans-serif;color:{MUTED};'
        f'border-top:1px solid {LINE};margin-top:26px;padding-top:14px">'
        f'Every item above was derived by a versioned rule from recorded evidence, '
        f'not by a model\'s opinion, and the decision behind each one can be '
        f'replayed under the policy that was in force at the time.'
        f'<br><br>— ControlPlane · generated {escape(brief["generatedAt"])}</div>'
        f'</div>')

    html = (f'<!DOCTYPE html><html><body style="margin:0;padding:24px;'
            f'background:#F6F6FA"><table cellpadding="0" cellspacing="0" width="100%" '
            f'style="max-width:660px;margin:0 auto;background:#fff;border-radius:10px;'
            f'border:1px solid {LINE};overflow:hidden"><tr><td>'
            + "".join(body) + '</td></tr></table></body></html>')

    return subject, html, text
