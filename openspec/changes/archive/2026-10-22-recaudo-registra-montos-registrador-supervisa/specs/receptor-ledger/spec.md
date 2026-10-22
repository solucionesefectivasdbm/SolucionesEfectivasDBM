# Delta for Receptor Ledger

## ADDED Requirements

### Requirement: Balance Follows Amount Reversal

Because the balance is computed on read from active `pago_repartos` joined to
paid payments, reverting a payment's amount MUST remove its contribution
automatically, with no ledger write. The reversal MUST NOT be blocked when the
resulting balance is negative; the negative balance is shown as computed.
Overdraft protection applies only to salida registration, unchanged.

#### Scenario: Reversal removes contribution `[pytest]`
- GIVEN a receptor balance that includes a registered payment's reparto
- WHEN the payment is reverted
- THEN the balance decreases by that reparto amount

#### Scenario: Negative balance permitted `[pytest]`
- GIVEN a receptor who already registered salidas consuming the payment's funds
- WHEN the payment is reverted
- THEN the revert succeeds and the balance is negative on read
