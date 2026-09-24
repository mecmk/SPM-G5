/**
 * Helpers for `scripts/uv.mjs`, the wrapper every root npm script uses to run uv.
 *
 * Node built-ins only, so they work on a fresh clone before `npm install` has ever run.
 */
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
export const IS_WINDOWS = process.platform === 'win32'

const useColour = Boolean(process.stdout.isTTY) && !process.env.NO_COLOR
const paint = (code) => (text) => (useColour ? `\u001b[${code}m${text}\u001b[0m` : text)
export const colour = {
  red: paint('31'),
  green: paint('32'),
  yellow: paint('33'),
}

export const log = {
  ok: (text) => console.log(`  ${colour.green('ok')}  ${text}`),
  info: (text) => console.log(`      ${text}`),
  warn: (text) => console.log(`  ${colour.yellow('!!')}  ${text}`),
  error: (text) => console.error(`  ${colour.red('xx')}  ${text}`),
}

/** Run a command with its output shown. Returns the exit code, or null if it could not start. */
export function run(command, args = [], options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', cwd: ROOT, ...options })
  if (result.error) {
    log.error(`${command}: ${result.error.message}`)
    return null
  }
  return result.status
}

/** Run a command quietly. Returns { ok, stdout }. */
export function capture(command, args = [], options = {}) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 20_000,
    ...options,
  })
  return { ok: !result.error && result.status === 0, stdout: (result.stdout ?? '').trim() }
}

export function commandExists(command, versionArgs = ['--version']) {
  return capture(command, versionArgs).ok
}

const UV_EXE = IS_WINDOWS ? 'uv.exe' : 'uv'

/**
 * Locate uv even when it is not on PATH: just installed (PATH only refreshes in new terminals),
 * installed with pip, or installed by winget or Homebrew. Returns the command to run, or null.
 */
export function findUv() {
  if (commandExists('uv')) return 'uv'
  const home = homedir()
  const candidates = [
    path.join(home, '.local', 'bin', UV_EXE), // official installer, every OS
    path.join(home, '.cargo', 'bin', UV_EXE), // older official installer
  ]
  if (IS_WINDOWS && process.env.LOCALAPPDATA) {
    candidates.push(path.join(process.env.LOCALAPPDATA, 'Microsoft', 'WinGet', 'Links', UV_EXE))
  }
  if (!IS_WINDOWS) candidates.push('/opt/homebrew/bin/uv', '/usr/local/bin/uv')
  const found = candidates.find((candidate) => existsSync(candidate))
  if (found) return found
  // `pip install uv` puts the binary in Python's scripts folder, which is often not on PATH.
  for (const python of IS_WINDOWS ? ['python', 'py'] : ['python3', 'python']) {
    const probe = capture(python, ['-c', 'import uv; print(uv.find_uv_bin())'])
    if (probe.ok && existsSync(probe.stdout)) return probe.stdout
  }
  return null
}

/** Install uv with the official installer (the method in README.md). Returns findUv(). */
export function installUv() {
  log.info('Installing uv with the official installer (https://docs.astral.sh/uv/) ...')
  const status = IS_WINDOWS
    ? run('powershell', [
        '-NoProfile',
        '-ExecutionPolicy',
        'ByPass',
        '-Command',
        'irm https://astral.sh/uv/install.ps1 | iex',
      ])
    : run('sh', ['-c', 'curl -LsSf https://astral.sh/uv/install.sh | sh'])
  return status === 0 ? findUv() : null
}

/** findUv(), installing uv first when it is missing. Exits the process if that fails. */
export function requireUv() {
  const existing = findUv()
  if (existing) return existing
  log.warn('uv, the Python package manager this project uses, is not installed.')
  const installed = installUv()
  if (installed) {
    log.ok(`uv installed at ${installed}`)
    return installed
  }
  log.error('Could not install uv automatically. Install it yourself, then try again:')
  log.info(
    IS_WINDOWS
      ? 'winget install --id astral-sh.uv -e'
      : 'curl -LsSf https://astral.sh/uv/install.sh | sh',
  )
  process.exit(1)
}
