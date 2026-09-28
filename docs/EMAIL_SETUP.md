# Sending the owner briefing for real

> **STATUS: DONE.** `notifications.controlplane-demo.world` is verified on
> Resend, the key is in `.env`, and delivery to arbitrary recipients is proven
> live. The rest of this file is the reasoning and the fallback plan — you do not
> need to do anything to make email work.

What Sir asked for, built: pick a branch, read its advisories, type an address,
send. This is how you make it actually deliver — and the one thing I changed
about your spec.

---

## The one change I made to your plan

> *"we can give you a mail id and details too for you to send the mail from that
> will be statically in the code"*

**I put them in `.env` instead, not in the code.** Three reasons, and none of
them is pedantry:

1. The repo goes to Sir, and possibly to Accenture. A password in a tracked file
   is a password you have published.
2. You have already had one credential exposed this way this month — the Gemini
   key, which is why it needs rotating.
3. It costs you nothing. `.env` is already gitignored, the app already reads it,
   and nothing about the demo changes.

Everything else is exactly as you described: the recipient is **typed at the
moment you send**, never stored, so you can put a judge's address in live.

---

## Two transports — and you want the HTTPS one

This matters more than it sounds.

**Measured from our build container:**

```
smtp.gmail.com:587   blocked
smtp.gmail.com:465   blocked
api.resend.com:443   OPEN
```

Conference and corporate networks block outbound SMTP ports as a matter of
routine, because that is how compromised laptops send spam. They essentially
never block 443, because that is the web.

**If you demo over venue wifi, SMTP may simply not connect.** An HTTPS email API
goes out over the same port as the rest of your traffic.

So: **set up the HTTPS transport as your primary, and keep SMTP configured as a
fallback you can switch to with one line.** Both are supported; the code path is
identical from the button's point of view.

---

## Option A — HTTPS email API  ⭐ recommended

Any of Resend, Brevo or Mailgun works; the code speaks both common payload
shapes. Pick one, verify a sender address (they all require this — it takes a
few minutes and an email confirmation), and get an API key.

In `.env`:

```ini
NOTIFY_FROM=ControlPlane <alerts@yourverifieddomain.com>
NOTIFY_API_URL=https://api.resend.com/emails
NOTIFY_API_KEY=your_key_here
NOTIFY_API_STYLE=resend
```

Brevo instead:

```ini
NOTIFY_API_URL=https://api.brevo.com/v3/smtp/email
NOTIFY_API_STYLE=brevo
```

**Do this part early.** Every provider makes you verify a sender before you can
mail arbitrary recipients, and some free tiers will only send to your *own*
verified address until a domain is verified. **Test sending to an address that
is not yours, this week** — not on the morning of the finale. If it only sends
to your own inbox, the judge-inbox moment does not work and you need to know that
now.

## Option B — Gmail SMTP

Needs an **App Password**, not your Google password. Enable 2-step verification,
then Google Account → Security → App passwords.

```ini
NOTIFY_FROM=Your Name <you@gmail.com>
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-16-char-app-password
SMTP_STARTTLS=1
```

Works fine on home and most campus wifi. **Test it on the venue network the day
before if you possibly can.**

---

## Checking it works

Start the server, open <http://localhost:8000/advisor>. The masthead pill tells
you the truth before you press anything:

| Pill | Meaning |
|---|---|
| `email not configured` | Send will compose and record, but deliver nothing |
| `email · https` | Ready, going out over 443 |
| `email · smtp` | Ready, going out over SMTP |

Then: pick **Marketing Copilot**, type your own address, press **Preview the
email**, read it, press **Send to owner**. Check your inbox — and your spam
folder, which is where a first message from a new sender usually lands.

---

## The judge-inbox moment

Your instinct here is good and it is the strongest version of this feature. Two
notes on doing it well.

**Ask for the address live rather than pre-loading it.** The input is empty by
design. Saying *"could someone give me an email address?"*, typing it in front of
them, and pressing send is dramatically more convincing than a pre-filled field,
because a pre-filled field could be faked and a typed one could not. It also
removes the risk of emailing a judge who did not consent.

**Have a fallback ready.** Use a teammate's phone, unlocked, on the table. If the
network eats it, you are not standing there waiting for an inbox that never
refreshes.

**Say the honest sentence while it sends.** Something like:

> "That is not a mockup — the briefing has been composed from the same
> deterministic rules you saw on the console, and the notification itself is now
> in the ledger: who sent it, to whom, what it said, and whether it was
> delivered."

**And if it fails**, the page tells you so plainly and still records the attempt.
That is a *good* moment, not a disaster. The line is:

> "It did not deliver, and it says so. A warning that silently failed to arrive
> is exactly what this product refuses to hide — the attempt is in the ledger
> either way."

That answer scores better than a successful send with most technical juries.
Rehearse it.

---

## What is recorded

Every send — delivered or not — writes a ledger event:

```
notification.sent     or    notification.failed
  actor        the authenticated operator who pressed the button
  recipients   who it went to
  subject      what it said
  transport    https | smtp | none
  delivered    true | false
  detail       why, if it failed
  ruleIds      which advisories were in the briefing
```

**No credential is ever written to the ledger, returned by the API, or shown on
screen.** A provider that echoes your key back inside a 401 error gets scrubbed
before the message goes anywhere — there is a test for exactly that, because the
first version of the code leaked it.

---

## Before the finale

- [ ] Provider chosen, sender verified, **tested to an address that is not
      yours**.
- [ ] `.env` filled in. `.env` **not** committed — `git status` should not list
      it.
- [ ] Both laptops configured, both tested.
- [ ] Tested once on the venue network if you get the chance.
- [ ] Fallback phone decided.
- [ ] **Do not open `.env` on the projector.**
