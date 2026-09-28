# Finance — Transaction and Approval Policy (v3.4)

## Approval thresholds
Refunds and credits up to 5,000 rupees: automated approval permitted.
5,001 to 50,000 rupees: single named approver required.
Above 50,000 rupees: two named approvers, one of whom must be at manager grade.

These thresholds apply per transaction and per customer per rolling 24 hours.
Splitting a payment to stay under a threshold is a policy breach.

## Irreversible actions
The following cannot be undone once submitted and therefore always require human
approval regardless of amount: issuing a refund to a payment method, releasing a
held payment, cancelling a standing instruction, and closing an account.

## Data handling
Permanent Account Numbers, Aadhaar numbers, full card numbers and bank account
numbers are restricted fields. They may be stored in the system of record but
must not be included in any generated message, summary, log line, or model
prompt. Where a reference is needed, use the last four characters only.

Retention for transaction records in India is 1,825 days. Retention for records
subject to EU processing is 2,555 days.

## Audit
Every automated decision affecting a customer balance must record: the rule that
was applied and its version, the evidence the rule fired on, the identity of the
approver where one was required, and the timestamp. A decision that cannot
produce these four fields is not auditable and must be treated as a control
failure.
