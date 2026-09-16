## Ticket ID

<!-- Story ID from the backlog, e.g. 1.1, 8.3 -->

## Summary

<!-- What does this PR change, and why? -->

## Test Plan

<!-- The test cases drafted, then scoped by the human, before implementation
     (AGENTS.md → Feature Development Workflow). One row per case; each case belongs to
     exactly one layer — never duplicate the same case in two.
     Cover every category below unless one genuinely doesn't apply to this story — say why if so.
     For a fix/chore/docs PR adding no new test cases, write N/A and say why. -->

| Acceptance criterion / case | Category | Layer | Test | Status |
| --- | --- | --- | --- | --- |
| <!-- e.g. AC1: valid login returns a session --> | happy path | backend | `test_login.py::test_valid_login` | ✅ |
| <!-- e.g. AC2: password shorter than 8 chars --> | boundary | backend | `test_login.py::test_short_password_rejected` | ✅ |
| <!-- e.g. AC3: unknown email --> | edge | backend | `test_login.py::test_unknown_email_generic_message` | ✅ |
| <!-- e.g. AC4: signed-out request to a protected route --> | permission | backend | `test_login.py::test_requires_session` | ✅ |
| <!-- e.g. AC5: double-booking the same venue slot --> | conflict | backend | `test_venues.py::test_double_booking_rejected` | ✅ |
| <!-- e.g. login flow, role-gated redirect --> | happy path | e2e | `login.spec.ts` | ✅ |

## Tests

<!-- Commands run and their result. -->

- Backend: `uv run pytest` — <!-- e.g. 12 passed -->
- E2E: `npm test` — <!-- e.g. 3 passed -->
- Manual: <!-- anything exercised by hand in the browser -->

## Definition of Done

- [ ] A test plan was drafted and its scope decided by the human before implementation,
      covering all of: happy path, boundary, edge, permission, and conflict cases (or noting
      why one doesn't apply)
- [ ] Acceptance criteria from the backlog are met
- [ ] The tests written from that plan exist, are filed in the right suite (`backend/tests/` or
      `tests/e2e/`), and pass; lint/format checks are clean
- [ ] Frontend lint is clean (if applicable); the flow was manually exercised in the browser
- [ ] No secrets, API keys, or `.env` values committed
- [ ] PR opened against `sprint/<N>`, one review obtained, CI green
