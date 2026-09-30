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
- E2E: `npm run test:e2e` — <!-- e.g. 3 passed -->
- Manual: <!-- anything exercised by hand in the browser -->

## Merge checklist

<!-- The author ticks these. -->

- [ ] A test plan was drafted and its scope decided by the human before implementation,
      covering all of: happy path, boundary, edge, permission, and conflict cases (or noting
      why one doesn't apply)
- [ ] Every acceptance criterion this PR addresses has at least one row in the Test Plan table,
      and is met
- [ ] The tests written from that plan exist, are filed in the right suite (`backend/tests/` or
      `tests/e2e/`), failed before the implementation, and pass now
- [ ] I have read every changed line, including any AI-generated code and tests, and can
      explain it. It does what the acceptance criteria ask, the functions, fields and
      endpoints it uses exist, and no test was weakened, skipped or edited to match a bug
- [ ] Lint/format checks are clean; the flow was manually exercised in the browser (if there is
      UI)
- [ ] No secrets, API keys, or `.env` values committed
- [ ] PR opened against `main`, CI green

## Reviewer sign-off

<!-- Reviewer: approve only with the sign-off from CONTRIBUTING.md → Reviewer Sign-off pasted
     as your review comment, every test case listed and marked. Any ❌ is Request changes. -->

- [ ] Approved with a reviewer sign-off comment
