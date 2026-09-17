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
that does it right, a _counter-site_ that does not, or a count of both. That anchor is the only
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
  export const PERMISSION_VENUES_MANAGE = 'venues:manage'

  // Bad — the same literal in two files, free to drift
  <RequirePermission permission="venues:manage" />          // App.tsx
  { to: '/venues/manage', permission: 'venues:manage' }     // AppLayout.tsx
  ```

  _`blocking` · last violated at `src/App.tsx:25` and `src/layout/AppLayout.tsx:17` — see
  Standing divergences_

## Styling

- `expected` — **Use the custom properties from `src/index.css` for colour; never a raw hex or
  `rgba()` in `src/App.css`.**
  `index.css` defines 62 tokens and redefines the colour ones under
  `@media (prefers-color-scheme: dark)`, so a token adapts and a literal does not. This was not
  hypothetical: `.error` used to be `#b91c1c` on a `--bg` of `#16171d` in dark mode — dark red
  text on a near-black panel, which is the one message the alert rule above exists to make
  readable. Opacity-composited colours have the same defect, compositing against whatever sits
  behind them. The token values are the Figma prototype's Tailwind classes; `--radius-sm` is `0`
  on purpose because the prototype's `rounded-sm` resolves to 0px.

  ```css
  /* Good */
  .error { color: var(--danger); background: var(--danger-bg); }

  /* Bad — fixed to one theme */
  .error { color: #b91c1c; background: rgba(239, 68, 68, 0.1); }
  ```

  Adding a colour means adding a token to `index.css` in **both** the light block and the
  `prefers-color-scheme: dark` block, then referencing it.

  _`expected` · exemplars `src/App.css` (`.error`, `.badge-active`, `.calendar-entry-danger`);
  0 counter-sites — every colour in `src/App.css` is a `var(--…)`_

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

  _`blocking` · exemplars `src/venues/VenueManagePage.tsx:45`, `src/auth/LoginPage.tsx:81`,
  `src/venues/VenueFormPage.tsx:171`, `:462`; depended on by `tests/e2e/auth.spec.ts:29`_

- `expected` — **Never leave a `console.log` in committed code.** If something needs surfacing, it
  needs surfacing to the user through the error rule above.

  _`expected` · 0 counter-sites_

## Data fetching

- `expected` — **Guard every fetching effect with a `cancelled` flag and return the cleanup that
  sets it.**
  React 19 runs effects twice in StrictMode, and a page can unmount while a request is still in
  flight. Without the flag a late response sets state on a dead component.

  ```tsx
  // Good
  useEffect(() => {
    let cancelled = false
    listVenues(includeWithdrawn)
      .then((data) => {
        if (!cancelled) setVenues(data)
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err))
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

  _`expected` · exemplars `src/venues/VenueManagePage.tsx:13-25`, `src/auth/AuthProvider.tsx:10-25`,
  `src/venues/VenueFormPage.tsx`_

- `expected` — **A custom hook returns a named object, never a tuple.** Positional unpacking
  breaks silently when the hook grows a new value: every call site shifts by one and still
  compiles. A named object lets each consumer take only what it needs and stay unaffected when the
  hook gains a member.

  ```tsx
  // Good — five consumers each destructure a different subset
  const { user, loading } = useAuth()
  const { can } = useAuth()
  const { user, can, signOut } = useAuth()

  // Bad — adding a sixth value silently reshuffles every call site
  const [user, loading, signIn, signOut, can] = useAuth()
  ```

  This is the same rule as the backend's _return several values as one typed object_; both exist
  because a positional container has no name to fail against.

  _`expected` · exemplar `src/auth/authContext.ts:17` (`useAuth` returns `AuthContextValue`, 5
  named members), consumed at `RequireAuth.tsx:6`, `:18`, `LoginPage.tsx:17`, `AppLayout.tsx:21`,
  `HomePage.tsx:4`; 0 counter-sites_

- `expected` — **A `useCallback` dependency array is exhaustive.** Every component-scoped value the
  callback reads goes in the array, or the value is hoisted to module scope so it cannot go stale.
  Nothing lints this here — there is no `exhaustive-deps` rule configured — so it is on review.

  _`expected` · exemplar
  `src/auth/AuthProvider.tsx:41-44`, where `can` correctly depends on `[user]`_

## Naming

- `expected` — **Prefix a boolean with `is`, `can` or `has`.** A plain participle does not read as
  a predicate at the call site: `isLoading` reads as a question, `loading` reads as a noun.

  ```tsx
  // Good
  const [isSaving, setIsSaving] = useState<boolean>(false)

  // Bad
  const [saving, setSaving] = useState(false)
  ```

  _`expected` · 4 counter-sites, see
  Standing divergences_

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
    await signOut()
    navigate('/login', { replace: true })
  }
  <button type="button" onClick={handleSignOut}>Sign out</button>

  // Bad
  <button onClick={async () => { await signOut(); navigate('/login') }}>Sign out</button>
  ```

  _`expected` · exemplar
  `src/layout/AppLayout.tsx:24`; 22 inline handlers remain, see Standing divergences_

- `taste` — **Render loading, empty and error as three separate explicit states.**
  A single spinner-or-content branch makes "no venues yet" look like a failure.

  ```tsx
  {error && <p role="alert" className="error">{error}</p>}
  {venues === null && !error && <p className="muted">Loading…</p>}
  {venues && venues.length === 0 && <p className="muted">No venues recorded yet.</p>}
  ```

  _`taste` · exemplar `src/venues/VenueManagePage.tsx:44-50`_

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

  _`expected` · already holds throughout:
  `src/api/venues.ts:3`, `:17` (interfaces) and `:15` (union as `type`)_

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

  _`expected` · exemplars `src/venues/VenueManagePage.tsx:8`, `:10`;
  `src/auth/AuthProvider.tsx:6`; `src/venues/VenueFormPage.tsx:148-150`; 0 counter-sites —
  every nullable state in the tree already annotates, every primitive correctly infers_

