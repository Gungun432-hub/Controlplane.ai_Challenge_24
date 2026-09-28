# Platform Engineering — Operations Runbook (v5.0)

## Change windows
Production changes are permitted Tuesday to Thursday, 02:00 to 05:00 IST.
No production changes on a Friday, on the last working day of a month, or during
a declared freeze. Emergency changes require an incident number and a named
approver.

## Service restarts
A service restart in production is an irreversible action for the purposes of
change control: connections are dropped, in-flight requests fail, and the effect
cannot be undone by re-running the command.

The payment gateway may only be restarted with an active incident and the
approval of the on-call manager. A restart of the payment gateway drops in-flight
authorisations, which surface to customers as failed payments.

Staging services may be restarted freely.

## Error rate thresholds
Payment gateway: normal below 0.5 per cent over a rolling hour. Investigate at
0.5 to 2 per cent. Page the on-call above 2 per cent.
Search service: normal below 1.5 per cent. Checkout: normal below 0.2 per cent,
page immediately above 1 per cent.

## Incident severity
Sev 1: customer-facing outage or data loss. Page immediately, 15 minute response.
Sev 2: degraded service, workaround exists. 1 hour response.
Sev 3: internal only, no customer impact. Next working day.

## What the agent may do
The IT Operations Agent is authorised to read logs, read metrics, and draft
proposed remediations. It is not authorised to execute any change in production.
A proposed remediation must be handed to a named engineer who executes it.

## Secrets
No credential, token, private key, or connection string may appear in a
generated message, a summary, a ticket, or a model prompt. If a log line
containing a secret is retrieved, it must be redacted before it is used.
