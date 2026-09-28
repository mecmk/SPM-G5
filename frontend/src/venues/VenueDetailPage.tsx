import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { formatApiError } from '../api/client'
import { getVenue, getVenueCalendar, type Venue, type VenueUnavailableWindow } from '../api/venues'
import { Calendar, type CalendarLegendItem } from '../components/Calendar'
import { isoDate } from '../components/calendarGrid'
import { Chip } from '../components/Chip'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { VENUE_CATALOGUE_PATH, venueRequestPath } from '../routes'
import { inputToInstant } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { useRequestingEvent } from './useRequestingEvent'
import {
  buildDayItems,
  groupDayItemsByDate,
  HELD_LABEL,
  toCalendarEntry,
} from './venueCalendarDays'
import { VenueDayPanel } from './VenueDayPanel'

// Story 9.1 AC2: a pending request that holds the venue has a style of its own.
const CALENDAR_LEGEND: CalendarLegendItem[] = [
  { tone: 'danger', label: 'Unavailable' },
  { tone: 'warning', label: HELD_LABEL },
]

const DAY_PANEL_ID = 'venue-calendar-day-panel'

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

/** Singapore-midnight instant for the first day of `month` (see shared/format.ts). */
function monthBoundary(month: Date): string {
  return inputToInstant(`${isoDate(month.getFullYear(), month.getMonth(), 1)}T00:00`)
}

const STATUS_LABELS: Record<Venue['status'], string> = {
  ACTIVE: 'In service',
  WITHDRAWN: 'Withdrawn',
}

const NOT_RECORDED = 'Not recorded'

/**
 * Story 8.1 AC1: a venue's full record, opened from the catalogue. Story 8.2 covers the display
 * rules for these characteristics in more depth (unknown vs. absent, readable by Event
 * Coordinators and Venue Staff) - the fields already come back from `getVenue`, so this page
 * shows them all now rather than in two passes.
 *
 * The hero's location line is `venue.location` alone: the schema has one combined location
 * string, not separate building/floor fields to build a longer breadcrumb from.
 *
 * f12.1.1 (story 12.1 AC15): opened from the catalogue for an event, the event's assigned
 * coordinator can request the venue from here too, and the back link returns to that same search.
 */
