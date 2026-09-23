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

## REMOVED Requirements

### Requirement: Individual Payment Account Change

(Reason: a payment can now have 0..N recipients instead of exactly one, so a single-field account PATCH no longer models the domain.)
(Migration: replaced by the `pago_repartos` split create/edit/delete operations defined in the `pago-repartos` capability. The old `PATCH /pagos/{id}/cuenta-bancaria` path MUST return 404 or 405.)
