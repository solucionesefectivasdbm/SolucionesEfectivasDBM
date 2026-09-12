# Session Expiry Feedback Specification

## Purpose

When an API call returns 401 and the silent token refresh also fails, the
user is redirected to `/login`. This capability requires that redirect to be
explained on the login page instead of happening silently. It applies to all
roles and all API calls; no proactive refresh is introduced. UI copy is
neutral Spanish (tuteo), matching existing screens.

Test tags: `[manual]` = frontend, no runner. No backend change.

## Requirements

### Requirement: Redirect Reason Persisted

When the silent refresh fails AND the refresh call itself answered HTTP 401,
the client MUST persist a session-expired reason in `sessionStorage` before
navigating to `/login`. The reason MUST only be set by this failed-refresh
path, and MUST NOT be set when the refresh call fails for a network error or
a 5xx (backend outage), since that is not an expired session. The original
401 that triggers the refresh attempt MUST NOT be the response to the
`/auth/login` request itself — a login attempt with wrong credentials never
enters the refresh path.

#### Scenario: Expired session on Reversar `[manual]`

- GIVEN the access token expired and the refresh cookie is missing
- WHEN the user clicks "Reversar"
- THEN the app lands on `/login` and a session-expired reason is present in
  `sessionStorage`

#### Scenario: Explicit logout sets no reason `[manual]`

- WHEN the user logs out via the menu
- THEN `/login` is shown with no expiry message

#### Scenario: Wrong credentials on login show no expiry message `[manual]`

- GIVEN the user is on `/login` with an active or no session
- WHEN they submit an incorrect username or password and the backend
  responds 401 to `/auth/login`
- THEN the backend's credentials-error message is shown inline on the login
  form, no session-expired message appears, no reason is stored in
  `sessionStorage`, and the page does not reload or redirect

#### Scenario: Backend outage during refresh sets no reason `[manual]`

- GIVEN the access token expired and the API is unreachable or returns a 5xx
  when the client attempts a silent refresh
- WHEN the failed refresh redirects to `/login`
- THEN no session-expired reason is stored in `sessionStorage` and the login
  page shows no expiry message

### Requirement: Login Page Shows Expiry Message Once

On load, the login page MUST read the reason, display the inline text
"Tu sesión expiró, vuelve a ingresar." when present, and clear the reason
immediately so the message does not reappear on later visits or reloads.

#### Scenario: Message shown after expiry redirect `[manual]`

- GIVEN a session-expired reason is stored
- WHEN `/login` renders
- THEN the inline message is visible and the reason is removed from storage

#### Scenario: Message cleared on reload `[manual]`

- GIVEN the message was displayed once
- WHEN the user reloads `/login`
- THEN no expiry message is shown

#### Scenario: Cross-browser parity `[manual]`

- GIVEN Chrome, Safari and Firefox
- WHEN the expired-session flow is reproduced in each
- THEN each shows the same message on `/login`

## Non-Goals

- Proactive or timed token refresh; refresh TTL changes; toast-based delivery
  of the message.
