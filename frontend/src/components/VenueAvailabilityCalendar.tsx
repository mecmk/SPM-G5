import { useMemo, useState } from 'react'
import type { VenueUnavailableWindow } from '../api/venues'
import { Calendar, type CalendarLegendItem } from './Calendar'
import { VenueDayPanel } from './VenueDayPanel'
import {
  buildDayItems,
  groupDayItemsByDate,
  HELD_LABEL,
  toCalendarEntry,
} from './venueCalendarDays'

// Story 9.1 AC2: a pending request that holds the venue has a style of its own.
const CALENDAR_LEGEND: CalendarLegendItem[] = [
  { tone: 'danger', label: 'Unavailable' },
  { tone: 'warning', label: HELD_LABEL },
]

export interface VenueAvailabilityCalendarProps {
  /** The first day of the month shown. */
  month: Date
  onMonthChange: (nextMonth: Date) => void
  windows: VenueUnavailableWindow[]
  /** The message to show when the month failed to load, otherwise null. */
  error: string | null
  isLoading: boolean
  /** The id the open day's list takes, unique on the page. */
  dayPanelId: string
  /** Story 13.1.3 AC2: a day (`YYYY-MM-DD`) whose list is open on arrival, once it has items. */
  initialOpenDay?: string | null
}

/**
 * Story 9.1: one venue's month of bookings, holds and closures, with a pressed day's list below
 * it. Shown on the venue's own page and, story 13.1.3, beside a booking request Venue Staff are
 * deciding. The page loads the month (`useVenueCalendar`) and wraps this in its own titled card.
 */
export function VenueAvailabilityCalendar({
  month,
  onMonthChange,
  windows,
  error,
  isLoading,
  dayPanelId,
  initialOpenDay = null,
}: VenueAvailabilityCalendarProps) {
  /** Story 9.1 AC5: the day (`YYYY-MM-DD`) whose list is open under the calendar, if any. */
  const [openDay, setOpenDay] = useState<string | null>(initialOpenDay)
  // A day open on arrival stays where it is: scrolling to it would carry the page away from
  // what is above the calendar, a booking request's Approve and Reject among them.
  const [hasPickedDay, setHasPickedDay] = useState(false)

  /** f9.1.1 AC2: an empty grid can mean loading, genuinely free, or failed - `entries` alone
   *  cannot tell those apart, so this drives a visibly distinct treatment for the two that are
   *  not "genuinely free" instead of rendering all three identically. */
  const status: 'loading' | 'unknown' | 'ready' = isLoading
    ? 'loading'
    : error
      ? 'unknown'
      : 'ready'

  /** Story 9.1 AC5/AC9: each window split into the part on every day it covers. */
  const dayItems = useMemo(() => buildDayItems(windows), [windows])
  const itemsByDate = useMemo(() => groupDayItemsByDate(dayItems), [dayItems])
  const calendarEntries = useMemo(() => dayItems.map(toCalendarEntry), [dayItems])
  // A day stays open only while it has items, so one whose booking is gone closes.
  const openDayItems = openDay === null ? [] : (itemsByDate.get(openDay) ?? [])
  const isDayOpen = openDay !== null && openDayItems.length > 0

  function handleOpenDay(date: string) {
    setHasPickedDay(true)
    setOpenDay((current) => (current === date ? null : date))
  }

  // An open day belongs to the month it was opened in, so changing month closes it - done here
  // rather than in the fetch, so it is not tied to every refetch (e.g. the venue changing).
  function handleMonthChange(nextMonth: Date) {
    setOpenDay(null)
    onMonthChange(nextMonth)
  }

  return (
    <>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {/* Always rendered - only the text inside changes - so this can never itself cause the
          calendar below it to shift (f9.1.1). role="status" announces the change to assistive
          tech the way the LoadingState it replaced did. */}
      <p className="muted calendar-status-line" role="status">
        {status === 'loading' && 'Loading availability…'}
        {status === 'unknown' &&
          'Availability unknown - showing every day as available may not be accurate.'}
      </p>
      <Calendar
        month={month}
        onMonthChange={handleMonthChange}
        entries={calendarEntries}
        legend={CALENDAR_LEGEND}
        gridStatus={status === 'ready' ? undefined : status}
        onOpenDay={handleOpenDay}
        openDay={isDayOpen ? openDay : null}
        openDayPanelId={dayPanelId}
      />
      {isDayOpen && (
        <VenueDayPanel
          id={dayPanelId}
          date={openDay}
          items={openDayItems}
          scrollIntoView={hasPickedDay}
        />
      )}
    </>
  )
}
