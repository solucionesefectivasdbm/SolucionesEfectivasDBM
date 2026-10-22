# Delta for Pagos

## ADDED Requirements

### Requirement: Recaudador May Register Amounts

`POST /pagos/{id}/registrar`, `POST /pagos/{id}/confirmar-excedente` and
`POST /pagos/no-programado/{credito_id}` MUST accept the roles `admin`,
`registrador` and `recaudador`. A `recaudador` MAY register amounts on any
validated payment regardless of who validated it. Any other role (e.g. `gestor`)
MUST receive HTTP 403. Business rules of registration (validated-only,
excedente, no-programado) are unchanged.

#### Scenario: Recaudador registers a payment validated by someone else `[pytest]`
- GIVEN a payment with `validado_recaudador = True` validated by another user
- WHEN a `recaudador` calls `registrar`
- THEN the response is 2xx and the payment is registered

#### Scenario: Recaudador confirms excedente and registers no-programado `[pytest]`
- GIVEN a payment pending excedente confirmation and an active credit
- WHEN a `recaudador` calls `confirmar-excedente` and `no-programado`
- THEN both responses are 2xx

#### Scenario: Unauthorized role `[pytest]`
- WHEN a `gestor` calls any of the three endpoints
- THEN the response is 403 and nothing changes

#### Scenario: Existing roles unchanged `[pytest]`
- WHEN `admin` or `registrador` calls any of the three endpoints
- THEN behavior is identical to before the change

### Requirement: Frontend Registration Permission

`authStore.canRegistrarPago` MUST be true for `admin`, `registrador` and
`recaudador`, and false for other roles, so the register actions in `PagosPage`
(weekly and daily) are shown to recaudador. `canValidarPago` is unchanged.

#### Scenario: Recaudador sees register actions `[manual]`
- GIVEN a validated unpaid row
- WHEN viewed by a recaudador
- THEN the register actions are available
