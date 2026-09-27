import { useMemo, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router'
import { listVenues, type VenueSummary } from '../api/venues'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import { VENUE_SEARCH_PARAMS, venuePath, venueRequestPath } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { RequestingEventBanner } from './RequestingEventBanner'
import { useRequestingEvent } from './useRequestingEvent'

function numberOrNull(value: string): number | null {
  const parsed = Number(value)
  return value.trim() === '' || !Number.isFinite(parsed) ? null : parsed
}

function matchesCapacity(venue: VenueSummary, minCapacity: string, maxCapacity: string): boolean {
  const min = numberOrNull(minCapacity)
  const max = numberOrNull(maxCapacity)
  return (min === null || venue.capacity >= min) && (max === null || venue.capacity <= max)
}

/** The address's minimum capacity, when it is a number: the event's expected attendance when the
 *  catalogue is opened from Find a venue (f12.1.1). */
function capacityFromAddress(searchParams: URLSearchParams): string {
  const capacity = searchParams.get(VENUE_SEARCH_PARAMS.capacity) ?? ''
  return numberOrNull(capacity) === null ? '' : capacity
}

function loadVenuesInService() {
  return listVenues(false)
}

/**
 * Story 8.1: an Event Coordinator browses venues in service. AC1 name/location/capacity, AC2 a
 * link to the full record, AC3 withdrawn venues excluded. The capacity range filter (team
 * decision, 17 Sep 2026, frontend design prototype) is applied client-side, the same way story
 * 8.3's Venue Staff list filters by capacity.
 *
 * f12.1.1 (story 12.1 AC15): opened from an event's Find a venue, the page names that event and
 * each venue offers Request this venue, for the event's assigned coordinator only. "Capacity
 * from" starts at the address's `capacity`, the event's expected attendance, so only venues big
 * enough are shown (story 8.1 AC3's minimum capacity). A venue's link keeps the address's query,
 * so its record knows the event too.
 */
export function VenueCataloguePage() {
  const { data: venues, error } = useLoaded(loadVenuesInService)
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { requestingEvent, error: eventError } = useRequestingEvent()
  const [minCapacity, setMinCapacity] = useState(() => capacityFromAddress(searchParams))
  const [maxCapacity, setMaxCapacity] = useState('')

  const shownVenues = useMemo(
    () => (venues ?? []).filter((venue) => matchesCapacity(venue, minCapacity, maxCapacity)),
    [venues, minCapacity, maxCapacity],
  )

  const isFiltered = minCapacity !== '' || maxCapacity !== ''

  function clearFilters() {
    setMinCapacity('')
    setMaxCapacity('')
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Venue catalogue"
        subtitle="Venues currently in service. Select one to see its full record."
      />

      {eventError && (
        <p role="alert" className="error">
          {eventError}
        </p>
      )}
      {requestingEvent && <RequestingEventBanner event={requestingEvent} />}

      <div className="catalogue-layout">
        <aside className="filter-column">
          <label>
            Capacity from
            <input
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              placeholder="Any"
              value={minCapacity}
              onChange={(e) => setMinCapacity(e.target.value)}
            />
          </label>
          <label>
            Capacity to
            <input
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              placeholder="Any"
              value={maxCapacity}
              onChange={(e) => setMaxCapacity(e.target.value)}
            />
          </label>
          {isFiltered && (
            <button type="button" className="link" onClick={clearFilters}>
              Clear all filters
            </button>
          )}
        </aside>

        <div className="stack">
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {venues === null && !error && <LoadingState label="Loading venues…" />}

          {venues !== null && venues.length === 0 && (
            <EmptyState>No venues are currently in service.</EmptyState>
          )}

          {venues !== null && venues.length > 0 && shownVenues.length === 0 && (
            <EmptyState>No venues match these filters.</EmptyState>
          )}

          {shownVenues.length > 0 && (
            <>
              <p className="small muted">
                Showing {shownVenues.length} of {venues?.length ?? 0} venues
              </p>
              <div className="item-grid item-grid-2">
                {shownVenues.map((venue) => (
                  <article key={venue.id} className="item-card">
                    <div className="item-card-picture" aria-hidden="true">
                      <Icon name="building" size={28} />
                    </div>
                    <div className="item-card-body">
                      <div className="item-card-header">
                        <div>
                          <h3 className="item-card-title">
                            <Link to={`${venuePath(venue.id)}${location.search}`}>
                              {venue.name}
                            </Link>
                          </h3>
                          <p className="small muted">{venue.location}</p>
                        </div>
                        <div className="item-card-capacity">
                          <div className="item-card-capacity-value">{venue.capacity}</div>
                          <div className="item-card-capacity-label">capacity</div>
                        </div>
                      </div>
                      {requestingEvent && (
                        <div className="item-card-footer">
                          <Link
                            to={venueRequestPath(requestingEvent.id, venue.id, location.search)}
                            className="button brand button-sm"
                          >
                            Request this venue
                          </Link>
                        </div>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