export function VenueDetailPage() {
  const { venueId = '' } = useParams()
  const location = useLocation()
  const loadVenue = useCallback(() => getVenue(venueId), [venueId])
  const { data: venue, error } = useLoaded(loadVenue)
  const { requestingEvent, error: eventError } = useRequestingEvent()
  const [month, setMonth] = useState(() => startOfMonth(new Date()))
  // Not reset when venueId changes - nothing links from one venue's page straight to another's
  // today, so this can't be observed yet. If that ever becomes possible, this needs to go back
  // to clearing windows (or keying the calendar on venueId) so a new venue never shows a moment
  // of the previous one's availability.
  const [windows, setWindows] = useState<VenueUnavailableWindow[]>([])
  const [calendarError, setCalendarError] = useState<string | null>(null)
  const [isCalendarLoading, setIsCalendarLoading] = useState(true)
  /** Story 9.1 AC5: the day (`YYYY-MM-DD`) whose list is open under the calendar, if any. */
  const [openDay, setOpenDay] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setIsCalendarLoading(true)
    // Clears a previous month's failure immediately, so it cannot sit on screen describing a
    // month that is no longer the one being loaded.
    setCalendarError(null)
    // An open day belongs to the month it was opened in, so previous / next close it.
    setOpenDay(null)
    const rangeStart = monthBoundary(month)
    const rangeEnd = monthBoundary(new Date(month.getFullYear(), month.getMonth() + 1, 1))
    getVenueCalendar(venueId, rangeStart, rangeEnd)
      .then((data) => {
        if (cancelled) return
        setWindows(data)
        setCalendarError(null)
        setIsCalendarLoading(false)
      })
      .catch((err) => {
        if (cancelled) return
        // Falls back to "everything available" rather than leaving stale data on screen or
        // hiding the calendar - a deliberate choice, not a neutral default (see f9.1.1 PR notes).
        setWindows([])
        setCalendarError(formatApiError(err))
        setIsCalendarLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [venueId, month])

  /** f9.1.1 AC2: an empty grid can mean loading, genuinely free, or failed - `entries` alone
   *  cannot tell those apart, so this drives a visibly distinct treatment for the two that are
   *  not "genuinely free" instead of rendering all three identically. */
  const calendarStatus: 'loading' | 'unknown' | 'ready' = isCalendarLoading
    ? 'loading'
    : calendarError
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
    setOpenDay((current) => (current === date ? null : date))
  }

  if (error) {
    return (
      <div className="page">
        <p role="alert" className="error">
          {error}
        </p>
      </div>
    )
  }
  if (!venue) return <LoadingState label="Loading the venue…" />

  return (
    <div className="page page-wide">
      <Link to={`${VENUE_CATALOGUE_PATH}${location.search}`} className="back-link">
        ← Venue catalogue
      </Link>
      {eventError && (
        <p role="alert" className="error">
          {eventError}
        </p>
      )}
      {requestingEvent && (
        <div className="page-header actions-only">
          <div className="page-actions">
            <Link
              to={venueRequestPath(requestingEvent.id, venue.id, location.search)}
              className="button brand"
            >
              Request this venue
            </Link>
          </div>
        </div>
      )}

      <div className="venue-hero">
        <span aria-hidden="true">
          <Icon name="building" size={36} />
        </span>
        <div className="venue-hero-overlay">
          <div className="cluster">
            <StatusBadge status={venue.status} label={STATUS_LABELS[venue.status]} />
          </div>
          <h1>{venue.name}</h1>
          <p className="venue-hero-meta">{venue.location}</p>
          {venue.description && <p className="venue-hero-meta">{venue.description}</p>}
        </div>
      </div>

      <div className="layout-split">
        <div className="stack">
          <section className="card stack" aria-labelledby="venue-capacity-heading">
            <p className="eyebrow" id="venue-capacity-heading">
              Capacity
            </p>
            {venue.layouts.length === 0 ? (
              <p className="muted">{NOT_RECORDED}</p>
            ) : (
              <div className="layout-grid">
                {venue.layouts.map((layout) => (
                  <div key={layout.code} className="layout-box">
                    <span>{layout.name}</span>
                    <span className="mono">{layout.layout_capacity ?? venue.capacity}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card stack" aria-labelledby="venue-facilities-heading">
            <p className="eyebrow" id="venue-facilities-heading">
              Facilities
            </p>
            <div className="cluster">
              {venue.facilities.length === 0 && <p className="muted">{NOT_RECORDED}</p>}
              {venue.facilities.map((item) => (
                <Chip
                  key={item.code}
                  tone="info"
                  label={`${item.name}${item.quantity ? ` × ${item.quantity}` : ''}${item.notes ? ` (${item.notes})` : ''}`}
                />
              ))}
            </div>
          </section>

          <section className="card stack" aria-labelledby="venue-accessibility-heading">
            <p className="eyebrow" id="venue-accessibility-heading">
              Accessibility
            </p>
            <div className="cluster">
              {venue.accessibility_features.length === 0 && <p className="muted">{NOT_RECORDED}</p>}
              {venue.accessibility_features.map((item) => (
                <Chip
                  key={item.code}
                  tone="success"
                  label={`${item.name}${item.notes ? ` (${item.notes})` : ''}`}
                />
              ))}
            </div>
          </section>

          <section className="card stack" aria-labelledby="venue-operating-heading">
            <p className="eyebrow" id="venue-operating-heading">
              Operating information
            </p>
            <ul className="check-list">
              <li>
                <span className="grow-text">Hours</span>
                <span>
                  {venue.operating_hours_start && venue.operating_hours_end
                    ? `${venue.operating_hours_start.slice(0, 5)}–${venue.operating_hours_end.slice(0, 5)}`
                    : NOT_RECORDED}
                </span>
              </li>
              <li>
                <span className="grow-text">Setup</span>
                <span>{venue.setup_minutes_default} min</span>
              </li>
              <li>
                <span className="grow-text">Teardown</span>
                <span>{venue.teardown_minutes_default} min</span>
              </li>
              <li>
                <span className="grow-text">Floor area</span>
                <span>{venue.floor_area_sqm ? `${venue.floor_area_sqm} m²` : NOT_RECORDED}</span>
              </li>
              <li>
                <span className="grow-text">Notes</span>
                <span>{venue.operating_notes || NOT_RECORDED}</span>
              </li>
            </ul>
          </section>

          <section className="card stack" aria-labelledby="venue-availability-heading">
            <p className="eyebrow" id="venue-availability-heading">
              Availability
            </p>
            {calendarError && (
              <p role="alert" className="error">
                {calendarError}
              </p>
            )}
            {/* Always rendered - only the text inside changes - so this can never itself cause
                the calendar below it to shift (f9.1.1). role="status" announces the change to
                assistive tech the way the LoadingState it replaced did. */}
            <p className="muted calendar-status-line" role="status">
              {calendarStatus === 'loading' && 'Loading availability…'}
              {calendarStatus === 'unknown' &&
                'Availability unknown - showing every day as available may not be accurate.'}
            </p>
            <Calendar
              month={month}
              onMonthChange={setMonth}
              entries={calendarEntries}
              legend={CALENDAR_LEGEND}
              gridStatus={calendarStatus === 'ready' ? undefined : calendarStatus}
              onOpenDay={handleOpenDay}
              openDay={isDayOpen ? openDay : null}
              openDayPanelId={DAY_PANEL_ID}
            />
            {isDayOpen && <VenueDayPanel id={DAY_PANEL_ID} date={openDay} items={openDayItems} />}
          </section>
        </div>

        <aside className="card stack" aria-labelledby="venue-quick-facts-heading">
          <p className="eyebrow" id="venue-quick-facts-heading">
            Quick facts
          </p>
          <ul className="check-list">
            <li>
              <span className="grow-text">Max capacity</span>
              <span className="mono">{venue.capacity}</span>
            </li>
            <li>
              <span className="grow-text">Area</span>
              <span className="mono">
                {venue.floor_area_sqm ? `${venue.floor_area_sqm} m²` : NOT_RECORDED}
              </span>
            </li>
            <li>
              <span className="grow-text">Layouts</span>
              <span className="mono">{venue.layouts.length}</span>
            </li>
            <li>
              <span className="grow-text">Facilities</span>
              <span className="mono">{venue.facilities.length}</span>
            </li>
          </ul>
        </aside>
      </div>
    </div>
  )
}
