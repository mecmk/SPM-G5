import { useCallback, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { listVenues, type VenueSummary } from '../api/venues'
import { useAuth } from '../auth/authContext'
import { PERMISSIONS } from '../auth/permissions'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import { VENUE_NEW_PATH, venueEditPath, venuePath, venueRequestPath } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { DeleteVenueDialog } from './DeleteVenueDialog'
import { RequestingEventBanner } from './RequestingEventBanner'
import { useRequestingEvent } from './useRequestingEvent'
import { VenueCard } from './VenueCard'

function numberOrNull(value: string): number | null {
  const parsed = Number(value)
  return value.trim() === '' || !Number.isFinite(parsed) ? null : parsed
}

function matchesSearch(venue: VenueSummary, search: string): boolean {
  const term = search.trim().toLowerCase()
  return (
    term === '' ||
    venue.name.toLowerCase().includes(term) ||
    venue.location.toLowerCase().includes(term)
  )
}

function matchesCapacity(venue: VenueSummary, minCapacity: string, maxCapacity: string): boolean {
  const min = numberOrNull(minCapacity)
  const max = numberOrNull(maxCapacity)
  return (min === null || venue.capacity >= min) && (max === null || venue.capacity <= max)
}

/** What the list is loaded with. A fresh object, even with the same values, loads it again. */
interface VenueListRequest {
  includeWithdrawn: boolean
}

/**
 * Story 8.1: an Event Coordinator browses venues in service. AC1 name/location/capacity, a link
 * to the full record, withdrawn venues excluded. The name-or-location search and the capacity
 * range (team decision, 17 Sep 2026, frontend design prototype) are applied client-side.
 *
 * f12.1.1 (story 12.1 AC15): opened from an event's Find a venue, the page names that event and
 * each venue offers Request this venue, for the event's assigned coordinator only. A venue's link
 * keeps the address's query, so its record knows the event too. Filling the filters in from the
 * address is story 8.1 AC3's.
 *
 * AC13 (f8.1.1, Sprint 1 review): Venue Staff manage venues from this same page, not a separate
 * one. Holding VENUES_MANAGE adds New venue, Show withdrawn venues, and Edit and Delete on every
 * card; the backend still refuses those writes to anyone else.
 */
export function VenueCataloguePage() {
  const location = useLocation()
  const { can } = useAuth()
  const canManageVenues = can(PERMISSIONS.VENUES_MANAGE)
  const { requestingEvent, error: eventError } = useRequestingEvent()
  const [listRequest, setListRequest] = useState<VenueListRequest>({ includeWithdrawn: false })
  const [search, setSearch] = useState('')
  const [minCapacity, setMinCapacity] = useState('')
  const [maxCapacity, setMaxCapacity] = useState('')
  const [pendingDelete, setPendingDelete] = useState<VenueSummary | null>(null)

  const loadVenues = useCallback(() => listVenues(listRequest.includeWithdrawn), [listRequest])
  const { data: venues, error, setData: setVenues } = useLoaded(loadVenues)
  const isShowingWithdrawn = listRequest.includeWithdrawn

  const shownVenues = useMemo(
    () =>
      (venues ?? []).filter(
        (venue) => matchesSearch(venue, search) && matchesCapacity(venue, minCapacity, maxCapacity),
      ),
    [venues, search, minCapacity, maxCapacity],
  )

  const isFiltered = search !== '' || minCapacity !== '' || maxCapacity !== '' || isShowingWithdrawn

  function clearFilters() {
    setSearch('')
    setMinCapacity('')
    setMaxCapacity('')
    setListRequest({ includeWithdrawn: false })
  }

  function showWithdrawn(includeWithdrawn: boolean) {
    setListRequest({ includeWithdrawn })
  }

  function askToDelete(venue: VenueSummary) {
    setPendingDelete(venue)
  }

  function cancelDelete() {
    setPendingDelete(null)
  }

  function removeDeletedVenue() {
    const deletedId = pendingDelete?.id
    setVenues((current) => current && current.filter((venue) => venue.id !== deletedId))
    setPendingDelete(null)
  }

  /** The list is out of date: a venue it shows was deleted elsewhere. */
  function reloadVenues() {
    setListRequest((current) => ({ ...current }))
  }

  function venueActions(venue: VenueSummary) {
    if (canManageVenues) {
      return (
        <div className="row-actions">
          <Link
            to={venueEditPath(venue.id)}
            className="button secondary button-sm button-with-icon"
          >
            <Icon name="pencil" size={14} /> Edit
          </Link>
          <button
            type="button"
            className="danger button-sm button-with-icon"
            onClick={() => askToDelete(venue)}
          >
            <Icon name="trash" size={14} /> Delete
          </button>
        </div>
      )
    }
    if (requestingEvent) {
      return (
        <Link
          to={venueRequestPath(requestingEvent.id, venue.id, location.search)}
          className="button brand button-sm"
        >
          Request this venue
        </Link>
      )
    }
    return undefined
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Venue catalogue"
        subtitle={
          canManageVenues
            ? 'Keep the venue records accurate. Coordinators plan every event against them.'
            : 'Venues currently in service. Select one to see its full record.'
        }
        action={
          canManageVenues ? (
            <Link to={VENUE_NEW_PATH} className="button button-with-icon">
              <Icon name="plus" size={16} /> New venue
            </Link>
          ) : undefined
        }
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
            Name or location
            <input
              type="search"
              placeholder="Any"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
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
          {canManageVenues && (
            <label className="checkbox">
              <input
                type="checkbox"
                checked={isShowingWithdrawn}
                onChange={(e) => showWithdrawn(e.target.checked)}
              />
              Show withdrawn venues
            </label>
          )}
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
            <EmptyState>
              {isShowingWithdrawn
                ? 'No venues recorded yet.'
                : 'No venues are currently in service.'}
              {canManageVenues && (
                <>
                  {' '}
                  <Link to={VENUE_NEW_PATH}>Add the first venue</Link> so coordinators can plan with
                  it.
                </>
              )}
            </EmptyState>
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
                  <VenueCard
                    key={venue.id}
                    venue={venue}
                    recordPath={`${venuePath(venue.id)}${location.search}`}
                    actions={venueActions(venue)}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {pendingDelete && (
        <DeleteVenueDialog
          venue={pendingDelete}
          onDeleted={removeDeletedVenue}
          onCancel={cancelDelete}
          onAlreadyGone={reloadVenues}
        />
      )}
    </div>
  )
}
