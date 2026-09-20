#!/usr/bin/env node
/**
 * Run the Playwright e2e suite against a throwaway database, never the development one.
 *
 *   npm run test:e2e                          # every spec
 *   npm run test:e2e -- e2e/venues.spec.ts    # extra arguments go to `playwright test`
 *
 * What it does, and undoes:
 *   1. Rebuilds `connectsphere_e2e` (migrations + seed) on the same PostgreSQL server as the
 *      dev database. The dev database is never opened.
 *   2. Starts its own API (:8001) and Vite server (:5174) pointed at that database, so a dev
 *      stack on :8000 / :5173 can keep running.
 *   3. Runs Playwright against them, then stops both servers and empties the database.
 *
 * Refuses to run when the database name does not end in `_e2e` (this script empties it), or
 * when either port is already taken (tests would silently hit whatever is listening).
 * Override with E2E_DATABASE_URL, E2E_BACKEND_PORT, E2E_FRONTEND_PORT.
 *
 * Both servers use 127.0.0.1 so the SameSite=Lax session cookie stays same-site, as in CI.
 */
import { spawn, spawnSync } from 'node:child_process'
import net from 'node:net'
import { IS_WINDOWS, ROOT, log, requireUv, run } from './lib/tools.mjs'

const DEFAULT_DATABASE_URL =
  'postgresql+psycopg://connectsphere:connectsphere@localhost:5433/connectsphere_e2e'
const REQUIRED_DATABASE_SUFFIX = '_e2e'
const HOST = '127.0.0.1'
const READY_TIMEOUT_MS = 120_000
const READY_POLL_MS = 500
const LOG_LINES_KEPT = 40

const databaseUrl = process.env.E2E_DATABASE_URL ?? DEFAULT_DATABASE_URL
const backendPort = Number(process.env.E2E_BACKEND_PORT ?? 8001)
const frontendPort = Number(process.env.E2E_FRONTEND_PORT ?? 5174)
const backendUrl = `http://${HOST}:${backendPort}`
const frontendUrl = `http://${HOST}:${frontendPort}`

const servers = []

function databaseName(url) {
  return new URL(url.replace('postgresql+psycopg://', 'postgresql://')).pathname.slice(1)
}

function isPortInUse(port) {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host: HOST })
    socket.once('connect', () => {
      socket.destroy()
      resolve(true)
    })
    socket.once('error', () => resolve(false))
  })
}

/** Start a long-running server, keeping its last output lines so a failed start can show them. */
function startServer(name, command, args, env) {
  const child = spawn(command, args, {
    cwd: ROOT,
    env: { ...process.env, ...env },
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: IS_WINDOWS && command === 'npm',
    detached: !IS_WINDOWS,
  })
  const recent = []
  const keep = (chunk) => {
    recent.push(...chunk.toString().split(/\r?\n/).filter(Boolean))
    recent.splice(0, Math.max(0, recent.length - LOG_LINES_KEPT))
  }
  child.stdout.on('data', keep)
  child.stderr.on('data', keep)
  const server = { name, child, recent }
  servers.push(server)
  return server
}

function stopServer({ child }) {
  if (child.exitCode !== null || child.pid === undefined) return
  if (IS_WINDOWS)
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  else process.kill(-child.pid, 'SIGTERM')
}

async function waitUntilReady(url, server) {
  const deadline = Date.now() + READY_TIMEOUT_MS
  while (Date.now() < deadline) {
    if (server.child.exitCode !== null) break
    try {
      if ((await fetch(url)).ok) return
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, READY_POLL_MS))
  }
  log.error(`${server.name} did not become ready at ${url}. Last output:`)
  server.recent.forEach((line) => log.info(line))
  throw new Error(`${server.name} did not start`)
}

function dbtool(...args) {
  return run(requireUv(), [
    '--directory',
    'backend',
    'run',
    'python',
    '-m',
    'app.dbtool',
    '--url',
    databaseUrl,
    ...args,
  ])
}

async function main() {
  const name = databaseName(databaseUrl)
  if (!name.endsWith(REQUIRED_DATABASE_SUFFIX)) {
    log.error(
      `Refusing to use database "${name}": e2e empties its database, so the name must end in ` +
        `"${REQUIRED_DATABASE_SUFFIX}". The development database is never used for e2e.`,
    )
    return 1
  }
  for (const port of [backendPort, frontendPort]) {
    if (await isPortInUse(port)) {
      log.error(`Port ${port} is already in use. Stop whatever is on it, or set E2E_*_PORT.`)
      return 1
    }
  }

  log.info(`Rebuilding throwaway database "${name}" ...`)
  if (dbtool('reset', '--no-docs') !== 0) return 1

  const backend = startServer(
    'backend',
    requireUv(),
    [
      '--directory',
      'backend',
      'run',
      'uvicorn',
      'app.main:app',
      '--host',
      HOST,
      '--port',
      String(backendPort),
    ],
    { DATABASE_URL: databaseUrl, CORS_ORIGINS: JSON.stringify([frontendUrl]) },
  )
  const frontend = startServer(
    'frontend',
    'npm',
    [
      '--prefix',
      'frontend',
      'run',
      'dev',
      '--',
      '--host',
      HOST,
      '--port',
      String(frontendPort),
      '--strictPort',
    ],
    { VITE_API_BASE_URL: backendUrl },
  )
  await waitUntilReady(`${backendUrl}/health`, backend)
  await waitUntilReady(frontendUrl, frontend)
  log.ok(`API ${backendUrl} and app ${frontendUrl} are up, on "${name}"`)

  return (
    run('npm', ['--prefix', 'tests', 'test', '--', ...process.argv.slice(2)], {
      shell: IS_WINDOWS,
      env: { ...process.env, FRONTEND_URL: frontendUrl, E2E_ISOLATED_DB: '1' },
    }) ?? 1
  )
}

function cleanUp() {
  servers.forEach(stopServer)
  servers.length = 0
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    cleanUp()
    process.exit(130)
  })
}

let exitCode = 1
try {
  exitCode = await main()
} catch (error) {
  log.error(error.message)
} finally {
  cleanUp()
  const name = databaseName(databaseUrl)
  if (name.endsWith(REQUIRED_DATABASE_SUFFIX)) dbtool('drop')
}
process.exit(exitCode)
