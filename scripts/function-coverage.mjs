#!/usr/bin/env node
/**
 * Function coverage for named backend modules, read from coverage.py's JSON report.
 *
 * coverage.py measures lines and branches but reports no function figure of its own. Its JSON
 * report does list every function and method of each file with the lines that ran, so a function
 * counts as covered here when at least one of its statements ran.
 *
 *   npm run test:coverage -- --cov=app.events.schemas      # writes backend/coverage.json
 *   npm run test:function-coverage -- app/events/schemas.py
 *
 * Prints each module's covered functions out of its total, and its percentage. Exits 1, naming
 * every function that never ran, when any module is below 100%, or when a named module is not in
 * the report at all.
 */
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { ROOT, log } from './lib/tools.mjs'

const REPORT = path.join(ROOT, 'backend', 'coverage.json')
const MODULE_LEVEL = '' // coverage.py's entry for code outside any function

function normalise(file) {
  return file.replaceAll('\\', '/').replace(/^\.\//, '')
}

function main() {
  const modules = process.argv.slice(2).map(normalise)
  if (modules.length === 0) {
    log.error('Name the modules to check, e.g. app/events/schemas.py')
    return 2
  }
  if (!existsSync(REPORT)) {
    log.error(`No ${path.relative(ROOT, REPORT)}: run npm run test:coverage first.`)
    return 2
  }
  const files = JSON.parse(readFileSync(REPORT, 'utf8')).files
  const byPath = new Map(Object.entries(files).map(([file, data]) => [normalise(file), data]))

  let isComplete = true
  let covered = 0
  let total = 0
  for (const module of modules) {
    const data = byPath.get(module)
    if (data === undefined || data.functions === undefined) {
      log.error(`${module}: not in the report (was it measured with --cov?)`)
      isComplete = false
      continue
    }
    const functions = Object.entries(data.functions).filter(([name]) => name !== MODULE_LEVEL)
    const unrun = functions.filter(([, fn]) => fn.summary.covered_lines === 0).map(([n]) => n)
    const ran = functions.length - unrun.length
    covered += ran
    total += functions.length
    const percent = functions.length === 0 ? 100 : (100 * ran) / functions.length
    const line = `${module}: ${ran}/${functions.length} functions (${percent.toFixed(1)}%)`
    if (unrun.length === 0) {
      log.ok(line)
    } else {
      isComplete = false
      log.error(`${line} - never ran: ${unrun.join(', ')}`)
    }
  }
  const overall = total === 0 ? 100 : (100 * covered) / total
  log.info(`Total: ${covered}/${total} functions (${overall.toFixed(1)}%)`)
  return isComplete ? 0 : 1
}

process.exit(main())
