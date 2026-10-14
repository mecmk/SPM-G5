import { TURNAROUND_MAX_MINUTES, type Booking } from '../api/bookings'
import type { ErrorCode } from '../errors/registry'
import { formatSchedule } from '../shared/format'

// Every event runs on Singapore time, which has no daylight saving, so a day is always 24 hours
// (see shared/format.ts).
const MINUTES_PER_HOUR = 60
const MINUTES_PER_DAY = 24 * MINUTES_PER_HOUR
const MS_PER_MINUTE = 60_000
const WHOLE_NUMBER = /^\d+$/
// f12.1.2 (story 12.1 AC17): Singapore's offset from UTC, fixed for the same reason, so a moment's
// time of day there is worked out in whole minutes; and the "HH:MM" of a venue's "HH:MM:SS" hours.
const SINGAPORE_UTC_OFFSET_MINUTES = 8 * MINUTES_PER_HOUR
const CLOCK_TIME_LENGTH = 'HH:MM'.length

/** f12.1.2 (story 12.1 AC1): a setup or a teardown as the request step's fields hold it, in days,
 * hours and minutes. Each is the text as typed - the fields are text, not number, inputs, so a
 * browser never turns what it cannot read into a blank - and it is only read when needed, so a
 * half-typed value never breaks the step. */
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
 * nothing; anything else that is not a whole number of zero or more ("-1", "1.5", "3-", "e") is
 * null. */
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

/** f12.1.2 (story 12.1 AC1/AC17): what the booked period is called, on the request step's row and
 * in Venue Staff's notice. */
export const BOOKED_PERIOD_LABEL = 'Booked period'

/** f12.1.2 (story 12.1 AC17): what the request step adds to its notice. Q51: Venue Staff decide,
 * considering the setup and teardown. */
export const VENUE_STAFF_DECIDE = 'Venue Staff decide whether to allow it when they approve.'

/** f12.1.2 (story 12.1 AC17): which of a setup and a teardown run outside the venue's opening
 * hours. */
interface OutsideHours {
  isSetupOutside: boolean
  isTeardownOutside: boolean
}

/** Minutes past midnight on the Singapore wall clock at `stamp`, a moment with its zone. */
function singaporeMinuteOfDay(stamp: string): number {
  const minutesFromEpoch = Math.floor(Date.parse(stamp) / MS_PER_MINUTE)
  return (minutesFromEpoch + SINGAPORE_UTC_OFFSET_MINUTES) % MINUTES_PER_DAY
}

/** Minutes past midnight at `time`, a venue's opening or closing time as "HH:MM:SS". */
function minuteOfDay(time: string): number {
  const [hours, minutes] = time.split(':').map(Number)
  return hours * MINUTES_PER_HOUR + minutes
}

/**
 * f12.1.2 (story 12.1 AC17): the rule, written once for the request step, Venue Staff's queue card
 * and the request's page. A setup runs outside the venue's opening hours when it is longer than
 * the time from opening, `opensAt`, to the request's own start, `startsAt`, on the Singapore wall
 * clock; a teardown when it is longer than the time from the own end, `endsAt`, to closing,
 * `closesAt`. So one reaching exactly to opening or closing is inside, and a setup of a day or
 * more, which runs through the night, is always outside.
 */
function outsideOpeningHours(
  startsAt: string,
  endsAt: string,
  setupMinutes: number,
  teardownMinutes: number,
  opensAt: string,
  closesAt: string,
): OutsideHours {
  const sinceOpening = singaporeMinuteOfDay(startsAt) - minuteOfDay(opensAt)
  const untilClosing = minuteOfDay(closesAt) - singaporeMinuteOfDay(endsAt)
  return {
    isSetupOutside: setupMinutes > 0 && setupMinutes > sinceOpening,
    isTeardownOutside: teardownMinutes > 0 && teardownMinutes > untilClosing,
  }
}

/**
 * f12.1.2 (story 12.1 AC16): whether a request's own times, `startsAt` to `endsAt`, are within the
 * venue's opening hours as the server reads them (`closed_for` and `daily_window` in
 * backend/app/venues/service.py): as daily sessions from the start's time of day to the end's, on
 * the Singapore wall clock, each end included; never when the end's time of day is not after the
 * start's. A venue with no hours recorded is open whenever. The server refuses a request whose
 * own times are outside, so the request step says nothing about its setup and teardown then.
 */
export function isWithinOpeningHours(
  startsAt: string,
  endsAt: string,
  opensAt: string | null,
  closesAt: string | null,
): boolean {
  if (opensAt === null || closesAt === null) return true
  const start = singaporeMinuteOfDay(startsAt)
  const end = singaporeMinuteOfDay(endsAt)
  return end > start && start >= minuteOfDay(opensAt) && end <= minuteOfDay(closesAt)
}

/**
 * f12.1.2 (story 12.1 AC17): what of a setup and a teardown runs outside the venue's opening hours
 * (`outsideOpeningHours`), as every page says it - naming the hours, never the venue - or null
 * when neither does. A venue with no hours recorded, either time null or not given, has nothing to
 * run outside of.
 */
export function outsideHoursFact(
  startsAt: string,
  endsAt: string,
  setupMinutes: number,
  teardownMinutes: number,
  opensAt: string | null | undefined,
  closesAt: string | null | undefined,
): string | null {
  if (!opensAt || !closesAt) return null
  const { isSetupOutside, isTeardownOutside } = outsideOpeningHours(
    startsAt,
    endsAt,
    setupMinutes,
    teardownMinutes,
    opensAt,
    closesAt,
  )
  if (!isSetupOutside && !isTeardownOutside) return null
  const whatRuns =
    isSetupOutside && isTeardownOutside
      ? 'Setup and teardown run'
      : isSetupOutside
        ? 'Setup runs'
        : 'Teardown runs'
  const hours = `${opensAt.slice(0, CLOCK_TIME_LENGTH)}–${closesAt.slice(0, CLOCK_TIME_LENGTH)}`
  return `${whatRuns} outside the venue's opening hours, ${hours}.`
}

/** f12.1.2 (story 12.1 AC17): what Venue Staff's notice reads from a request - `Booking` and
 * `BookingQueueEntry` both carry it. */
type BookingTurnaround = Pick<
  Booking,
  'starts_at' | 'ends_at' | 'setup_minutes' | 'teardown_minutes' | 'held_from' | 'held_until'
>

/**
 * f12.1.2 (story 12.1 AC17): Venue Staff's notice, on the request's card in their queue and on its
 * page, so they decide on it when approving (13.2): what runs outside the venue's opening hours,
 * `opensAt` to `closesAt`, then the booked period. Null when nothing does (`outsideHoursFact`).
 * Q51: Venue Staff decide, considering the setup and teardown.
 */
export function venueStaffOutsideHoursNotice(
  booking: BookingTurnaround,
  opensAt: string | null | undefined,
  closesAt: string | null | undefined,
): string | null {
  const fact = outsideHoursFact(
    booking.starts_at,
    booking.ends_at,
    booking.setup_minutes,
    booking.teardown_minutes,
    opensAt,
    closesAt,
  )
  if (fact === null) return null
  return `${fact} ${BOOKED_PERIOD_LABEL}: ${formatSchedule(booking.held_from, booking.held_until)}.`
}
