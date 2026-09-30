# frontend/STYLE.md

Personal coding idioms for `frontend/`. Follow these when writing or reviewing code. This
document only contains things Claude would get wrong without being told: not standard React or
TypeScript conventions, and not patterns already covered in [CLAUDE.md](CLAUDE.md).

**What these rules are for.** One idea sits under nearly all of them: _a reader should not have
to open the function body, or another file, to know what something does._ Names carry type and
intent, failures are typed and loud, values are never unnamed, and indirection has to earn its
place. Where a rule below looks fussy, that is the thing it is protecting.

**Automated enforcement.** `oxlint` runs the `react`, `typescript` and `oxc` plugins with exactly
two explicitly configured rules — `react/rules-of-hooks` (error) and `react/only-export-components`
(warn) — plus each plugin's default correctness set. `prettier` owns formatting: no semicolons,
single quotes, trailing commas, 100 columns. There is **no type-aware linting**; `tsc -b` inside
`npm run build` is the only type check, and there is no test runner at all. Everything below is
enforced by review.

**Provenance.** Every rule ends with the sites in this repo it was drawn from — an _exemplar_
that does it right, or a _counter-site_ that does not — named by file and component, function or
class, never by line number, so an anchor survives edits around it. That anchor is the only
justification a rule gets here: open the file and check. A rule with nothing to point at was
removed rather than kept on the strength of where it came from. See
[Considered and rejected](#considered-and-rejected) for what was deliberately left out.

**Rule strength.** Every rule carries its weight, and a non-blocking weight is genuinely the
author's call. Never flatten a `taste` into a "must".

| Grade      | Meaning                                                 |
| ---------- | ------------------------------------------------------- |
| `blocking` | A reviewer blocks the PR on it.                         |
| `expected` | The default. Deviating needs a reason stated in the PR. |
| `taste`    | Raised as a suggestion, the author decides.             |

## Constants and magic values

- `blocking` — **A string literal used in more than one file becomes one exported constant,
  imported everywhere.**
  Permission codes are the live case: they are compared as plain strings against the backend, so a
  typo in one of the two copies does not fail to compile, does not throw, and does not show an
  error — the nav link simply stops appearing.

  ```tsx
  // Good — one definition, imported by both
  // src/auth/permissions.ts
  export const PERMISSIONS = {
    VENUES_MANAGE: 'venues:manage',
    // …
  } as const

  // Bad — the same literal in two files, free to drift
  <RequirePermission permission="venues:manage" />          // App.tsx
  { to: '/venues', permission: 'venues:manage' }            // navigation.ts
  ```

  _`blocking` · exemplar `PERMISSIONS` in `src/auth/permissions.ts`, imported by `src/App.tsx`
  and `src/layout/navigation.ts`; once violated, see Standing divergences_

## Styling

- `expected` — **Use the custom properties from `src/index.css` for colour; never a raw hex or
  `rgba()` in `src/App.css`.**
  `index.css` defines the tokens and redefines the colour ones under
  `@media (prefers-color-scheme: dark)`, so a token adapts and a literal does not. This was not
  hypothetical: `.error` used to be `#b91c1c` on a `--bg` of `#16171d` in dark mode — dark red
  text on a near-black panel, which is the one message the alert rule above exists to make
  readable. Opacity-composited colours have the same defect, compositing against whatever sits
  behind them. The token values are the Figma prototype's Tailwind classes; `--radius-sm` is `0`
  on purpose because the prototype's `rounded-sm` resolves to 0px.

  ```css
  /* Good */
  .error {
    color: var(--danger-deep);
    background: var(--danger-bg);
    border-color: var(--danger-border);
  }

  /* Bad — fixed to one theme */
  .error { color: #b91c1c; background: rgba(239, 68, 68, 0.1); }
  ```

  Adding a colour means adding a token to `index.css` in **both** the light block and the
  `prefers-color-scheme: dark` block, then referencing it.

  _`expected` · exemplars `src/App.css` (`.error`, `.badge-active`, `.calendar-entry-danger`);
  every colour in `src/App.css` is a `var(--…)`_

## Control flow and failure

- `blocking` — **Render every API error as `<p role="alert" className="error">` with the text from
  `formatApiError`.**
  `role="alert"` is not decoration: e2e specs locate the message with
  `getByRole('alert')`, so a visually identical `<p className="error">` passes review, renders
  fine, and fails the suite.

  ```tsx
  // Good
  {error && (
    <p role="alert" className="error">
      {error}
    </p>
  )}

  // Bad — invisible to getByRole('alert')
  {error && <p className="error">{error}</p>}
  ```

  _`blocking` · exemplars `VenueDetailPage`, `LoginPage`, `VenueFormPage`; depended on by
  every e2e spec that asserts an error with `getByRole('alert')`, `tests/e2e/auth.spec.ts`
  among them_

- `expected` — **Never leave a `console.log` in committed code.** If something needs surfacing, it
  needs surfacing to the user through the error rule above.

  _`expected` · `git grep console.log frontend/src` finds none_

## Data fetching

- `expected` — **Guard every fetching effect with a `cancelled` flag and return the cleanup that
  sets it.**
  React 19 runs effects twice in StrictMode, and a page can unmount while a request is still in
  flight. Without the flag a late response sets state on a dead component.

  ```tsx
  // Good — AuthProvider's session lookup
  useEffect(() => {
    let cancelled = false
    listVenues(includeWithdrawn)
      .then((data) => {
        if (!cancelled) setVenues(data)
      })
      .catch(() => {
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [includeWithdrawn])

  // Bad — no guard, no cleanup
  useEffect(() => {
    listVenues(includeWithdrawn).then(setVenues)
  }, [includeWithdrawn])
  ```

  _`expected` · exemplars `src/shared/useLoaded.ts` (the pattern, written once for every page that only
  loads on arrival), the session-restoring effect in `AuthProvider`, `VenueFormPage`_

- `expected` — **A custom hook returns a named object, never a tuple.** Positional unpacking
  breaks silently when the hook grows a new value: every call site shifts by one and still
  compiles. A named object lets each consumer take only what it needs and stay unaffected when the
  hook gains a member.

  ```tsx
  // Good — each consumer destructures the subset it needs
  const { user, isLoading } = useAuth()
  const { can } = useAuth()
  const { user, can, signOut } = useAuth()

  // Bad — adding a sixth value silently reshuffles every call site
  const [user, isLoading, signIn, signOut, can] = useAuth()
  ```

  This is the same rule as the backend's _return several values as one typed object_; both exist
  because a positional container has no name to fail against.

  _`expected` · exemplar `useAuth` in `src/auth/authContext.ts`, which returns the named
  `AuthContextValue`, consumed by `RequireAuth`, `LoginPage`, `AppLayout` and `HomePage`_

- `expected` — **A `useCallback` dependency array is exhaustive.** Every component-scoped value the
  callback reads goes in the array, or the value is hoisted to module scope so it cannot go stale.
  Nothing lints this here — there is no `exhaustive-deps` rule configured — so it is on review.

  _`expected` · exemplar `can` in `AuthProvider` (`src/auth/AuthProvider.tsx`), which depends
  on `[user]`_

## Naming

- `expected` — **Prefix a boolean with `is`, `can` or `has`.** A plain participle does not read as
  a predicate at the call site: `isLoading` reads as a question, `loading` reads as a noun.

  ```tsx
  // Good
  const [isSaving, setIsSaving] = useState(false)

  // Bad
  const [saving, setSaving] = useState(false)
  ```

  _`expected` · once violated, see Standing divergences_

- `expected` — **Name a function for the specific domain operation, as a verb phrase.** Not a
  generic description of the operation in the abstract, and never a name that reads like a class.

  _`expected` · exemplars
  `src/api/venues.ts` (`fetchVenueReferenceData`), `src/auth/homeFor.ts`_

## Component patterns

- `expected` — **Extract an event handler as a named function instead of inlining an arrow in
  JSX.** Inline handlers make the markup harder to scan and the logic impossible to reuse. A
  one-line setter that reads as data — `onChange={(e) => set('name', e.target.value)}` in a form
  built from a field map — is the licensed exception.

  ```tsx
  // Good
  async function handleSignOut() {
    try {
      await signOut()
    } catch {
      // The local session is already cleared by signOut, so the browser is signed out either way.
    }
    navigate(LOGIN_PATH, { replace: true })
  }
  <button type="button" onClick={handleSignOut}>Sign out</button>

  // Bad
  <button onClick={async () => { await signOut(); navigate(LOGIN_PATH) }}>Sign out</button>
  ```

  _`expected` · exemplar `handleSignOut` in `AppLayout`; counter-sites, see Standing
  divergences_

- `taste` — **Render loading, empty and error as three separate explicit states.**
  A single spinner-or-content branch makes "no venues yet" look like a failure.

  ```tsx
  {error && <p role="alert" className="error">{error}</p>}
  {result === null && !error && <LoadingState label="Loading venues…" />}
  {result !== null && result.venues.length === 0 && (
    <EmptyState>No venues are currently in service.</EmptyState>
  )}
  ```

  _`taste` · exemplar the results list in `VenueCataloguePage`_

## Types

- `expected` — **Use `interface` for a hand-written object shape and `type` only for a computed or
  derived type** — a union, a utility type, a mapped type.

  ```tsx
  // Good
  export interface VenueSummary { id: string; name: string }
  export type VenueStatus = 'ACTIVE' | 'WITHDRAWN'

  // Bad — object shape as a type alias
  export type VenueSummary = { id: string; name: string }
  ```

  _`expected` · already holds throughout: `ReferenceItem` and `VenueSummary` (interfaces) and
  `VenueStatus` (a union, as `type`) in `src/api/venues.ts`_

- `expected` — **Pass an explicit type parameter to `useState` when the initial value does not
  carry the domain type** — a union, an enum, or anything nullable. Inference from `false`, `0` or
  `''` is correct and idiomatic TypeScript; forcing `useState<boolean>(false)` adds nothing.
  The test is whether the initial value tells the reader what the state can hold: `useState(null)`
  does not, `useState<VenueSummary[] | null>(null)` does.

  ```tsx
  // Good — the domain type would otherwise be lost
  const [venues, setVenues] = useState<VenueSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Good — `false` already says everything
  const [isSaving, setIsSaving] = useState(false)
  ```

  _`expected` · exemplars the `data` and `error` state in `useLoaded` (`src/shared/useLoaded.ts`),
  the `user` state in `AuthProvider`, the form state in `VenueFormPage`_

- `taste` — **Import types with the inline `type` modifier when the module also supplies values;
  use a standalone `import type` line only when nothing but types is imported.**

  ```tsx
  // Good — module supplies both
  import { fetchCurrentUser, login, logout, type CurrentUser } from '../api/auth'
  // Good — nothing but a type
  import type { CurrentUser } from '../api/auth'
  ```

  **A stricter variant of this rule exists elsewhere**, splitting every type import onto its own
  `import type` line. This tree uses the inline form wherever a module supplies both, so the local
  majority governs.

  Graded `taste`: the only argument for it is matching what is already here, which is not enough
  to block a PR over.

  _`taste` · exemplars the `../api/auth` import in `src/auth/AuthProvider.tsx`; standalone form
  in `src/auth/authContext.ts`_

## Traceability

- `expected` — **Name the story and acceptance criterion in a docblock above anything that
  implements one.** A component, route guard, helper or context field that exists because of an AC
  says so in one line. This is the only link between a page and the criterion it satisfies — the
  backend has `@pytest.mark.story` and the e2e specs have story-prefixed titles, and without this
  the frontend is the one layer a reviewer cannot trace.

  ```tsx
  /**
   * Story 1.2 AC3/AC4: a direct URL to a page outside the role shows "Not permitted" instead of the
   * page. This is a courtesy; the backend refuses the page's API calls regardless.
   */
  export function RequirePermission({ permission }: { permission: Permission }) { ... }

  /** Story 1.2 AC2: whether the signed-in role holds a permission, to hide what it cannot use. */
  can: (permission: Permission) => boolean
  ```

  _`expected` · exemplars `VenueCataloguePage`, `VenueFormPage`, `RequirePermission` in
  `src/auth/RequireAuth.tsx`, `homeFor`, the `can` member of `AuthContextValue`_

## Considered and rejected

Conventions weighed against this codebase and left out, recorded so nobody re-adds them:

| Convention                                                                                            | Why not here                                                                                                                                                                                                                                                                              |
| ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **No comments or JSDoc — names must be self-documenting**                                             | This tree's docblocks carry story and AC references that the grading rubric depends on, and the cross-boundary notes (`CurrentUser` in `src/api/auth.ts`, `PERMISSIONS` in `src/auth/permissions.ts`) are the only thing linking a type or a permission string to its backend definition. |
| `[Category][Context].tsx` component naming (`FormUpdateUser`, `DialogDeleteConversation`)             | This tree is consistently `[Context]Page` (`VenueFormPage`, `LoginPage`, `HomePage`). Adopting the other scheme would rename every file for no gain.                                                                                                                                      |
| Semantic colour tokens, no raw palette or opacity-composite classes, `cn()` over string interpolation | Tailwind-specific. There is no Tailwind, no `cn()` and no token config here — styling is plain global CSS with custom properties.                                                                                                                                                         |
| Dialog, Table, Button, Form, Skeleton and Notice patterns                                             | All built on Radix, shadcn, TanStack Table and react-hook-form. None is installed here, and [CLAUDE.md](CLAUDE.md) forbids adding them without team agreement.                                                                                                                            |
| Shared helpers belong in `src/lib/utils.ts`                                                           | No `lib/` folder here; the equivalent shared module is `src/api/client.ts`.                                                                                                                                                                                                               |

## Standing divergences

Rules the existing tree violates. Naming them here is what stops someone copying a violation in
good faith because they found it first. **Fix these under their own ticket, never opportunistically
in an unrelated PR.**

| Rule                                          | Violating sites                                                                                                                  | Status                                                                    |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| One exported constant for a cross-file string | none: permission codes are constants in `src/auth/permissions.ts` (story 1.2)                                                    | resolved                                                                  |
| Extract named handlers                        | single-expression inline arrows in the pages, most in `EventRequestFormPage` and `VenueFormPage`; no multi-statement one remains | carried rule, newly adopted — most are the licensed form-setter shape     |
| Colour comes from a token, never a literal    | none: `src/App.css` is token-only (story c3)                                                                                     | resolved                                                                  |
| Boolean `is`/`can`/`has` prefix               | none left: `loading`, `submitting` and `saving` were renamed                                                                     | resolved                                                                  |
| Components use named exports                  | `App` in `src/App.tsx`                                                                                                           | licensed exception — conventional default export for the Vite entry point |

## Maintaining this file

- **Every rule describes something real.** If nobody has ever got it wrong, it is not a rule
  yet. A new rule needs a site in this repo it can point at — an exemplar that does it right or
  a counter-site that does not. Record a correction in the PR thread; add it here only when a
  second, independent case appears.
- **Record divergences by file and component or function**, not "some legacy code does this",
  and never by line number or count: both go stale with the next edit nearby.
- **Match the way it is already done here, even when the local choice is worse.** Settle a dispute
  by the majority of existing untouched code, name the canonical module to copy from, and raise
  standardization as its own PR rather than fixing it in passing.
