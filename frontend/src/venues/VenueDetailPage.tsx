import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { formatApiError } from '../api/client'
import { getVenue, getVenueCalendar, type Venue, type VenueUnavailableWindow } from '../api/venues'
import { Calendar, type CalendarEntry, type CalendarLegendItem } from '../components/Calendar'
import { eachDate, isoDate } from '../components/calendarGrid'
import { Chip } from '../components/Chip'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { VENUE_CATALOGUE_PATH } from '../routes'
import { inputToInstant } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

const CALENDAR_LEGEND: CalendarLegendItem[] = [{ tone: 'danger', label: 'Unavailable' }]

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
 * Story 8.1 AC2: a venue's full record, opened from the catalogue. Story 8.2 covers the display
 * rules for these characteristics in more depth (unknown vs. absent, readable by Event
 * Coordinators and Venue Staff) - the fields already come back from `getVenue`, so this page
 * shows them all now rather than in two passes.
 *
 * The hero's location line is `venue.location` alone: the schema has one combined location
 * string, not separate building/floor fields to build a longer breadcrumb from.
 */
export function VenueDetailPage() {
  const { venueId = '' } = useParams()
  const loadVenue = useCallback(() => getVenue(venueId), [venueId])
  const { data: venue, error } = useLoaded(loadVenue)
  const [month, setMonth] = useState(() => startOfMonth(new Date()))
  // Not reset when venueId changes - nothing links from one venue's page straight to another's
  // today, so this can't be observed yet. If that ever becomes possible, this needs to go back
  // to clearing windows (or keying the calendar on venueId) so a new venue never shows a moment
  // of the previous one's availability.
  const [windows, setWindows] = useState<VenueUnavailableWindow[]>([])
  const [calendarError, setCalendarError] = useState<string | null>(null)
  const [isCalendarLoading, setIsCalendarLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setIsCalendarLoading(true)
    // Clears a previous month's failure immediately, so it cannot sit on screen describing a
    // month that is no longer the one being loaded.
    setCalendarError(null)
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

  const calendarEntries: CalendarEntry[] = useMemo(
    () =>
      windows.flatMap((window) =>
        eachDate(window.starts_at, window.ends_at).map((date) => ({
          id: `${window.starts_at}-${date}`,
          date,
          label: window.label,
          tone: 'danger' as const,
        })),
      ),
    [windows],
  )

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
      <Link to={VENUE_CATALOGUE_PATH} className="back-link">
        ← Venue catalogue
      </Link>

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
            />
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
