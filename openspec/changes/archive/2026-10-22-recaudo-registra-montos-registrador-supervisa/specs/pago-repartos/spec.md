# Delta for Pago Repartos

## ADDED Requirements

### Requirement: Repartos Soft-Deleted On Amount Reversal

Reverting a payment's amount MUST soft-delete (`deleted_at` set) all active
`pago_repartos` rows of that payment, including the default reparto, so reports
and ledger no longer attribute it. Re-registering the payment afterwards MUST
create a fresh default reparto, provided the payment still has a bank account. A payment
whose account was cleared by a split among two or more recipients keeps no account after
the revert (no single account can be restored without guessing), so no default reparto is
created until an account is assigned via the bank-account update. Repartos of other
payments are untouched.

#### Scenario: Repartos removed on revert `[pytest]`
- GIVEN a registered payment with one or more active repartos
- WHEN it is reverted
- THEN all its repartos have `deleted_at` set and none remain active

#### Scenario: Re-registration recreates default reparto `[pytest]`
- GIVEN a reverted payment
- WHEN it is registered again
- THEN exactly one active default reparto exists for it

#### Scenario: Split-cleared account needs reassignment `[pytest]`
- GIVEN a payment whose account was cleared by a multi-recipient split, then reverted
- WHEN it is registered again without assigning an account
- THEN no default reparto exists for it
- AND assigning an account via the bank-account update creates the reparto
