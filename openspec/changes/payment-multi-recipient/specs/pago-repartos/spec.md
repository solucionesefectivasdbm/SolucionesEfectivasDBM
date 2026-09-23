# Pago Repartos Specification

## Purpose

Allow a single collected `Pago` to be split among N recipients (receiver bank
accounts and/or existing clients) via a satellite `pago_repartos` ledger,
without altering the "1 Pago = 1 cuota" invariant used by mora, cierre de
crédito, and `generar_siguiente_cuota`.

## Requirements

### Requirement: Split Allocation Persistence

The system MUST allow persisting one or more `pago_repartos` rows per `Pago`,
each with `tipo_destinatario` (`cuenta_bancaria` | `cliente`), a
`cuenta_bancaria_id` or `cliente_id` (mutually exclusive, matching
`tipo_destinatario`), and a `monto`.

#### Scenario: Split across two receiver accounts

- GIVEN a paid `Pago` with capital_pagado + interes_pagado = 100,000
- WHEN an admin allocates 60,000 to cuenta_bancaria A and 40,000 to cuenta_bancaria B
- THEN two `pago_repartos` rows are persisted, one per account

#### Scenario: Mixed account and client split

- GIVEN a paid `Pago` of 100,000
- WHEN an admin allocates 70,000 to cuenta_bancaria A and 30,000 to an existing Cliente
- THEN two `pago_repartos` rows are persisted with distinct `tipo_destinatario`

#### Scenario: Mutually exclusive destination fields

- WHEN a `pago_reparto` row is submitted with both `cuenta_bancaria_id` and `cliente_id` set
- THEN the system rejects the request and no row is persisted

### Requirement: Split Integrity Validation

The system MUST enforce, at write time (create, edit, or delete of any
`pago_reparto` row), that the sum of `pago_repartos.monto` for a `Pago`
equals `capital_pagado + interes_pagado` within the existing `_validar_split`
TOL tolerance.

#### Scenario: Split sums correctly

- GIVEN a `Pago` with capital_pagado + interes_pagado = 100,000
- WHEN the submitted repartos sum to 100,000
- THEN the repartos are persisted

#### Scenario: Split sum mismatch rejected

- GIVEN a `Pago` with capital_pagado + interes_pagado = 100,000
- WHEN the submitted repartos sum to 95,000
- THEN the system rejects the request with an integrity error and persists nothing

#### Scenario: Editing a reparto amount re-validates the total

- GIVEN a `Pago` with two repartos summing to 100,000
- WHEN an admin edits one reparto so the new total is 90,000
- THEN the system rejects the edit and the prior values remain unchanged

### Requirement: Client-Type Split Never Creates Credit

The system MUST NOT auto-create a `Credito` or any credit-related record when
a `pago_reparto` row references a `Cliente`. Client split rows MUST link an
existing `Cliente` selected by search — free-text recipient names MUST be
rejected.

#### Scenario: Client split is informational only

- GIVEN a paid `Pago` split with 30,000 allocated to an existing Cliente C
- WHEN the split is persisted
- THEN no `Credito` is created for Cliente C
- AND the `pago_reparto` row references C's existing `cliente_id`

#### Scenario: Free-text client recipient rejected

- WHEN an admin submits a client-type reparto without a valid `cliente_id`
- THEN the system rejects the request

### Requirement: Direct Split Edit and Delete

The system MUST allow `admin` users to directly edit or delete a
`pago_reparto` row after creation. No correction/audit-trail record of the
prior value is required; the original value is not preserved in history.

#### Scenario: Reparto edited in place

- GIVEN a persisted `pago_reparto` of 40,000 to cuenta_bancaria B
- WHEN an admin edits it to 45,000 (and adjusts another reparto to keep the total valid)
- THEN the row reflects 45,000 and no prior-value record is created

#### Scenario: Reparto deleted

- GIVEN a `Pago` with two repartos
- WHEN an admin deletes one and reallocates the other to preserve the sum
- THEN only the remaining reparto persists

### Requirement: Account Inheritance Only From a Single Cuenta Recipient

`generar_siguiente_cuota` MUST copy an account onto the next installment
ONLY when the immediately prior `Pago` for the credito has exactly one
active reparto recipient AND that recipient is of type `cuenta_bancaria`.
Every other case MUST leave the next `Pago.cuenta_bancaria_id` null pending
explicit selection: 2+ recipients of any type (cuenta+cuenta, cuenta+cliente,
cliente+cliente), and a single recipient of type `cliente`.

#### Scenario: Prior payment split across two accounts

- GIVEN a paid `Pago` split between cuenta_bancaria A and cuenta_bancaria B
- WHEN `generar_siguiente_cuota` creates the next installment
- THEN the new `Pago.cuenta_bancaria_id` is null

#### Scenario: Prior payment split between one account and one client

- GIVEN a paid `Pago` split between cuenta_bancaria A and an existing `Cliente`
- WHEN `generar_siguiente_cuota` creates the next installment
- THEN the new `Pago.cuenta_bancaria_id` is null, even though only one
  `cuenta_bancaria` participated — the split had two recipients

#### Scenario: Prior payment single-account (no split) still inherits

- GIVEN a paid `Pago` with a single `cuenta_bancaria_id` and no `pago_repartos` rows
- WHEN `generar_siguiente_cuota` creates the next installment
- THEN existing inheritance behavior (per the receiver-bank-account-assignment spec) is unchanged

#### Scenario: Prior payment's sole recipient is a client, not an account

- GIVEN a paid `Pago` whose only active reparto is to an existing `Cliente`
  (no `cuenta_bancaria` recipient at all)
- WHEN `generar_siguiente_cuota` creates the next installment
- THEN the new `Pago.cuenta_bancaria_id` is null — there is no account to
  inherit, even though the split had only one recipient

### Requirement: Revenue Reports Attribute Split Pagos Per Cuenta

`reportes.py` revenue-by-cuenta figures MUST be computed from `pago_repartos`,
not from `Pago.cuenta_bancaria_id` directly. A split `Pago` MUST appear under
every cuenta it was split to, for the amount that cuenta actually received
from that payment — not attributed to a single "heritable" cuenta and not
dropped.

#### Scenario: Split payment appears under each of its cuentas

- GIVEN a paid `Pago` of $100.000 split as $60.000 to cuenta_bancaria A and
  $40.000 to cuenta_bancaria B
- WHEN a revenue-by-cuenta report is generated for the period covering that payment
- THEN cuenta A's total includes $60.000 from this payment
- AND cuenta B's total includes $40.000 from this payment
- AND the payment is not counted twice against a single cuenta

#### Scenario: Split payment with a client recipient contributes nothing to that client

- GIVEN a paid `Pago` split between cuenta_bancaria A and an existing `Cliente`
- WHEN a revenue-by-cuenta report is generated
- THEN only cuenta A's total reflects its share of the payment
- AND the client-type reparto row does not appear in the cuenta-based report
