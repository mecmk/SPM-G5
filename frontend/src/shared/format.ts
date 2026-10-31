/**
 * Display formats, in one place so every page writes a server timestamp the same way. Every
 * event and booking in ConnectSphere runs on Singapore time (the seed data is all `+08`), so
 * these render in `Asia/Singapore` regardless of the viewer's own timezone, rather than letting
 * the browser silently reinterpret a UTC-stored instant into whatever zone it is sitting in.
 */
const LOCALE = 'en-SG'
const TIME_ZONE = 'Asia/Singapore'

/** What a page shows in place of a value that was never recorded, such as a request's sender or
 * a reason for declining given before reasons were required. */
export const NOT_RECORDED = 'Not recorded'

/** What a page shows for something given as nothing at all, such as an attendee's dietary
 *  requirements left blank (story 18.4 AC6). */
export const NONE = 'None'

/** Story 6.2 AC16: how every page names when a booking or equipment request was cancelled - with
 * its event, or by an approved change (19.2). */
export const CANCELLED_AT_LABEL = 'Cancelled at'

/** Story 17.2 AC4: the label of when a withdrawn equipment request was withdrawn, on Technical
 *  Support's queue card and on the request's own page. */
export const WITHDRAWN_AT_LABEL = 'Withdrawn at'

/** What a page shows for a venue requirement or booking that asks for no particular layout. */
export const ANY_LAYOUT = 'Any'

/** What a page shows for a booking that is for no venue requirement: an additional venue (12.5). */
export const ADDITIONAL_VENUE = 'Additional venue'

/** What a page shows for an event that has no coordinator yet (stories 5.4 AC6, 5.5 AC1). */
export const NOT_YET_ASSIGNED = 'Not yet assigned'

/** How much of a request's id names it on screen. */
const SHORT_ID_LENGTH = 8

/** A request's short reference, "#14629C18": the end of its id, as every request card shows it
 *  (bookings, equipment, change requests) and the change history names it (story 7.4 AC4). */
export function shortReference(id: string): string {
  return `#${id.slice(-SHORT_ID_LENGTH).toUpperCase()}`
}

/** Story 13.3 AC6: the link a search nothing matches offers, to list the whole tab again. */
export const CLEAR_SEARCH = 'Clear search'

export function formatDate(stamp: string): string {
  return new Date(stamp).toLocaleDateString(LOCALE, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: TIME_ZONE,
  })
}

/** "10 Apr 2029": a day on its own, without its weekday. */
export function formatCalendarDate(stamp: string): string {
  return new Date(stamp).toLocaleDateString(LOCALE, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: TIME_ZONE,
  })
}

export function formatTime(stamp: string): string {
  return new Date(stamp).toLocaleTimeString(LOCALE, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: TIME_ZONE,
  })
}

/**
 * "Wed, 18 Nov 2026 · 09:00–17:00" for a period inside one day. f7.1.1 (story 7.1 AC1): a period
 * over more than one day names both dates, "Tue, 15 Dec 2026, 09:00 – Wed, 16 Dec 2026, 17:00", so
 * it never reads as its first day alone. The days compared are Singapore days, like every date here.
 */
export function formatSchedule(startsAt: string, endsAt: string): string {
  return formatDate(startsAt) === formatDate(endsAt)
    ? `${formatDate(startsAt)} · ${formatTime(startsAt)}–${formatTime(endsAt)}`
    : `${formatDateTime(startsAt)} – ${formatDateTime(endsAt)}`
}

export function formatDateTime(stamp: string): string {
  return `${formatDate(stamp)}, ${formatTime(stamp)}`
}

const SINGAPORE_UTC_OFFSET = '+08:00'
const DATE_TIME_INPUT_LENGTH = 'YYYY-MM-DDTHH:mm'.length

/**
 * A `datetime-local` input's value ("2026-11-18T09:00") is a wall-clock time with no zone. Every
 * event runs on Singapore time, which has no daylight saving, so the offset is fixed.
 */
export function inputToInstant(inputValue: string): string {
  return `${inputValue}:00${SINGAPORE_UTC_OFFSET}`
}

/** The current moment as a Singapore `datetime-local` value, e.g. for a picker's `min`. */
export function nowAsInput(): string {
  return instantToInput(new Date().toISOString())
}

/** The reverse of `inputToInstant`: a server timestamp as a Singapore `datetime-local` value. */
export function instantToInput(stamp: string): string {
  // The Swedish locale writes "2026-11-18 09:00:00", which is the input's format bar the space.
  return new Date(stamp)
    .toLocaleString('sv-SE', { timeZone: TIME_ZONE, hour12: false })
    .replace(' ', 'T')
    .slice(0, DATE_TIME_INPUT_LENGTH)
}

const SECONDS_PER_MINUTE = 60
const MINUTES_PER_HOUR = 60

/**
 * Story 1.1 AC6: a duration in whole seconds as whole minutes, rounded up, so the last minute
 * reads "1 min" rather than "0 min": "15 min", "1 h 5 min", "2 h". A length of time, not a
 * moment, so no time zone applies.
 */
export function formatTimeLeft(totalSeconds: number): string {
  const totalMinutes = Math.ceil(totalSeconds / SECONDS_PER_MINUTE)
  const hours = Math.floor(totalMinutes / MINUTES_PER_HOUR)
  const minutes = totalMinutes % MINUTES_PER_HOUR
  const parts: string[] = []
  if (hours > 0) parts.push(`${hours} h`)
  if (minutes > 0 || hours === 0) parts.push(`${minutes} min`)
  return parts.join(' ')
}
