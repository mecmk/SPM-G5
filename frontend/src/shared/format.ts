/**
 * Display formats, in one place so every page writes a server timestamp the same way. Every
 * event and booking in ConnectSphere runs on Singapore time (the seed data is all `+08`), so
 * these render in `Asia/Singapore` regardless of the viewer's own timezone, rather than letting
 * the browser silently reinterpret a UTC-stored instant into whatever zone it is sitting in.
 */
const LOCALE = 'en-SG'
const TIME_ZONE = 'Asia/Singapore'

export function formatDate(stamp: string): string {
  return new Date(stamp).toLocaleDateString(LOCALE, {
    weekday: 'short',
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

/** "Wed, 18 Nov 2026 · 09:00–17:00" */
export function formatSchedule(startsAt: string, endsAt: string): string {
  return `${formatDate(startsAt)} · ${formatTime(startsAt)}–${formatTime(endsAt)}`
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
