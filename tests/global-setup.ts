/**
 * Refuse to run against a stack whose database nobody has said is disposable.
 *
 * E2E specs write to whatever database the API behind FRONTEND_URL uses and never roll back, so
 * running them by hand against the development stack leaves junk in the dev database. The root
 * `npm run test:e2e` (scripts/e2e.mjs) builds a throwaway `connectsphere_e2e` database and its
 * own servers, then sets E2E_ISOLATED_DB=1 to say so. CI sets it too: its PostgreSQL service
 * container is discarded with the job.
 */
export default function globalSetup() {
  if (process.env.E2E_ISOLATED_DB === '1') return
  throw new Error(
    'E2E specs must not run against the development database.\n' +
      'Run `npm run test:e2e` from the repo root: it rebuilds a throwaway database and starts ' +
      'its own servers.\n' +
      'Only if the stack you are pointing at really uses a disposable database, set ' +
      'E2E_ISOLATED_DB=1.',
  )
}
