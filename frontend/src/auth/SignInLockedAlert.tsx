import { useEffect, useState } from 'react'
import { LOGIN_LOCKED_COUNTDOWN } from '../errors/registry'
import { formatTimeLeft } from '../shared/format'

/** Re-read the time left well inside each second, so a late timer never skips a second. */
const TICK_MS = 250
const MS_PER_SECOND = 1000

/** A locked sign-in: the seconds left the server gave, and when the browser received them. */
export interface SignInLock {
  retryAfterSeconds: number
  /** `Date.now()` on receipt. */
  receivedAtMs: number
  /** `performance.now()` on receipt. */
  receivedAtMonotonicMs: number
}

/**
 * Whole seconds left, rounded up. The countdown never reads a clock time, only time elapsed, so
 * time zones, daylight saving and leap years cannot affect it. Elapsed time is taken from two
 * clocks because each fails differently: `Date.now()` keeps counting while the computer sleeps
 * but jumps if someone changes the clock, and `performance.now()` ignores clock changes but may
 * stand still during sleep. The larger of the two is right in both cases. A clock moved forward
 * ends the countdown early, but the server still holds the lock and sends the true time again on
 * the next attempt.
 */
function secondsLeftOf(lock: SignInLock): number {
  const elapsedMs = Math.max(
    Date.now() - lock.receivedAtMs,
    performance.now() - lock.receivedAtMonotonicMs,
    0,
  )
  return Math.max(0, Math.ceil(lock.retryAfterSeconds - elapsedMs / MS_PER_SECOND))
}

/**
 * Story 1.1 AC6: while sign-in is locked, count down the minutes left, then say it is open again.
 * The seconds are still tracked, so the minute changes on time and the end is exact.
 * The ticking time is a `timer`, which screen readers do not announce on every change; the
 * surrounding alert is announced when the lock arrives and again when it ends.
 */
export function SignInLockedAlert({ lock }: { lock: SignInLock }) {
  const [secondsLeft, setSecondsLeft] = useState(lock.retryAfterSeconds)

  useEffect(() => {
    function tick() {
      const left = secondsLeftOf(lock)
      setSecondsLeft(left)
      if (left === 0) clearInterval(timer)
    }
    const timer = setInterval(tick, TICK_MS)
    return () => clearInterval(timer)
  }, [lock])

  if (secondsLeft === 0) {
    return (
      <p role="alert" className="info login-error">
        {LOGIN_LOCKED_COUNTDOWN.ended}
      </p>
    )
  }
  return (
    <p role="alert" className="error login-error">
      {LOGIN_LOCKED_COUNTDOWN.lead} <span role="timer">{formatTimeLeft(secondsLeft)}</span>.
    </p>
  )
}
