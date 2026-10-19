#!/usr/bin/env node
/**
 * Backend coverage, for the modules a change adds or changes (docs/testing/README.md).
 *
 *   npm run test:coverage -- --cov=app.events.schemas --cov-fail-under=100
 *
 * Runs the whole pytest suite under pytest-cov, prints each measured module's missed lines and
 * branches ([tool.coverage] in backend/pyproject.toml) and writes backend/coverage.json for
 * npm run test:function-coverage. Without a --cov it measures the whole app package, so a run never
 * measures nothing. Every argument goes on to pytest.
 */
import path from 'node:path'
import { ROOT, run } from './lib/tools.mjs'

const WHOLE_APP = '--cov=app'

function isCoverageTarget(arg) {
  return arg === '--cov' || arg.startsWith('--cov=')
}

const args = process.argv.slice(2)
const target = args.some(isCoverageTarget) ? [] : [WHOLE_APP]
const status = run(process.execPath, [
  path.join(ROOT, 'scripts', 'uv.mjs'),
  '--directory',
  'backend',
  'run',
  'pytest',
  '--cov-report=term',
  '--cov-report=json',
  ...target,
  ...args,
])
process.exit(status ?? 1)
