import { Fragment, useCallback, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router'
import {
  searchVenues,
  type RelaxHint,
  type VenueSearchHit,
  type VenueSearchQuery,
  type VenueSummary,
} from '../api/venues'
import { useAuth } from '../auth/authContext'
import { PERMISSIONS } from '../auth/permissions'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import {
  VENUE_NEW_PATH,
  venueEditPath,
  venuePath,
  venueRequestPath,
  type VenueSearch,
} from '../routes'
import { inputToInstant } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { DeleteVenueDialog } from './DeleteVenueDialog'
import { RequestingEventBanner } from './RequestingEventBanner'
import { useRequestingEvent } from './useRequestingEvent'
import { VenueCard } from './VenueCard'
import { VenueFilterPanel } from './VenueFilterPanel'
import { hasFilters, RELAX_CHANGES, useVenueSearch } from './useVenueSearch'

/**
 * Story 8.1 AC2/AC7: the server query for the address's search. The period goes only once both
 * ends are filled in, as Singapore instants.
 */
function searchQueryFor(search: VenueSearch): VenueSearchQuery {
  const hasPeriod = Boolean(search.from && search.to)
  return {
    search: search.search,
    capacity: search.capacity,
    capacity_max: search.capacityMax,
    starts_at: hasPeriod && search.from ? inputToInstant(search.from) : undefined,
    ends_at: hasPeriod && search.to ? inputToInstant(search.to) : undefined,
    layout: search.layout,
    facility: search.facilities,
    accessibility: search.accessibilityFeatures,
    include_withdrawn: search.includeWithdrawn,
  }
}

/** What the list is loaded with. A fresh object, even for the same search, loads it again. */
interface VenueListRequest {
  query: VenueSearchQuery
}

/** Story 8.1 AC8: one suggested filter to remove, as its button reads. */
function describeRelaxHint(hint: RelaxHint): string {
  return `${hint.label} (${hint.count} ${hint.count === 1 ? 'venue' : 'venues'})`
}

/**
 * Story 8.1: browse the venues in service - AC1 name, location and capacity, a link to the full
 * record, withdrawn venues excluded. Sprint 2 (10.1 merged in, built as s8.1): the filter panel
 * (AC2), a search run on the server with the booking rules (AC4), and the filters kept in the page
 * address (AC4, AC10). A search that cannot be run says why beside the panel and keeps the last
 * results (AC7); when nothing matches, the page offers to remove the filters that would give
 * results, or all of them (AC8). A venue with no recorded opening hours says so when a period is
 * searched, since it is kept rather than refused (AC2).
 *
 * f12.1.1 (story 12.1 AC15): opened from an event's Find a venue, the page names that event and
 * each venue offers Request this venue, for the event's assigned coordinator only (AC11). A
 * venue's link keeps the address's query, so its record knows the event and the search too.
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
  const { search, updateSearch, clearFilters } = useVenueSearch()
  const query = useMemo(() => searchQueryFor(search), [search])
  const [listRequest, setListRequest] = useState<VenueListRequest>({ query })
  if (listRequest.query !== query) setListRequest({ query })
  const [pendingDelete, setPendingDelete] = useState<VenueSummary | null>(null)

  const loadVenues = useCallback(() => searchVenues(listRequest.query), [listRequest])
  const { data: result, error, setData: setResult } = useLoaded(loadVenues)
  const isPeriodSearched = query.starts_at !== undefined

  function askToDelete(venue: VenueSummary) {
    setPendingDelete(venue)
  }

  function cancelDelete() {
    setPendingDelete(null)
  }

  function removeDeletedVenue() {
    const deletedId = pendingDelete?.id
    setResult(
      (current) =>
        current && {
          ...current,
          venues: current.venues.filter((venue) => venue.id !== deletedId),
          total: current.total - 1,
        },
    )
    setPendingDelete(null)
  }

  /** The list is out of date: a venue it shows was deleted elsewhere. */
  function reloadVenues() {
    setListRequest((current) => ({ ...current }))
  }

  function removeFilter(hint: RelaxHint) {
    updateSearch(RELAX_CHANGES[hint.filter])
  }

  function venueNotes(venue: VenueSearchHit) {
    if (!isPeriodSearched || venue.operating_hours_start !== null) return undefined
    return <p className="small muted">Opening hours not recorded</p>
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
        <VenueFilterPanel
          search={search}
          onChange={updateSearch}
          onClear={clearFilters}
          canShowWithdrawn={canManageVenues}
          error={error}
        />

        <div className="stack">
          {result === null && !error && <LoadingState label="Loading venues…" />}

          {result !== null && result.venues.length === 0 && !hasFilters(search) && (
            <EmptyState>
              {search.includeWithdrawn
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

          {result !== null && result.venues.length === 0 && hasFilters(search) && (
            <EmptyState>
              No venues match these filters.{' '}
              {result.relax.length > 0 && (
                <>
                  Try removing:{' '}
                  {result.relax.map((hint, index) => (
                    <Fragment key={hint.filter}>
                      {index > 0 && ', '}
                      <button type="button" className="link" onClick={() => removeFilter(hint)}>
                        {describeRelaxHint(hint)}
                      </button>
                    </Fragment>
                  ))}
                  , or{' '}
                </>
              )}
              <button type="button" className="link" onClick={clearFilters}>
                Clear filters
              </button>
              .
            </EmptyState>
          )}

          {result !== null && result.venues.length > 0 && (
            <>
              <p className="small muted">
                Showing {result.venues.length} of {result.total} venues
              </p>
              <div className="item-grid item-grid-2">
                {result.venues.map((venue) => (
                  <VenueCard
                    key={venue.id}
                    venue={venue}
                    recordPath={`${venuePath(venue.id)}${location.search}`}
                    notes={venueNotes(venue)}
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
