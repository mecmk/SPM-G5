import { BOOKING_REASON, HELD_REASON, type VenueUnavailableWindow } from '../api/venues'
import type { CalendarEntry, CalendarEntryTone } from '../components/Calendar'
import { eachDate } from '../components/calendarGrid'
import { inputToInstant } from '../shared/format'

/** Story 9.1 AC2: what a confirmed booking, and a pending request that holds the venue, are
 *  called - in words as well as colour. */
export const BOOKED_LABEL = 'Booked'
export const HELD_LABEL = 'Held – pending'

const CLOSED_PREFIX = 'Closed'
const HELD_ENTRY_PREFIX = 'Held'
const TURNAROUND_INCLUDED = 'Setup and teardown included'
// On a day the event itself does not reach, only its setup or teardown, the row says so instead of
// calling it booked; a pending request keeps its "Held – pending".
const TURNAROUND_ONLY_LABEL = 'Setup and teardown only'
const HELD_TURNAROUND_ONLY_LABEL = `${HELD_LABEL}, setup and teardown only`

/** Mirrors `UnavailabilityReason` in backend/app/venues/models.py: a closure's `reason`. */
const CLOSURE_REASON_NAMES: Record<string, string> = {
  MAINTENANCE: 'Maintenance',
  RENOVATION: 'Renovation',
  SAFETY: 'Safety',
  INTERNAL_USE: 'Internal use',
  OTHER: 'Other',
}

// Every event runs on Singapore time, which has no daylight saving, so a day is always 24 hours
// (see shared/format.ts).
const MINUTES_PER_HOUR = 60
const MS_PER_MINUTE = 60_000
const MINUTES_PER_DAY = 24 * MINUTES_PER_HOUR
const MS_PER_DAY = MINUTES_PER_DAY * MS_PER_MINUTE

/** A stretch of one day, in milliseconds since the epoch. */
interface DaySlice {
  start: number
  end: number
}

/**
 * Story 9.1 AC5/AC9: one window's part of one Singapore day, ready to list. A booking that runs
 * over several days has one of these on each, holding only the part that falls on that day.
 */
export interface DayItem {
  id: string
  /** `YYYY-MM-DD`, Singapore time. */
  date: string
  /** The event's name, or a closure's notes. */
  label: string
  /** "Booked", "Held – pending" or "Closed – Maintenance"; on a day only a booking's setup or
   *  teardown reaches, "Setup and teardown only" or "Held – pending, setup and teardown only". */
  kindLabel: string
  tone: CalendarEntryTone
  /** The event's part of the day, "09:00–18:00"; a closure's, or a day the event does not reach
   *  (only its setup or teardown does), the blocked part. "24:00" is the end of the day. */
  timeRange: string
  /** A second line when the venue is blocked for longer than the event on a day the event is on:
   *  "Setup and teardown included: 08:00–19:00". Null when the two are the same, for a closure,
   *  and on a day the event does not reach, where `kindLabel` already says so. */
  turnaround: string | null
  /** Where the item sorts within its day. */
  sortStart: number
  /** The item as a calendar cell shows it. */
  entryLabel: string
}

function startOfDay(date: string): number {
  return Date.parse(inputToInstant(`${date}T00:00`))
}

function sliceOfDay(startsAt: string, endsAt: string, dayStart: number): DaySlice | null {
  const start = Math.max(Date.parse(startsAt), dayStart)
  const end = Math.min(Date.parse(endsAt), dayStart + MS_PER_DAY)
  return start < end ? { start, end } : null
}

function twoDigits(value: number): string {
  return String(value).padStart(2, '0')
}

/** "09:00", and "24:00" for the end of the day, which a clock would write as 00:00 of the next. */
function clockTime(moment: number, dayStart: number): string {
  const minutes = Math.round((moment - dayStart) / MS_PER_MINUTE)
  return `${twoDigits(Math.floor(minutes / MINUTES_PER_HOUR))}:${twoDigits(minutes % MINUTES_PER_HOUR)}`
}

function formatSlice(slice: DaySlice, dayStart: number): string {
  return `${clockTime(slice.start, dayStart)}–${clockTime(slice.end, dayStart)}`
}

function isSameSlice(first: DaySlice, second: DaySlice): boolean {
  return first.start === second.start && first.end === second.end
}

function closureKindLabel(reason: string): string {
  return `${CLOSED_PREFIX} – ${CLOSURE_REASON_NAMES[reason] ?? reason}`
}

function bookingKindLabel(isHeld: boolean, isTurnaroundOnly: boolean): string {
  if (isTurnaroundOnly) return isHeld ? HELD_TURNAROUND_ONLY_LABEL : TURNAROUND_ONLY_LABEL
  return isHeld ? HELD_LABEL : BOOKED_LABEL
}

function itemsForWindow(window: VenueUnavailableWindow, index: number): DayItem[] {
  return eachDate(window.starts_at, window.ends_at).flatMap((date) => {
    const dayStart = startOfDay(date)
    const blocked = sliceOfDay(window.starts_at, window.ends_at, dayStart)
    if (blocked === null) return []
    const event =
      window.event_starts_at !== null && window.event_ends_at !== null
        ? sliceOfDay(window.event_starts_at, window.event_ends_at, dayStart)
        : null

    const isBooking = window.reason === BOOKING_REASON || window.reason === HELD_REASON
    const isHeld = window.reason === HELD_REASON
    const isTurnaroundOnly = isBooking && event === null
    let turnaround: string | null = null
    if (isBooking && event !== null && !isSameSlice(event, blocked)) {
      turnaround = `${TURNAROUND_INCLUDED}: ${formatSlice(blocked, dayStart)}`
    }

    return [
      {
        id: `${index}-${date}`,
        date,
        label: window.label,
        kindLabel: isBooking
          ? bookingKindLabel(isHeld, isTurnaroundOnly)
          : closureKindLabel(window.reason),
        tone: isHeld ? 'warning' : 'danger',
        timeRange: formatSlice(event ?? blocked, dayStart),
        turnaround,
        sortStart: (event ?? blocked).start,
        entryLabel: isHeld ? `${HELD_ENTRY_PREFIX} – ${window.label}` : window.label,
      },
    ]
  })
}

/** Story 9.1 AC5/AC9: every window split into the part on each day it covers, in date then time
 *  order - so a day's items, and the entries a cell shows, are already in the order to list. */
export function buildDayItems(windows: VenueUnavailableWindow[]): DayItem[] {
  return windows
    .flatMap(itemsForWindow)
    .sort(
      (first, second) =>
        first.date.localeCompare(second.date) ||
        first.sortStart - second.sortStart ||
        first.label.localeCompare(second.label),
    )
}

/** The items of each day (`YYYY-MM-DD`), in the order `buildDayItems` gave them. */
export function groupDayItemsByDate(items: DayItem[]): Map<string, DayItem[]> {
  const byDate = new Map<string, DayItem[]>()
  for (const item of items) {
    byDate.set(item.date, [...(byDate.get(item.date) ?? []), item])
  }
  return byDate
}

/** One item as a cell of the month grid shows it: held ones spelled out in the text too. */
export function toCalendarEntry(item: DayItem): CalendarEntry {
  return { id: item.id, date: item.date, label: item.entryLabel, tone: item.tone }
}
