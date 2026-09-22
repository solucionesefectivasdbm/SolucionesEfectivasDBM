# Receptor Ledger Specification

## Purpose

Give admins a reliable, per-`cuenta_bancaria_id` cash balance view derived from collected `Pago` records plus an append-only ledger of `salida` (cash out) and `correccion` (manual adjustment) entries, without ever persisting a cached balance.

## Requirements

### Requirement: Compute-on-Read Balance

The system MUST compute the balance for a given `cuenta_bancaria_id` on every read as: `SUM(Pago.monto WHERE cuenta_bancaria_id = X AND pagado = True) - SUM(salida.monto WHERE cuenta_bancaria_id = X) + SUM(correccion.monto WHERE cuenta_bancaria_id = X)`. The system MUST NOT persist or cache this balance on `Receptor` or `CuentaBancaria`.

#### Scenario: Balance with mixed movement types

- GIVEN a `cuenta_bancaria_id` with 1,000,000 in collected `Pago` sum, one `salida` of 200,000, and one `correccion` of -50,000
- WHEN an admin requests the current balance
- THEN the system returns 750,000

#### Scenario: Cuenta bancaria with zero movements

- GIVEN a `cuenta_bancaria_id` with no `Pago`, `salida`, or `correccion` records
- WHEN an admin requests the current balance
- THEN the system returns 0

#### Scenario: Balance scoped per cuenta_bancaria, not per receptor

- GIVEN a receptor with two `cuenta_bancaria` records, A and B, each with independent movement histories
- WHEN an admin requests the balance for cuenta_bancaria A
- THEN the system returns a balance computed only from A's `Pago`, `salida`, and `correccion` records, ignoring B

#### Scenario: Reassigning a paid Pago's cuenta_bancaria_id shifts two balances

- GIVEN a `Pago` with `pagado = True` and `monto = 100,000` originally assigned to cuenta_bancaria A
- WHEN an admin reassigns that `Pago.cuenta_bancaria_id` to cuenta_bancaria B
- THEN cuenta_bancaria A's computed balance decreases by 100,000
- AND cuenta_bancaria B's computed balance increases by 100,000

### Requirement: Salida Registration with Overdraft Protection

The system MUST allow `admin` users to register a `salida` (cash-out) movement against a `cuenta_bancaria_id`. The system MUST hard-reject a `salida` whose amount exceeds that account's current computed balance, without recording the entry. A `salida` exactly equal to the current balance MUST be accepted.

#### Scenario: Salida within balance succeeds

- GIVEN cuenta_bancaria A has a current balance of 500,000
- WHEN an admin registers a salida of 300,000 against cuenta_bancaria A
- THEN the salida is persisted in `receptor_movimientos`
- AND the new computed balance is 200,000

#### Scenario: Salida exceeding balance is rejected

- GIVEN cuenta_bancaria A has a current balance of 500,000
- WHEN an admin registers a salida of 500,001 against cuenta_bancaria A
- THEN the system rejects the request with an overdraft error
- AND no `receptor_movimientos` row is created

#### Scenario: Salida exactly equal to balance succeeds

- GIVEN cuenta_bancaria A has a current balance of 500,000
- WHEN an admin registers a salida of exactly 500,000
- THEN the salida is persisted
- AND the new computed balance is 0

### Requirement: Correccion Registration

The system MUST allow `admin` users to register a `correccion` movement with a positive or negative amount and an optional free-text note. The system MUST NOT require a mandatory justification for corrections.

#### Scenario: Positive correction

- GIVEN cuenta_bancaria A has a current balance of 100,000
- WHEN an admin registers a correccion of +20,000 with no note
- THEN the correccion is persisted
- AND the new computed balance is 120,000

#### Scenario: Negative correction with note

- GIVEN cuenta_bancaria A has a current balance of 100,000
- WHEN an admin registers a correccion of -15,000 with note "ajuste conteo físico"
- THEN the correccion is persisted with the note
- AND the new computed balance is 85,000

### Requirement: Ledger Read Endpoints

The system MUST expose an endpoint to retrieve the current balance for a `cuenta_bancaria_id` and an endpoint to retrieve its full movement history (`salida` and `correccion` rows, ordered by date). Both endpoints MUST be accessible to `admin` and `recaudador` roles, mirroring existing receptor read access.

#### Scenario: Recaudador reads balance and history

- GIVEN an authenticated user with role `recaudador`
- WHEN they request the balance and movement history for a cuenta_bancaria_id
- THEN the system returns both successfully

### Requirement: Write Permission Restricted to Admin

The system MUST restrict `salida` and `correccion` write endpoints to the `admin` role. The permission check MUST be implemented so that extending write access to another role (e.g., future `registrador`) requires no structural rework.

#### Scenario: Non-admin attempts a write

- GIVEN an authenticated user with role `recaudador`
- WHEN they attempt to register a `salida` or `correccion`
- THEN the system rejects the request with a permission error

### Requirement: Ledger Entries Survive Receptor Soft-Delete

The system MUST retain `receptor_movimientos` rows and include them in balance computation even if the owning `Receptor` is soft-deleted.

#### Scenario: Balance after receptor soft-delete

- GIVEN a receptor with a cuenta_bancaria that has recorded salidas and corrections
- WHEN the receptor is soft-deleted
- THEN the cuenta_bancaria's computed balance still reflects all prior movements unchanged
