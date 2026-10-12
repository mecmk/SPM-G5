import { useCallback, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { mediaUrl } from '../api/client'
import { getVenue, getVenueCalendar, type Venue } from '../api/venues'
import { Chip } from '../components/Chip'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { VenueAvailabilityCalendar } from '../components/VenueAvailabilityCalendar'
import { LoadingState } from '../layout/LoadingState'
import { VENUE_CATALOGUE_PATH, venueRequestPath, venueSwitchPath } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { useVenueCalendar } from '../shared/useVenueCalendar'
import { describeCoveredRequirement, isBooked, requirementName } from '../shared/venueRequest'
import { useRequestingEvent } from './useRequestingEvent'
import { VenuePictureViewer } from './VenuePictureViewer'

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
 * Story 12.5 AC11: when the venue requirement selected there already has a venue, the page says so.
 * Once it is booked, nothing is offered; while it is only requested, the venue is offered in its
 * place with Switch to this venue (decided 11 Oct 2026).
 *
 * Story 8.3 AC6 (bug f8.3.2): the venue's first picture fills the banner, and every picture shows
 * in a gallery, in order; selecting one opens a pop-up carousel at it. Without pictures the banner
 * keeps its icon and there is no gallery.
 */
export function VenueDetailPage() {
  const { venueId = '' } = useParams()
  const location = useLocation()
  const loadVenue = useCallback(() => getVenue(venueId), [venueId])
  const { data: venue, error } = useLoaded(loadVenue)
  const {
    requestingEvent,
    selectedRequirement,
    selectedCovering,
    error: eventError,
  } = useRequestingEvent()
  const loadWindows = useCallback(
    (startsAt: string, endsAt: string) => getVenueCalendar(venueId, startsAt, endsAt),
    [venueId],
  )
  const calendar = useVenueCalendar(loadWindows, new Date())
  /** Story 8.3 AC6: a banner picture that failed to load, so the icon shows instead. */
  const [failedCoverUrl, setFailedCoverUrl] = useState<string | null>(null)
  /** Story 8.3 AC6: the gallery picture the carousel is open on, if it is open. */
  const [viewerIndex, setViewerIndex] = useState<number | null>(null)

  function markCoverFailed() {
    setFailedCoverUrl(venue?.cover_image_url ?? null)
  }

  function closeViewer() {
    setViewerIndex(null)
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
  const coverUrl = venue.cover_image_url

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
            {/* Story 12.5 AC11: the selected requirement already has a venue, which the page
             *  names; it is switched while only requested, never once booked. */}
            {selectedRequirement !== null && selectedCovering !== null && (
              <p className="muted">
                {describeCoveredRequirement(
                  requirementName(requestingEvent, selectedRequirement),
                  selectedCovering,
                )}
              </p>
            )}
            {selectedCovering === null && (
              <Link
                to={venueRequestPath(requestingEvent.id, venue.id, location.search)}
                className="button brand"
              >
                Request this venue
              </Link>
            )}
            {selectedCovering !== null && !isBooked(selectedCovering) && (
              <Link
                to={venueSwitchPath(
                  requestingEvent.id,
                  venue.id,
                  location.search,
                  selectedCovering.id,
                )}
                className="button brand"
              >
                Switch to this venue
              </Link>
            )}
          </div>
        </div>
      )}

      <div className="venue-hero">
        {coverUrl !== null && coverUrl !== failedCoverUrl ? (
          <img
            className="venue-hero-picture"
            src={mediaUrl(coverUrl) ?? undefined}
            alt=""
            onError={markCoverFailed}
          />
        ) : (
          <span aria-hidden="true">
            <Icon name="building" size={36} />
          </span>
        )}
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
          {venue.images.length > 0 && (
            <section className="card stack" aria-labelledby="venue-pictures-heading">
              <p className="eyebrow" id="venue-pictures-heading">
                Pictures
              </p>
              <ul className="picture-gallery">
                {venue.images.map((image, index) => (
                  <li key={image.id}>
                    <button
                      type="button"
                      className="picture-gallery-button"
                      onClick={() => setViewerIndex(index)}
                    >
                      <img
                        src={mediaUrl(image.url) ?? undefined}
                        alt={`Picture ${index + 1} of ${venue.images.length}`}
                      />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {viewerIndex !== null && (
            <VenuePictureViewer
              venueName={venue.name}
              pictures={venue.images}
              startIndex={viewerIndex}
              onClose={closeViewer}
            />
          )}

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
