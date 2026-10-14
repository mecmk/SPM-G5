import { TURNAROUND_MAX_MINUTES } from '../api/bookings'
import type { ErrorCode } from '../errors/registry'

// Every event runs on Singapore time, which has no daylight saving, so a day is always 24 hours
// (see shared/format.ts).
const MINUTES_PER_HOUR = 60
const MINUTES_PER_DAY = 24 * MINUTES_PER_HOUR
const MS_PER_MINUTE = 60_000
const WHOLE_NUMBER = /^\d+$/

/** f12.1.2 (story 12.1 AC1): a setup or a teardown as the request step's fields hold it, in days,
 * hours and minutes. Each stays as typed until it is read, so a half-typed value never breaks the
 * step. */
export interface DurationDraft {
  days: string
  hours: string
  minutes: string
}

/** f12.1.2 (story 12.1 AC1): setup and teardown are 0 until the coordinator enters more. */
export const ZERO_DURATION: DurationDraft = { days: '0', hours: '0', minutes: '0' }

/** f12.1.2 (story 12.1 AC1): the booked period - from the setup before a request's own start to
 * the teardown after its own end, as moments with their zone. */
export interface BookedPeriod {
  heldFrom: string
  heldUntil: string
}

/** One part of a draft as a whole number. A blank part counts as 0, as a cleared field adds
 * nothing; anything else that is not a whole number of zero or more ("-1", "1.5", "e") is null. */
function wholeNumberOf(part: string): number | null {
  const trimmed = part.trim()
  if (trimmed === '') return 0
  return WHOLE_NUMBER.test(trimmed) ? Number(trimmed) : null
}

/** f12.1.2 (story 12.1 AC1/AC5): a setup or teardown draft in whole minutes, or null when any of
 * its parts is not a whole number of zero or more. */
export function durationMinutes(draft: DurationDraft): number | null {
  const days = wholeNumberOf(draft.days)
  const hours = wholeNumberOf(draft.hours)
  const minutes = wholeNumberOf(draft.minutes)
  if (days === null || hours === null || minutes === null) return null
  return days * MINUTES_PER_DAY + hours * MINUTES_PER_HOUR + minutes
}

/** f12.1.2 (story 12.1 AC5): what the server would refuse in a setup and a teardown, as a registry
 * code, so the step refuses it before sending: a part that is not a whole number of zero or more,
 * or either one over `TURNAROUND_MAX_MINUTES`. Null when both may be sent. */
export function turnaroundProblem(setup: DurationDraft, teardown: DurationDraft): ErrorCode | null {
  const setupMinutes = durationMinutes(setup)
  const teardownMinutes = durationMinutes(teardown)
  if (setupMinutes === null || teardownMinutes === null) return 'BOOKING_TURNAROUND_INVALID'
  if (Math.max(setupMinutes, teardownMinutes) > TURNAROUND_MAX_MINUTES) {
    return 'BOOKING_TURNAROUND_TOO_LONG'
  }
  return null
}

/** f12.1.2 (story 12.1 AC1): the booked period a setup and a teardown make around a request's own
 * times, `startsAt` to `endsAt`, as the server holds it. AC5: a setup may reach into earlier days,
 * and a teardown into later ones. */
export function bookedPeriod(
  startsAt: string,
  endsAt: string,
  setupMinutes: number,
  teardownMinutes: number,
): BookedPeriod {
  return {
    heldFrom: new Date(Date.parse(startsAt) - setupMinutes * MS_PER_MINUTE).toISOString(),
    heldUntil: new Date(Date.parse(endsAt) + teardownMinutes * MS_PER_MINUTE).toISOString(),
  }
}
