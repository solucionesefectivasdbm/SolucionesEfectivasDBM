# Delta for Payment Validation Reversal

## ADDED Requirements

### Requirement: Interplay With Reverted Amounts

`desvalidar` rules and role matrix are unchanged (admin and recaudador only; 422
when `pagado = True` or amounts recorded). An installment restored by "revert
amount" is validated, unpaid and has zero amounts, so `desvalidar` on it MUST
succeed under the existing rules. A registered (paid) installment MUST still be
rejected by `desvalidar` until its amount is reverted.

#### Scenario: Desvalidar after amount revert `[pytest]`
- GIVEN a payment whose amount was reverted (validated, unpaid, zero amounts)
- WHEN an `admin` or `recaudador` calls `desvalidar`
- THEN the response is 200 and `validado_recaudador` is `False`

#### Scenario: Desvalidar before amount revert `[pytest]`
- GIVEN a registered (paid) installment
- WHEN `desvalidar` is called
- THEN the response is 422 (already registered with amounts)

#### Scenario: Registrador still forbidden on desvalidar `[pytest]`
- WHEN a `registrador` calls `desvalidar`
- THEN the response is 403
