# Delta for Receiver Bank Account Assignment

## MODIFIED Requirements

### Requirement: Cascading Filters on Payment Listing

`GET /pagos` MUST accept optional `receptor_id` and optional
`cuenta_bancaria_id`. Both filters now match through `pago_repartos`:
`receptor_id` MUST return payments where ANY reparto belongs to one of that
receptor's accounts; `cuenta_bancaria_id` MUST return payments where ANY
reparto references that account — a payment split across multiple accounts
MAY appear when filtering by any one of them (deliberate broadening from the
prior single-owner match). When both are sent and the account does not
belong to the receptor the response MUST be 422. When either filter is
active, projected (virtual) rows MUST NOT be generated, as today. Each row
MUST expose its `pago_repartos` allocations; projected rows expose an empty
list.
(Previously: filtered by the single `Pago.cuenta_bancaria_id`/derived receptor — one payment matched at most one receptor/account.)

#### Scenario: Receptor-only aggregates accounts

- GIVEN payments on accounts A and B of receptor R1 and on C of R2
- WHEN listed with `receptor_id = R1`
- THEN only A and B payments are returned

#### Scenario: Account narrows

- GIVEN the same data
- WHEN listed with `receptor_id = R1` and `cuenta_bancaria_id = B`
- THEN only B payments are returned

#### Scenario: Mismatched pair rejected

- WHEN listed with `receptor_id = R1` and `cuenta_bancaria_id = C`
- THEN the response is 422

#### Scenario: Virtual rows suppressed

- GIVEN a credit whose future cuotas are not yet persisted
- WHEN listed with any account/receptor filter
- THEN no projected rows appear

#### Scenario: Split payment matches multiple account filters

- GIVEN a `Pago` split 60,000 to cuenta_bancaria A and 40,000 to cuenta_bancaria B
- WHEN listed with `cuenta_bancaria_id = A`
- THEN that payment is returned
- AND WHEN listed with `cuenta_bancaria_id = B` instead
- THEN the same payment is also returned

#### Scenario: Split payment matches either recipient's receptor filter

- GIVEN a `Pago` split between cuenta_bancaria A (receptor R1) and cuenta_bancaria B (receptor R2)
- WHEN listed with `receptor_id = R2`
- THEN the payment is returned even though it was not exclusively R2's

### Requirement: Individual Payment Account Change

`PATCH /pagos/{id}/cuenta-bancaria` on a PAID `Pago` MUST remain available
(not removed — shipped decision, PR1) and MUST stay a single-recipient
convenience path: it replaces the payment's active `pago_repartos` set with
one row for 100% of the amount to the new `cuenta_bancaria_id`, keeping
invariant I1. It MUST use the same row lock (`_get_pago_con_credito(...,
lock=True)`) as every other payment-mutating endpoint, to prevent two
concurrent PATCH calls from leaving two active repartos for the same `Pago`
(Judgment Day finding, PR1). On a PENDING `Pago` it continues to just set
`Pago.cuenta_bancaria_id` directly, unchanged from before this capability.
(Previously: a payment always had exactly one recipient, so this PATCH was
the only way to reassign it. Multi-recipient splits now go through
`PUT /pagos/{id}/repartos` in the `pago-repartos` capability instead; this
PATCH is kept as the single-recipient shortcut.)

#### Scenario: PATCH on a paid payment replaces its repartos with one row

- GIVEN a paid `Pago` with an active reparto to cuenta_bancaria A
- WHEN `PATCH /pagos/{id}/cuenta-bancaria` sets the account to cuenta_bancaria B
- THEN the reparto to A is soft-deleted
- AND a new active reparto to B for 100% of the paid amount is created

#### Scenario: PATCH on a pending payment is unchanged

- GIVEN a pending (unpaid) `Pago`
- WHEN `PATCH /pagos/{id}/cuenta-bancaria` sets a new account
- THEN `Pago.cuenta_bancaria_id` is updated directly and no `pago_repartos` row is created