- `taste` — **Import types with the inline `type` modifier when the module also supplies values;
  use a standalone `import type` line only when nothing but types is imported.**

  ```tsx
  // Good — module supplies both
  import { fetchMe, login, logout, type CurrentUser } from '../api/auth'
  // Good — nothing but a type
  import type { CurrentUser } from '../api/auth'
  ```

  **A stricter variant of this rule exists elsewhere**, splitting every type import onto its own
  `import type` line. This tree has 7 inline sites and 1 standalone, so the local majority governs.

  Graded `taste`: the only argument for it is matching what is already here, which is not enough
  to block a PR over.

  _`taste` · exemplars `src/auth/AuthProvider.tsx:2`, `src/venues/VenueManagePage.tsx:4`;
  standalone form at `src/auth/authContext.ts:2`_

## Traceability

- `expected` — **Name the story and acceptance criterion in a docblock above anything that
  implements one.** A component, route guard, helper or context field that exists because of an AC
  says so in one line. This is the only link between a page and the criterion it satisfies — the
  backend has `@pytest.mark.story` and the e2e specs have story-prefixed titles, and without this
  the frontend is the one layer a reviewer cannot trace.

  ```tsx
  /** Story 8.3 - Venue Staff entry point: list venues, jump to create / edit. */
  export function VenueManagePage() { ... }

  /** Story 1.2 AC2: hide navigation / actions the role may not perform. */
  can: (permission: string) => boolean
  ```

  _`expected` · exemplars `src/venues/VenueManagePage.tsx:6`, `src/venues/VenueFormPage.tsx:143`,
  `src/auth/RequireAuth.tsx:14`, `src/auth/homeFor.ts:2`, `src/auth/authContext.ts:11`,
  `src/layout/AppLayout.tsx:7`; 9 sites in `src/`_

## Considered and rejected

Conventions weighed against this codebase and left out, recorded so nobody re-adds them:

| Convention                                                                                            | Why not here                                                                                                                                                                                                                                        |
| ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **No comments or JSDoc — names must be self-documenting**                                             | This tree's docblocks carry story and AC references that the grading rubric depends on, and the cross-boundary notes (`src/api/auth.ts:3`, `src/layout/AppLayout.tsx:12`) are the only thing linking a permission string to its backend definition. |
| `[Category][Context].tsx` component naming (`FormUpdateUser`, `DialogDeleteConversation`)             | This tree is consistently `[Context]Page` (`VenueFormPage`, `LoginPage`, `HomePage`). Adopting the other scheme would rename every file for no gain.                                                                                                |
| Semantic colour tokens, no raw palette or opacity-composite classes, `cn()` over string interpolation | Tailwind-specific. There is no Tailwind, no `cn()` and no token config here — styling is plain global CSS with custom properties.                                                                                                                   |
| Dialog, Table, Button, Form, Skeleton and Notice patterns                                             | All built on Radix, shadcn, TanStack Table and react-hook-form. None is installed here, and [CLAUDE.md](CLAUDE.md) forbids adding them without team agreement.                                                                                      |
| Shared helpers belong in `src/lib/utils.ts`                                                           | No `lib/` folder here; the equivalent shared module is `src/api/client.ts`.                                                                                                                                                                         |

## Standing divergences

Rules the existing tree violates. Naming them here is what stops someone copying a violation in
good faith because they found it first. **Fix these under their own ticket, never opportunistically
in an unrelated PR.**

| Rule                                          | Violating sites                                                                                                                                          | Status                                                                                                                  |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| One exported constant for a cross-file string | 2: both copies of `'venues:manage'` (`src/App.tsx:25`, `src/layout/AppLayout.tsx:17`)                                                                    | fix when a page is next gated on this permission                                                                        |
| Extract named handlers                        | 22 across `LoginPage.tsx`, `VenueManagePage.tsx`, `VenueFormPage.tsx`                                                                                    | carried rule, newly adopted — most are the licensed form-setter shape; only the multi-statement ones are worth changing |
| Colour comes from a token, never a literal    | 0 — resolved in story c3 (`src/App.css` is token-only)                                                                                                   | resolved                                                                                                                |
| Boolean `is`/`can`/`has` prefix               | 4: `loading` (`AuthProvider.tsx:7`), `submitting` (`LoginPage.tsx:22`), `saving` (`VenueFormPage.tsx:151`), `includeWithdrawn` (`VenueManagePage.tsx:9`) | carried rule, newly adopted                                                                                             |
| Components use named exports                  | 1: `src/App.tsx:39`                                                                                                                                      | licensed exception — conventional default export for the Vite entry point                                               |

## Maintaining this file

- **Every rule describes something real.** If nobody has ever got it wrong, it is not a rule
  yet. A new rule needs a site in this repo it can point at — an exemplar that does it right or
  a counter-site that does not. Record a correction in the PR thread; add it here only when a
  second, independent case appears.
- **Record divergences with counts**, not "some legacy code does this".
- **Match the way it is already done here, even when the local choice is worse.** Settle a dispute
  by the majority of existing untouched code, name the canonical module to copy from, and raise
  standardization as its own PR rather than fixing it in passing.
