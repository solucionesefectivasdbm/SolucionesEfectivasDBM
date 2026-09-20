# Receiver Bank Account Assignment Specification

## Purpose

Defines the receptor bank account (`CuentaBancaria`) as the money destination
of a gestor and of a payment, replacing the receptor-level link. Covers the
default-account rule, inheritance and propagation, the per-payment account
change, cascading receptor → account filters, the per-account report
sub-breakdown, the idempotent backfill, and role gates. Rejection `detail`
strings are backend-owned Spanish UI copy; scenarios fix semantics, not
wording. Money amounts keep the existing aggregation semantics of `/reportes`.

Test tags: `[pytest]` = backend-automatable; `[manual]` = frontend, no runner.

## Requirements

### Requirement: Default Bank Account

Every `CuentaBancaria` MUST carry `es_predeterminada` (boolean, never null).
Each receptor with at least one account MUST have exactly one default. The
first account created for a receptor MUST become the default automatically.
`PUT /receptores/{id}/cuentas/{cuenta_id}/predeterminada` MUST make the
target account the default and clear the previous one atomically. Changing the
default MUST NOT modify any existing `Gestor.cuenta_bancaria_id` or
`Pago.cuenta_bancaria_id`. The default is used only for backfill and UI
preselection. Account responses MUST expose `es_predeterminada`.

#### Scenario: First account is default `[pytest]`

- GIVEN a receptor with no accounts
- WHEN an account is created
- THEN it is returned with `es_predeterminada = true`

#### Scenario: Second account is not default `[pytest]`

- GIVEN a receptor with one (default) account
- WHEN a second account is created
- THEN the second has `es_predeterminada = false` and the first stays `true`

#### Scenario: Admin changes the default `[pytest]`

- GIVEN a receptor with accounts A (default) and B
- WHEN the default endpoint is called for B
- THEN B is `true`, A is `false`, and exactly one default exists

#### Scenario: Default change does not move assignments `[pytest]`

- GIVEN a gestor and an unpaid payment assigned to account A
- WHEN the receptor's default is switched to B
- THEN the gestor and the payment still reference A

#### Scenario: Account of another receptor rejected `[pytest]`

- WHEN the default endpoint is called with a `cuenta_id` that does not belong
  to `{id}`
- THEN the response is 404 and no default changes

### Requirement: Gestor Account Assignment and Propagation

`GestorCreate`/`GestorUpdate` MUST accept an optional `cuenta_bancaria_id`
replacing `receptor_id`; `GestorResponse` MUST expose `cuenta_bancaria_id`,
the nested account, and the derived receptor. When `PATCH /gestores/{id}`
changes `cuenta_bancaria_id` to a non-null value, every unpaid
(`pagado = false`), non-deleted payment of that gestor's active clientes'
creditos MUST be updated to the new account; paid payments MUST NOT change.
An unknown `cuenta_bancaria_id` MUST be rejected with 404 and nothing persisted.

#### Scenario: Propagates to unpaid only `[pytest]`

- GIVEN a gestor on account A with one paid and one unpaid payment
- WHEN the gestor is moved to account B
- THEN the unpaid payment references B and the paid one still references A

#### Scenario: Other gestor untouched `[pytest]`

- GIVEN two gestores on account A
- WHEN only the first is moved to B
- THEN the second gestor's payments still reference A

### Requirement: Payment Account Inheritance

When cuotas are generated (first cuota at credit creation and each next cuota
built during payment registration or reversal), the new `Pago` MUST inherit
the owning cliente's `gestor.cuenta_bancaria_id` at that moment. If the gestor
has no account, the payment's `cuenta_bancaria_id` MUST be null.

#### Scenario: First cuota inherits `[pytest]`

- GIVEN a cliente whose gestor is on account A
- WHEN a credit is created
- THEN its first payment references A

#### Scenario: Next cuota inherits current account `[pytest]`

- GIVEN a credit whose gestor moved from A to B after the first cuota
- WHEN the first cuota is paid and the next is generated
- THEN the next payment references B

#### Scenario: Gestor without account `[pytest]`

- GIVEN a gestor with `cuenta_bancaria_id = null`
- WHEN a credit is created
- THEN the first payment has `cuenta_bancaria_id = null`

### Requirement: Individual Payment Account Change

`PATCH /pagos/{id}/cuenta-bancaria` MUST replace `PATCH /pagos/{id}/receptor`
(old path MUST return 404 or 405). Body MUST carry `cuenta_bancaria_id`. The
target MAY belong to a different receptor. On success the system MUST persist
the new account, return the updated `PagoResponse`, and write an audit entry
attributed to the caller with `cuenta_bancaria_id` old → new. Unknown account
MUST return 404 with nothing persisted; projected rows have no id and MUST
return 404.

#### Scenario: Move to another receptor's account `[pytest]`

- GIVEN a payment on receptor R1's account A
- WHEN it is changed to receptor R2's account C
- THEN it references C, its derived receptor is R2, and the audit shows A → C

#### Scenario: Unknown account `[pytest]`

- WHEN the body references a non-existent account
- THEN the response is 404, the payment and audit log are unchanged

### Requirement: Cascading Filters on Payment Listing

