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
signature* rule below. It reports **8 violations in feature code** today (`app/auth`, `app/venues`,
`app/common`, `app/db.py`) and more under `app/dbtool` and `tests/`. Clear those and add `ANN` to
`select`; the rule then leaves this file.

**Provenance.** Every rule ends with the sites in this repo it was drawn from — an *exemplar*
that does it right, a *counter-site* that does not, or a count of both. That anchor is the only
justification a rule gets here: open the file and check. A rule with nothing to point at was
removed rather than kept on the strength of where it came from. See
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

  *`expected` · already holds here:
  `venues/router.py:67` ↔ `venues/service.py:99`, and likewise for `list_venues`, `get_venue`*

- `taste` — **Prefix a boolean with `is_`.** The columns already do (`is_active`, `is_internal`).
  Graded `taste` rather than `expected` because three existing parameters read naturally without
  it and forcing `is_include_withdrawn` would be worse — see Standing divergences.

  *`taste` · downgraded for this tree ·
  exemplars `auth/models.py` (`is_active`); counter-sites `venues/service.py:70`,
  `venues/service.py:207`*

## Queries and sessions

- `blocking` — **Query with `select()` plus `db.scalar()` / `db.scalars()`, never `db.query()`.**
  `db.query()` is the SQLAlchemy 1.x API. It still runs on 2.0, so nothing fails — it just types
  poorly and reads differently from every other query in the tree.

  ```python
  # Good
  user = db.scalar(select(User).where(User.email == email.strip()))

  # Bad — legacy 1.x API
  user = db.query(User).filter(User.email == email).first()
  ```

  *`blocking` · exemplars `app/auth/service.py:32`, `app/venues/service.py:71`; 8 uses of
  `select()` in `app/`, 0 of `db.query()`*

- `expected` — **Filtering, sorting and limiting happen in SQL, not in Python.** Bend this only
  where moving the work would change the result.

  *`expected` · exemplar
  `venues/service.py:70-74`, which filters `status` in the statement rather than the list*

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
  dangerous default. This tree has 9 sites doing it the broader way and none doing it the other
  way, so the local majority governs.

  *`expected` · exemplars `venues/service.py:99`, `common/audit.py:36`, `passwords.py:28`;
  9 sites across `auth/`, `venues/` and `dbtool/`*

- `expected` — **Annotate every signature, parameters and return alike**, on private helpers as
  well as public functions — except a class `__init__`, which never takes `-> None`.

  *`expected` · 9 counter-sites, see
  Standing divergences*

## Modules and imports

- `expected` — **Open every module under `app/<feature>/` with
  `from __future__ import annotations`.**
  On Python 3.12 the `X | None` syntax already works unaided, so that is not the reason. The
  reason is forward references: `UserOut.from_user` is annotated `-> UserOut` inside the class
  that is still being defined, which is a `NameError` at runtime without this import.

  *`expected` · exemplar `app/auth/schemas.py:1`; present in 16 of 19 modules*

- `taste` — **Define a private helper above the function that calls it.** The reader meets it
  before the code that depends on it, and sibling modules doing near-identical jobs keep the same
  order. Graded `taste`: Python has no convention either way, and this tree is split.

  *`taste` · exemplar `auth/router.py:22`
  (`_set_session_cookie` above `login`); counter-site `venues/service.py:186`*

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

  *`blocking` · exemplars
  `venues/service.py:109`, `:163`*

- `expected` — **Test a possibly-absent object with `is None`, never a falsy check.** A SQLAlchemy
  row, an empty string and an empty list are all falsy for different reasons; `is None` tests the
  one you meant.

  *`expected` · 12 uses across 5 modules,
  exemplar `auth/service.py:64`*

- `expected` — **`except Exception` is not a handler.** A blind catch routes the bug it was not
  written for — a typo's `AttributeError`, a `KeyError` from a renamed field — into the branch
  built for a database failure.

  *`expected` · 0 counter-sites in `app/`*

- `taste` — **One `except` per exception type, narrowest first; never group types in a tuple.**
  Handlers diverge over time, and a grouped block lets the next person change one type's
  behaviour without noticing they changed the other's. Graded `taste`: `except (A, B):` is
  ordinary, idiomatic Python, so this is a house preference rather than a correctness rule.

  *`taste` · counter-site
  `venues/router.py:96`, which groups `UnknownReferenceCode` and `InvalidOperatingHours`*

- `expected` — **Suppress the exception chain with `from None` when a router translates a service
  exception into an `HTTPException`.** The domain exception has already been handled and
  converted; leaving it chained puts an irrelevant "During handling of the above exception" block
  in the log for an ordinary 404.

  *`expected` · exemplars `venues/router.py:63`, `:76`, `:93`; all 6 translations do this*

## Types and data

- `expected` — **Every fixed literal becomes a named module-level constant**, and a
  module-private one takes a leading underscore. The name is the documentation, and one place
  changes when the value does.

  *`expected` · already holds:
  `passwords.py:18-25`, `auth/router.py:19`, `venues/service.py:85`*

- `expected` — **Return several values as one typed object, never a bare tuple.** A tuple makes
  the caller unpack positionally, so adding a third value breaks every call site silently.

  *`expected` · 2 counter-sites, see Standing
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

  *`expected` · exemplars `venues/schemas.py` (`VenueOut`, 16 fields, no defaults),
  `auth/schemas.py:16` (`UserOut`, 9 fields, no defaults); 0 counter-sites*

