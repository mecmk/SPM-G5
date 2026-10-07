import { useCallback } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { getVenue, getVenueCalendar, type Venue } from '../api/venues'
import { Chip } from '../components/Chip'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { VenueAvailabilityCalendar } from '../components/VenueAvailabilityCalendar'
import { LoadingState } from '../layout/LoadingState'
import { VENUE_CATALOGUE_PATH, venueRequestPath } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { useVenueCalendar } from '../shared/useVenueCalendar'
import { useRequestingEvent } from './useRequestingEvent'

const DAY_PANEL_ID = 'venue-calendar-day-panel'

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
  const loadWindows = useCallback(
    (startsAt: string, endsAt: string) => getVenueCalendar(venueId, startsAt, endsAt),
    [venueId],
  )
  const calendar = useVenueCalendar(loadWindows, new Date())

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
            <VenueAvailabilityCalendar
              month={calendar.month}
              onMonthChange={calendar.setMonth}
              windows={calendar.windows}
              error={calendar.error}
              isLoading={calendar.isLoading}
              dayPanelId={DAY_PANEL_ID}
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