`GET /pagos` MUST accept optional `receptor_id` and optional
`cuenta_bancaria_id`. `receptor_id` alone MUST return payments of all that
receptor's accounts. `cuenta_bancaria_id` MUST narrow to that account; when
both are sent and the account does not belong to the receptor the response
MUST be 422. When either filter is active, projected (virtual) rows MUST NOT
be generated, as today. Each row MUST expose `cuenta_bancaria_id`, the nested
account, and the derived receptor; projected rows expose null.

#### Scenario: Receptor-only aggregates accounts `[pytest]`

- GIVEN payments on accounts A and B of receptor R1 and on C of R2
- WHEN listed with `receptor_id = R1`
- THEN only A and B payments are returned

#### Scenario: Account narrows `[pytest]`

- GIVEN the same data
- WHEN listed with `receptor_id = R1` and `cuenta_bancaria_id = B`
- THEN only B payments are returned

#### Scenario: Mismatched pair rejected `[pytest]`

- WHEN listed with `receptor_id = R1` and `cuenta_bancaria_id = C`
- THEN the response is 422

#### Scenario: Virtual rows suppressed `[pytest]`

- GIVEN a credit whose future cuotas are not yet persisted
- WHEN listed with any account/receptor filter
- THEN no projected rows appear

### Requirement: Report Per-Account Sub-Breakdown

`GET /reportes` MUST keep `por_receptor` with unchanged fields and totals
(receptor derived through the payment's account). Each receptor entry MUST
carry `por_cuenta`, one row per account with the same money fields plus
account identity. Per-account subtotals MUST sum exactly to the receptor entry
under the existing rounding semantics. Payments with null account MUST be
excluded from both levels, as today.

#### Scenario: Subtotals sum to receptor `[pytest]`

- GIVEN paid payments of 100 on account A and 50 on account B of R1
- WHEN the report is requested for that period
- THEN R1 shows `total_recaudado = 150` with rows A = 100 and B = 50

#### Scenario: Totals equal pre-change values `[pytest]`

- GIVEN the same fixture used by existing report tests
- WHEN the report is requested
- THEN receptor-level totals are identical to the pre-change expectations

### Requirement: Backfill Endpoint

A temporary admin-only `POST /receptores/admin/backfill-cuentas-bancarias`
(query `dry_run`, default `true`) MUST: (1) create a default account
`entidad_bancaria = "Por definir"`, `Ahorros`, `numero_cuenta = "0"` for each
active receptor with no account; (2) mark the account with the lowest `id`
(deterministic, portable ranking rather than `MIN(uuid)`) as default for
receptors with accounts but no default; (3) set `cuenta_bancaria_id` from each
gestor/pago row's `receptor_id` default where `cuenta_bancaria_id` is null;
(4) for unpaid, non-deleted pagos still without account and without
`receptor_id`, inherit the account of the non-deleted credito -> cliente ->
gestor chain. Rows whose default cannot be resolved MUST NOT be counted or
written; they MUST be reported only under `pendientes`
(`gestores_sin_cuenta`, `pagos_sin_cuenta_rellenables`,
`pagos_sin_cuenta_no_rellenables`). It MUST be idempotent, MUST NOT overwrite
non-null values, MUST return counts per step, and MUST operate on SQL columns
so it stays runnable after the ORM drops `receptor_id`. Generic accounts MUST
be visible as-is until edited. The endpoint MUST be deleted in the cleanup PR.

#### Scenario: Idempotent re-run `[pytest]`

- GIVEN a completed backfill
- WHEN it runs again
- THEN all counts are 0 and no rows change

#### Scenario: Fills only gaps `[pytest]`

- GIVEN a gestor already on account B and a pago with null account whose
  `receptor_id` defaults to A
- WHEN the backfill runs
- THEN the gestor keeps B and the pago gets A

### Requirement: Role Gates

Gates MUST mirror today: account create/update/default-change `admin`;
gestor account assignment `admin`; payment account change `admin` and
`recaudador`; backfill `admin`; listing/report visibility unchanged. Others
MUST receive 403 with nothing persisted.

#### Scenario: Registrador cannot change payment account `[pytest]`

- WHEN a `registrador` calls `PATCH /pagos/{id}/cuenta-bancaria`
- THEN the response is 403 and the payment is unchanged

### Requirement: Account Visible Wherever the Receptor Was

Weekly, daily and deferred payment tables MUST show the account (receptor,
entity, number) where the receptor was shown. The "Modificar cuenta" modal
MUST offer a receptor select that preselects its default account and an
account select limited to that receptor. Gestor form/list MUST use an account
select/badge. Receptores page MUST mark the default and offer "set default".
Reportes MUST render per-account rows nested under each receptor. Backend
4xx `detail` MUST be shown verbatim.

#### Scenario: Cascading filter in UI `[manual]`

- GIVEN the Pagos page
- WHEN a receptor is chosen, then one of its accounts
- THEN the table narrows at each step and the account column matches

#### Scenario: Default preselected `[manual]`

- WHEN a receptor is chosen in the "Modificar cuenta" modal
- THEN its default account is preselected and can be changed

## Non-Goals

- Balance, ledger or "salidas" (item 9); multi-destination splits (item 10).
- Account delete or deactivate; soft delete on `CuentaBancaria`.
- Role changes, `Cliente` linkage, credit math, audit mechanics beyond the
  renamed field; rewriting assignments when the default changes.
