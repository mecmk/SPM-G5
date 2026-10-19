#!/usr/bin/env node
/**
 * Mutation testing of the backend with mutmut.
 *
 * mutmut forks a process per mutant, which Windows cannot do, so it runs in a python:3.12-slim
 * Docker container on every OS. The backend is mounted read-only and copied inside the container;
 * nothing in the working tree changes. Its tests run on their own throwaway databases on the
 * compose PostgreSQL (connectsphere_mut, rebuilt by conftest.py as connectsphere_mut_test), never
 * the development or test ones. Needs PostgreSQL up (npm run db:up) and Docker.
 *
 *   npm run test:mutation -- [--tests <path>...] [--debug] [<mutant name glob>...]
 *
 *   npm run test:mutation -- --tests tests/equipment tests/events "app.events.schemas.*"
 *
 * --tests   the tests that may kill a mutant (default: every test); mutmut then runs, for each
 *           mutant, only those of them that reached its function
 * --debug   show pytest's own output, to see why mutmut could not run the tests
 * globs     which mutants to run (default: every one), e.g. "app.events.schemas.*"
 *
 * Writes backend/mutation-report/ (git-ignored): run.txt, results.txt (every mutant and its
 * status) and survivors.txt (the diff of each one not killed).
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { ROOT, log, run } from './lib/tools.mjs'

const IMAGE = 'python:3.12-slim'
const REPORT_DIR = path.join(ROOT, 'backend', 'mutation-report')
const DATABASE = 'postgresql+psycopg://connectsphere:connectsphere@host.docker.internal:5433'

function parseArgs(args) {
  const tests = []
  const globs = []
  let isDebug = false
  let target = globs
  for (const arg of args) {
    if (arg === '--tests') target = tests
    else if (arg === '--debug') isDebug = true
    else if (arg.startsWith('--')) throw new Error(`Unknown option ${arg}`)
    else if (target === tests && !arg.startsWith('tests')) globs.push(arg)
    else target.push(arg)
  }
  return { tests, globs, isDebug }
}

/** The shell script run inside the container. Values come in as environment variables. */
const CONTAINER_SCRIPT = String.raw`
set -eu
export UV_LINK_MODE=copy UV_PYTHON=3.12 UV_PYTHON_DOWNLOADS=never
pip install -q uv >/dev/null 2>&1
rm -rf /work && cp -r /src /work && cd /work
rm -rf .venv mutants .pytest_cache mutation-report
# This run's choices go into the working copy's [tool.mutmut] only.
if [ -n "$MUTATION_TESTS" ]; then
  sed -i "/^\[tool.mutmut\]/a pytest_add_cli_args_test_selection = [$MUTATION_TESTS]" pyproject.toml
fi
if [ "$MUTATION_DEBUG" = "true" ]; then
  sed -i "/^\[tool.mutmut\]/a debug = true" pyproject.toml
fi
uv sync -q --group dev
set -f
# shellcheck disable=SC2086
uv run --no-sync mutmut run --max-children 1 $MUTATION_GLOBS > /out/run.txt 2>&1 || true
set +f
uv run --no-sync mutmut results --all true > /out/results.txt 2>&1 || true
for name in $(grep -E ": (survived|no tests|timeout|suspicious|segfault)" /out/results.txt | sed 's/^ *//' | cut -d: -f1); do
  echo "=== $name"
  uv run --no-sync mutmut show "$name"
done > /out/survivors.txt 2>&1 || true
`

function main() {
  let options
  try {
    options = parseArgs(process.argv.slice(2))
  } catch (error) {
    log.error(error.message)
    return 2
  }
  mkdirSync(REPORT_DIR, { recursive: true })
  writeFileSync(path.join(REPORT_DIR, 'run.txt'), '')
  const quoted = options.tests.map((test) => `"${test}"`).join(', ')
  log.info(`Mutating ${options.globs.length ? options.globs.join(' ') : 'every function'}`)
  log.info(`Killing with ${options.tests.length ? options.tests.join(' ') : 'every test'}`)
  const status = run('docker', [
    'run',
    '--rm',
    // Docker Desktop resolves host.docker.internal itself; Linux needs it mapped to the host.
    '--add-host=host.docker.internal:host-gateway',
    '-v', `${path.join(ROOT, 'backend')}:/src:ro`,
    '-v', `${REPORT_DIR}:/out`,
    '-e', `DATABASE_URL=${DATABASE}/connectsphere_mut`,
    '-e', `TEST_DATABASE_URL=${DATABASE}/connectsphere_mut_test`,
    '-e', `MUTATION_TESTS=${quoted}`,
    '-e', `MUTATION_GLOBS=${options.globs.join(' ')}`,
    '-e', `MUTATION_DEBUG=${options.isDebug}`,
    IMAGE,
    'sh',
    '-c',
    CONTAINER_SCRIPT,
  ])
  if (status !== 0) {
    log.error('The mutation run did not finish; see backend/mutation-report/run.txt')
    return 1
  }
  log.ok(`Done: ${path.relative(ROOT, REPORT_DIR)}/results.txt and survivors.txt`)
  return 0
}

process.exit(main())
