#!/usr/bin/env node
/**
 * Run uv even when it is not on PATH, installing it first if it is missing.
 *
 * The root package.json scripts call uv through this wrapper, for example:
 *   node scripts/uv.mjs --directory backend run pytest
 */
import { spawn } from 'node:child_process'
import { requireUv } from './lib/tools.mjs'

const child = spawn(requireUv(), process.argv.slice(2), { stdio: 'inherit' })

// Ctrl+C already reaches uv through the terminal, so let it shut down on its own.
// SIGTERM (for example from `concurrently`) is passed on explicitly.
process.on('SIGINT', () => {})
process.on('SIGTERM', () => child.kill('SIGTERM'))

child.on('error', (error) => {
  console.error(`uv: ${error.message}`)
  process.exit(1)
})
child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)))
