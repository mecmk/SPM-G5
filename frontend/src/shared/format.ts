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
