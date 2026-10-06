# backend/STYLE.md

Personal coding idioms for `backend/`. Follow these when writing or reviewing code. This
document only contains things Claude would get wrong without being told: not standard Python or
FastAPI conventions, and not patterns already covered in [CLAUDE.md](CLAUDE.md).

**What these rules are for.** One idea sits under nearly all of them: *a reader should not have
to open the function body, or another file, to know what something does.* Names carry type and
intent, failures are typed and loud, values are never unnamed, and indirection has to earn its
place. Where a rule below looks fussy, that is the thing it is protecting.

**Automated enforcement.** `ruff check` owns four rule sets — `select = ["E", "F", "I", "RET"]`
in `pyproject.toml`: pycodestyle errors, pyflakes (unused imports and names), import ordering, and
return flow (no `else` after an exiting `if`, no bare variable before a `return`). `ruff format`
owns layout at 100 columns. Everything below is enforced by review, and nothing here restates a
rule ruff already decides.

**Queued to move to tooling.** `ANN` (annotation presence) would own the *Annotate every
signature* rule below. `uv run ruff check --select ANN app` lists what it would report today.
Clear those and add `ANN` to `select`; the rule then leaves this file.

**Provenance.** Every rule ends with the sites in this repo it was drawn from — an *exemplar*
that does it right, or a *counter-site* that does not — named by file and function, never by line
number, so an anchor survives edits around it. That anchor is the only justification a rule gets
here: open the file and check. A rule with nothing to point at was removed rather than kept on the
strength of where it came from. See
[Considered and rejected](#considered-and-rejected) for what was deliberately left out.

**Rule strength.** Every rule carries its weight, and a non-blocking weight is genuinely the
author's call. Never flatten a `taste` into a "must".

| Grade | Meaning |
| --- | --- |
| `blocking` | A reviewer blocks the PR on it. |
| `expected` | The default. Deviating needs a reason stated in the PR. |
| `taste` | Raised as a suggestion, the author decides. |

**A rule yields only to a demonstrated technical cost, never to a style preference**, and a yield
is recorded as a conscious new precedent rather than left to slip in. Where a carried rule and
this tree's existing majority disagree, the tree wins — see [Standing divergences](#standing-divergences).

## Naming

- `expected` — **Name the function for what it returns or mutates, and keep a router function's
  name identical to the service function it calls.** That identity is the explicit coupling
  between the two layers; when one is renamed, the rename travels through router, service and
  every import in the same commit.

  *`expected` · already holds here: `create_venue`, `update_venue`, `list_venues` and
  `get_venue` share their names across `venues/router.py` and `venues/service.py`*

- `taste` — **Prefix a boolean with `is_`.** The columns already do (`is_active`, `is_internal`).
  Graded `taste` rather than `expected` because three existing parameters read naturally without
  it and forcing `is_include_withdrawn` would be worse — see Standing divergences.

  *`taste` · downgraded for this tree ·
  exemplars `auth/models.py` (`is_active`); counter-sites: see Standing divergences*

## Queries and sessions

- `blocking` — **Query with `select()` plus `db.scalar()` / `db.scalars()`, never `db.query()`.**
  `db.query()` is the SQLAlchemy 1.x API. It still runs on 2.0, so nothing fails — it just types
  poorly and reads differently from every other query in the tree.

  ```python
  # Good
  user = db.scalar(select(User).where(User.email == email))

  # Bad — legacy 1.x API
  user = db.query(User).filter(User.email == email).first()
  ```

  *`blocking` · exemplars `auth/service.py::authenticate`, `venues/service.py::list_venues`;
  `git grep "db.query(" app` finds none*

- `expected` — **Filtering, sorting and limiting happen in SQL, not in Python.** Bend this only
  where moving the work would change the result.

  *`expected` · exemplar `venues/service.py::list_venues`, which filters `status` in the
  statement rather than the list*

## Function signatures

- `expected` — **Make every service parameter that is not the session or the payload
  keyword-only, with `*`.**
  The actor, flags and options all end up as bare positionals otherwise, and
  `create_venue(db, data, user)` does not say which user or in what capacity.

  ```python
  # Good
  def create_venue(db: Session, data: VenueCreate, *, actor: User) -> Venue: ...


  # Bad
  def create_venue(db: Session, data: VenueCreate, actor: User) -> Venue: ...
  ```

  **A stricter variant of this rule exists elsewhere**, applying `*` only in front of a
  dangerous default. Where this tree uses `*` it uses the broader form, so the local majority
  governs.

  *`expected` · exemplars `venues/service.py::create_venue`, `common/audit.py::record_audit`,
  `auth/passwords.py::hash_password`*

- `expected` — **Annotate every signature, parameters and return alike**, on private helpers as
  well as public functions — except a class `__init__`, which never takes `-> None`.

  *`expected` · counter-sites: see Standing divergences*

## Modules and imports

- `expected` — **Open every module under `app/<feature>/` with
  `from __future__ import annotations`.**
  On Python 3.12 the `X | None` syntax already works unaided, so that is not the reason. The
  reason is forward references: `UserOut.from_user` is annotated `-> UserOut` inside the class
  that is still being defined, which is a `NameError` at runtime without this import.

  *`expected` · exemplar `auth/schemas.py`; missing only where Standing divergences says*

- `taste` — **Define a private helper above the function that calls it.** The reader meets it
  before the code that depends on it, and sibling modules doing near-identical jobs keep the same
  order. Graded `taste`: Python has no convention either way, and this tree is split.

  *`taste` · exemplar `auth/router.py::_set_session_cookie` (above `login`); counter-sites: see
  Standing divergences*

## Control flow and failure

- `blocking` — **Attempt the operation and catch the failure; no pre-check in front of the
  attempt.** Checking for a conflict before inserting races another request between the check and
  the write, and the database constraint has to be handled anyway.

  ```python
  # Good — let the constraint fire, translate it
  try:
      db.flush()
  except IntegrityError as exc:
      db.rollback()
      if "uq_venues_name" in str(exc.orig):
          raise VenueNameTaken(data.name) from exc
      raise

  # Bad — check-then-insert
  if db.scalar(select(Venue).where(Venue.name == data.name)):
      raise VenueNameTaken(data.name)
  ```

  Validating a payload before acting on it is a different thing and stays legal —
  `_validate_reference_codes` is not a pre-check in this sense.

  *`blocking` · exemplars `venues/service.py::create_venue`, `::update_venue`*

- `expected` — **Test a possibly-absent object with `is None`, never a falsy check.** A SQLAlchemy
  row, an empty string and an empty list are all falsy for different reasons; `is None` tests the
  one you meant.

  *`expected` · exemplar `auth/service.py::get_session_user`*

- `expected` — **`except Exception` is not a handler.** A blind catch routes the bug it was not
  written for — a typo's `AttributeError`, a `KeyError` from a renamed field — into the branch
  built for a database failure.

  *`expected` · one licensed counter-site, see Standing divergences*

- `taste` — **One `except` per exception type, narrowest first; never group types in a tuple.**
  Handlers diverge over time, and a grouped block lets the next person change one type's
  behaviour without noticing they changed the other's. Graded `taste`: `except (A, B):` is
  ordinary, idiomatic Python, so this is a house preference rather than a correctness rule.

  *`taste` · counter-sites: see Standing divergences*

- `expected` — **Suppress the exception chain with `from None` when a router translates a service
  exception into an `HTTPException`.** The domain exception has already been handled and
  converted; leaving it chained puts an irrelevant "During handling of the above exception" block
  in the log for an ordinary 404.

  *`expected` · exemplars `venues/router.py::get_venue`, `::create_venue`, `::update_venue`*

## Types and data

- `expected` — **Every fixed literal becomes a named module-level constant**, and a
  module-private one takes a leading underscore. The name is the documentation, and one place
  changes when the value does.

  *`expected` · exemplars the scrypt parameters at the top of `auth/passwords.py`,
  `INVALID_CREDENTIALS_MESSAGE` in `auth/router.py`, `_SCALAR_FIELDS` in `venues/service.py`;
  counter-site: see Standing divergences*

- `expected` — **Return several values as one typed object, never a bare tuple.** A tuple makes
  the caller unpack positionally, so adding a third value breaks every call site silently.

  *`expected` · counter-sites: see Standing
  divergences*

- `expected` — **No field defaults on a response schema.** Every field is populated explicitly at
  construction. A default lets a field the caller forgot ship as `None` or `0` to the frontend,
  where it surfaces as a blank cell rather than an error. Defaults on *request* schemas are
  different and stay legal — there, the default is what the client legitimately omitted.

  ```python
  # Good — VenueOut declares no defaults; from_venue must supply every field
  class VenueOut(BaseModel):
      description: str | None
      setup_minutes_default: int


  # Bad — a forgotten field silently becomes None
  class VenueOut(BaseModel):
      description: str | None = None
  ```

  *`expected` · exemplars `venues/schemas.py::VenueOut`, `auth/schemas.py::UserOut`;
  counter-site: see Standing divergences*

- `expected` — **A constructed timestamp carries its timezone:** `datetime.now(UTC)`, never the
  naive `datetime.now()` or the deprecated `datetime.utcnow()`. A naive value written to an aware
  column is wrong by the host's offset and silent about it.

  *`expected` · already holds: `auth/service.py::create_session`, `::get_session_user`,
  `::revoke_session`*

- `expected` — **Parse anything from outside the process into a Pydantic model before reading a
  field off it.** Dict access fails where the value is used; validation fails where the schema
  changed.

  *`expected` · exemplar `venues/router.py::reference_data`*

## HTTP surface

- `expected` — **A URL names a resource and nothing else.** The action lives in the HTTP method —
  `PATCH /venues/{id}`, not `POST /venues/{id}/update`. A partial update is `PATCH`, a full
  replacement is `PUT`.

  *`expected` · exemplars `GET /venues`, `GET /venues/{venue_id}`, `POST /venues` and
  `PATCH /venues/{venue_id}` in `venues/router.py`; counter-sites: see Standing divergences*

- `expected` — **Never trust the client with a security-relevant value.** It is generated
  server-side or it is not trusted.

  *`expected` · exemplar `auth/service.py::create_session`, where the session token comes from
  `secrets.token_urlsafe`*

- `expected` — **Write a user-facing error message as a complete sentence: second person, capital
  first word, terminal period.** Name what was refused; never speculate about the cause; never
  interpolate a runtime number. Two messages never share one string.

  ```python
  # Good
  INVALID_CREDENTIALS_MESSAGE = "Invalid email or password."
  NOT_PERMITTED_MESSAGE = "Your role does not permit this action."

  # Bad
  INVALID_CREDENTIALS_MESSAGE = "invalid credentials"
  NOT_PERMITTED_MESSAGE = "forbidden"
  ```

  *`expected` · exemplars `INVALID_CREDENTIALS_MESSAGE` in `auth/router.py`, the 401 and 403
  details in `auth/deps.py`; asserted in `tests/auth/test_login_logout.py::`
  `test_wrong_password_and_unknown_email_get_identical_responses`*

## Traceability

- `expected` — **Name the story and the acceptance criterion in the docstring of anything that
  implements one.** The module docstring carries the story, the function docstring the AC.
  Reviewers and the Week 12 submission both need to match code to a criterion.

  ```python
  """HTTP endpoints for story 1.1 (login / logout) and the `me` lookup used by the RBAC UI (1.2)."""

  def login(...):
      """AC1: valid credentials start a session. AC2: any failure returns the same generic 401."""
  ```

  *`expected` · exemplars `auth/router.py` (the module docstring and `login`),
  `venues/router.py::create_venue`, `venues/service.py::create_venue`*

## Considered and rejected

Conventions weighed against this codebase and left out, recorded so nobody re-adds them:

| Convention | Why not here |
| --- | --- |
| **No comments or docstrings — a comment is an admission the code failed to say it** | Directly contradicts the Traceability rule above, which this project's grading rubric depends on. Every module in `app/` is docstringed, and the story/AC docstrings are the audit trail. Carrying this would mean deleting the thing that makes the code gradeable. |
| `*` only in front of a dangerous default | Contradicted by the local majority — see Function signatures. |
| `ErrorCode` / `AppHttpExceptionBase`, no-argument exception classes | No such hierarchy here; services raise plain Python exceptions that routers translate. |
| CRUD / gateway / middleware / validators layer rules | Different architecture — this project is router / service / schemas / models. |
| Alembic single-head migrations, `RateLimiter`, `EndpointLogLevel`, Loguru over `print()`, Azure blob paths | None of these exist in this project. |

## Standing divergences

Rules the existing tree violates. Naming them here is what stops someone copying a violation in
good faith because they found it first. **Fix these under their own ticket, never opportunistically
in an unrelated PR.**

| Rule | Violating sites | Status |
| --- | --- | --- |
| Annotate every signature | `uv run ruff check --select ANN app` lists them (an `__init__` without `-> None` is not a violation of this rule) | carried rule, newly adopted — existing code predates it |
| Return a typed object, not a tuple | `auth/service.py::create_session` (`tuple[UserSession, str]`), `venues/service.py::daily_window` and `::_search_period`, `dbtool/docs.py::generate` | carried rule, newly adopted |
| A URL names a resource | `POST /auth/login`, `POST /auth/logout` | licensed exception — `POST /auth/login` is near-universal convention and both the backend and e2e tests call the path; not a precedent for other features |
| A URL names a resource | `POST /events/{event_id}/submit`, `/approve`, `/reject`; `POST /bookings/{booking_id}/approve`, `/reject`, `/withdraw` | pre-existing, undecided — each is a state transition with its own rules and audit record, so it was modelled as an action; agree as a team before adding another |
| Every fixed literal becomes a named constant | the error sentences written inline in `coordination/router.py`, one of which repeats `NOT_PERMITTED_MESSAGE` from `auth/deps.py` | pre-existing, not precedent |
| No field defaults on a response schema | `coordination/schemas.py::CoordinatorOption` (`department = None`), `venues/schemas.py::ReferenceItem` (`description = None`) | pre-existing, not precedent |
| One `except` per type | `venues/router.py::update_venue`, `coordination/router.py::assign_coordinator`, `auth/passwords.py::verify_password`, `dbtool/__main__.py::main` | pre-existing, not precedent |
| `except Exception` is not a handler | `events/service.py::_replace_cover_image` | licensed exception — it deletes the file it has just written and re-raises, so nothing is swallowed |
| Private helper defined above its caller | helpers below their callers in `venues/service.py`, `bookings/service.py` and `dbtool/docs.py` | pre-existing, not precedent — `auth/router.py::_set_session_cookie` shows the intended shape |
| `is_` on booleans | parameters that read as flags: `include_withdrawn` (`venues/service.py::list_venues`), `only_present` (`::_replace_characteristics`), `commit` (`common/audit.py::record_audit`, `notifications/service.py::notify`), `required` (`events/service.py::_check_registration`), and the `force` / `with_seed` / `with_docs` options in `dbtool/__main__.py` | licensed exception — each reads as a flag and the prefix would worsen it |
| `from __future__ import annotations` | `db.py`, `config.py`, `main.py` | licensed exception — none defers an annotation |
| Services raise domain exceptions for failure | `auth/service.py::authenticate` returns `None` | licensed exception — story 1.1 AC2 requires the failure modes be indistinguishable |
| Routers do HTTP only; services own the transaction | `auth/router.py::login` and `::logout` call `record_audit` with the default `commit=True` | pre-existing, not precedent — `venues/service.py::create_venue` shows the intended shape |

## Maintaining this file

- **Every rule describes something real.** If nobody has ever got it wrong, it is not a rule
  yet. A new rule needs a site in this repo it can point at — an exemplar that does it right or
  a counter-site that does not. Record a correction in the PR thread; add it here only when a
  second, independent case appears.
- **Record divergences by file and function**, not "some legacy code does this", and never by
  line number or count: both go stale with the next edit nearby.
- **Match the way it is already done here, even when the local choice is worse.** Settle a dispute
  by the majority of existing untouched code, name the canonical module to copy from, and raise
  standardization as its own PR rather than fixing it in passing.
