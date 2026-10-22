# Delta for Credit Closure

## ADDED Requirements

### Requirement: Reopen On Amount Reversal

Reverting the payment that caused a credit to close (settled state or regla 14
explicit closure) MUST reopen the credit (`activo = True`) and make it operational
on read paths again. Reopened credit balances are those recomputed from the schedule
by `payment-amount-reversal`. Reversing a payment on an open credit MUST NOT alter
`activo`. The closure "Non-Goal" of reversal on closed credits applies only to
`desvalidar`, not to amount reversal.

#### Scenario: Last payment reverted reopens settled credit `[pytest]`
- GIVEN a credit closed because its last payment settled it
- WHEN that payment is reverted
- THEN `activo = True`, and the credit appears in operationally-open listings

#### Scenario: Explicit closure reopens `[pytest]`
- GIVEN a credit explicitly closed with interest pending (regla 14)
- WHEN the closing payment is reverted
- THEN `activo = True` and the pending interest is again visible per the schedule

#### Scenario: Non-closing payment leaves state `[pytest]`
- GIVEN an open credit and a registered latest payment
- WHEN it is reverted
- THEN `activo` remains `True`
