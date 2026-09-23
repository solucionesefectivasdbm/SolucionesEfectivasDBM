# Delta for Receptor Ledger

## MODIFIED Requirements

### Requirement: Compute-on-Read Balance

The system MUST compute the balance for a given `cuenta_bancaria_id` on every
read as: `SUM(pago_repartos.monto WHERE tipo_destinatario = 'cuenta_bancaria'
AND cuenta_bancaria_id = X, joined to Pago WHERE pagado = True) -
SUM(salida.monto WHERE cuenta_bancaria_id = X) + SUM(correccion.monto WHERE
cuenta_bancaria_id = X)`. The system MUST NOT persist or cache this balance
on `Receptor` or `CuentaBancaria`. For historical `Pago` rows migrated before
`pago_repartos` existed, the backfilled 100%-allocation row MUST be used so
totals match pre-change balances.
(Previously: aggregated directly from `Pago.cuenta_bancaria_id` with no reparto layer — one payment contributed to exactly one account's balance.)

#### Scenario: Balance with mixed movement types

- GIVEN a `cuenta_bancaria_id` with 1,000,000 in reparto-allocated `Pago` sum, one `salida` of 200,000, and one `correccion` of -50,000
- WHEN an admin requests the current balance
- THEN the system returns 750,000

#### Scenario: Cuenta bancaria with zero movements

- GIVEN a `cuenta_bancaria_id` with no `pago_repartos`, `salida`, or `correccion` records
- WHEN an admin requests the current balance
- THEN the system returns 0

#### Scenario: Balance scoped per cuenta_bancaria, not per receptor

- GIVEN a receptor with two `cuenta_bancaria` records, A and B, each with independent movement histories
- WHEN an admin requests the balance for cuenta_bancaria A
- THEN the system returns a balance computed only from A's `pago_repartos`, `salida`, and `correccion` records, ignoring B

#### Scenario: Split payment contributes partial amounts to two balances

- GIVEN a paid `Pago` of 100,000 split into 60,000 to cuenta_bancaria A and 40,000 to cuenta_bancaria B
- WHEN an admin requests the balances for A and B
- THEN A's balance includes 60,000 and B's balance includes 40,000 from that payment, with no double counting

#### Scenario: Backfilled historical payment matches pre-change balance

- GIVEN a `Pago` paid before this change with `cuenta_bancaria_id = A` and no manual reparto edits since
- WHEN an admin requests cuenta_bancaria A's balance after the migration backfill
- THEN the balance equals the pre-change computed balance for that payment

#### Scenario: Editing a reparto reassigns balance without a Pago-level reassignment

- GIVEN a paid `Pago` with a reparto of 100,000 to cuenta_bancaria A
- WHEN an admin edits the reparto to reference cuenta_bancaria B instead
- THEN cuenta_bancaria A's balance decreases by 100,000
- AND cuenta_bancaria B's balance increases by 100,000