- `expected` — **A constructed timestamp carries its timezone:** `datetime.now(UTC)`, never the
  naive `datetime.now()` or the deprecated `datetime.utcnow()`. A naive value written to an aware
  column is wrong by the host's offset and silent about it.

  *`expected` · already holds:
  `auth/service.py:51`, `:66`, `:80`*

- `expected` — **Parse anything from outside the process into a Pydantic model before reading a
  field off it.** Dict access fails where the value is used; validation fails where the schema
  changed.

  *`expected` · exemplar `venues/router.py:39`*

## HTTP surface

- `expected` — **A URL names a resource and nothing else.** The action lives in the HTTP method —
  `PATCH /venues/{id}`, not `POST /venues/{id}/update`. A partial update is `PATCH`, a full
  replacement is `PUT`.

  *`expected` · exemplars
  `venues/router.py:47`, `:58`, `:66`, `:82`; counter-sites `auth/router.py:38`, `:57`*

- `expected` — **Never trust the client with a security-relevant value.** It is generated
  server-side or it is not trusted.

  *`expected` · exemplar
  `auth/service.py:47`, where the session token comes from `secrets.token_urlsafe`*

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

  *`expected` · exemplars
  `auth/router.py:19`, `auth/deps.py:33`, `:47`; asserted in `tests/auth/test_login_logout.py:77`
  and the e2e check at `tests/e2e/auth.spec.ts:29`*

## Traceability

- `expected` — **Name the story and the acceptance criterion in the docstring of anything that
  implements one.** The module docstring carries the story, the function docstring the AC.
  Reviewers and the Week 12 submission both need to match code to a criterion.

  ```python
  """HTTP endpoints for story 1.1 (login / logout) and the `me` lookup used by the RBAC UI (1.2)."""

  def login(...):
      """AC1: valid credentials start a session. AC2: any failure returns the same generic 401."""
  ```

  *`expected` · exemplars `auth/router.py:1`, `:45`; `venues/router.py:72`; `venues/service.py:100`*

## Considered and rejected

Conventions weighed against this codebase and left out, recorded so nobody re-adds them:

| Convention | Why not here |
| --- | --- |
| **No comments or docstrings — a comment is an admission the code failed to say it** | Directly contradicts the Traceability rule above, which this project's grading rubric depends on. Every module in `app/` is docstringed, and the story/AC docstrings are the audit trail. Carrying this would mean deleting the thing that makes the code gradeable. |
| `*` only in front of a dangerous default | Contradicted by 9 local sites — see Function signatures. |
| `ErrorCode` / `AppHttpExceptionBase`, no-argument exception classes | No such hierarchy here; services raise plain Python exceptions that routers translate. |
| CRUD / gateway / middleware / validators layer rules | Different architecture — this project is router / service / schemas / models. |
| Alembic single-head migrations, `RateLimiter`, `EndpointLogLevel`, Loguru over `print()`, Azure blob paths | None of these exist in this project. |

## Standing divergences

Rules the existing tree violates. Naming them here is what stops someone copying a violation in
good faith because they found it first. **Fix these under their own ticket, never opportunistically
in an unrelated PR.**

| Rule | Violating sites | Status |
| --- | --- | --- |
| Annotate every signature | 9: `venues/schemas.py:77`, `:106`, `:136`, `:140`; `venues/service.py:227`; `auth/deps.py:40`; `db.py:45`; `dbtool/docs.py:461`, `:652` | carried rule, newly adopted — existing code predates it |
| Return a typed object, not a tuple | 2: `auth/service.py:45` (`tuple[UserSession, str]`), `dbtool/docs.py:710` | carried rule, newly adopted |
| A URL names a resource | 2: `auth/router.py:38` (`/login`), `:57` (`/logout`) | licensed exception — `POST /auth/login` is near-universal convention and both the backend and e2e tests call the path; not a precedent for other features |
| One `except` per type | 1: `venues/router.py:96` | pre-existing, not precedent |
| Private helper defined above its caller | `venues/service.py:186-238` (helper block at the bottom) | pre-existing, not precedent — `auth/router.py:22` shows the intended shape |
| `is_` on booleans | 3: `venues/service.py:70` (`include_withdrawn`), `:207` (`only_present`), `common/audit.py:44` (`commit`) | licensed exception — all three read as flags and the prefix would worsen them |
| `from __future__ import annotations` | 3: `db.py`, `config.py`, `main.py` | licensed exception — none defers an annotation |
| Services raise domain exceptions for failure | `auth/service.py:26` returns `None` | licensed exception — story 1.1 AC2 requires the failure modes be indistinguishable |
| Routers do HTTP only; services own the transaction | `auth/router.py:52`, `:63` call `record_audit` with the default `commit=True` | pre-existing, not precedent — `venues/service.py:116` shows the intended shape |

## Maintaining this file

- **Every rule describes something real.** If nobody has ever got it wrong, it is not a rule
  yet. A new rule needs a site in this repo it can point at — an exemplar that does it right or
  a counter-site that does not. Record a correction in the PR thread; add it here only when a
  second, independent case appears.
- **Record divergences with counts**, not "some legacy code does this".
- **Match the way it is already done here, even when the local choice is worse.** Settle a dispute
  by the majority of existing untouched code, name the canonical module to copy from, and raise
  standardization as its own PR rather than fixing it in passing.
