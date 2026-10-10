import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { withdrawBooking, type BookingOutcome } from '../api/bookings'
import { formatApiError } from '../api/client'
import type { VenueRequirement } from '../api/events'
import {
  searchVenues,
  type RelaxHint,
  type VenueSearchHit,
  type VenueSearchQuery,
  type VenueSearchResult,
  type VenueSummary,
} from '../api/venues'
import { useAuth } from '../auth/authContext'
import { PERMISSIONS } from '../auth/permissions'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { SuitabilityNote } from '../components/SuitabilityNote'
import { LoadingState } from '../layout/LoadingState'
import {
  VENUE_NEW_PATH,
  venueEditPath,
  venuePath,
  venueRequestPath,
  venueSwitchPath,
  type VenueSearch,
} from '../routes'
import { inputToInstant } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import {
  firstRequirementNeedingVenue,
  isBooked,
  requirementName,
  venueSearchFor,
} from '../shared/venueRequest'
import { CoveringBookingCard } from './CoveringBookingCard'
import { DeleteVenueDialog } from './DeleteVenueDialog'
import { RequestingEventBanner } from './RequestingEventBanner'
import { useRequestingEvent } from './useRequestingEvent'
import { VenueCard } from './VenueCard'
import { VenueFilterPanel } from './VenueFilterPanel'
import { hasFilters, hasSameFilters, RELAX_CHANGES, useVenueSearch } from './useVenueSearch'

/**
 * Story 8.1 AC3/AC8: the server query for the address's search. The period goes only once both
 * ends are filled in, as Singapore instants. Story 11.1 AC1: `judgedEventId` - the event a venue
 * is being requested for, once it has resolved to one the user may request a venue for - asks
 * for each result's suitability; a fake or someone else's event in the address is never sent.
 * f11.1.1: with it goes the venue requirement selected in the banner (story 8.4), so each result
 * is judged against that requirement; the page searches only once the address names one of the
 * event's, or none.
 */
function searchQueryFor(search: VenueSearch, judgedEventId: string | undefined): VenueSearchQuery {
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
    event: judgedEventId,
    requirement: judgedEventId === undefined ? undefined : search.requirementId,
  }
}

/** What the list is loaded with. A fresh object, even for the same search, loads it again. */
interface VenueListRequest {
  query: VenueSearchQuery
}

/**
 * Story 11.1: the list's load while the event in the address is still resolving - one that never
 * settles, so the page shows its loading state and searches once the event is known, rather than
 * searching without it and again with it.
 */
function untilTheEventResolves(): Promise<VenueSearchResult> {
  return new Promise(() => {})
}

/** Story 8.1 AC9: one suggested filter to remove, as its button reads. */
function describeRelaxHint(hint: RelaxHint): string {
  return `${hint.label} (${hint.count} ${hint.count === 1 ? 'venue' : 'venues'})`
}

/**
 * Story 8.1: browse the venues in service - AC1 name, location and capacity, a link to the full
 * record; AC2 withdrawn venues excluded. Sprint 2 (10.1 merged in, built as s8.1): the filter
 * panel (AC3), a search run on the server with the booking rules (AC4), and the filters kept in
 * the page address (AC4, AC11). A search that cannot be run says why beside the panel and keeps
 * the last results (AC8); when nothing matches, the page offers to remove the filters that would
 * give results, or all of them (AC9). A venue with no recorded opening hours says so when a period
 * is searched, since it is kept rather than refused (AC3).
 *
 * f12.1.1 (story 12.1 AC15): opened from an event's Find a venue, the page names that event and
 * each venue offers Request this venue, for the event's assigned coordinator only (AC5). A
 * venue's link keeps the address's query, so its record knows the event and the search too.
 *
 * Story 11.1 AC1/AC5: for that coordinator, each card also says whether the venue suits the event
 * and why not. The search waits for the event in the address to resolve and carries it only when
 * Request this venue would show (AC6), so arriving sends one search and a fake event none.
 *
 * Story 8.4: the banner lists the event's venue requirements for anyone who may read the event
 * (AC10), and selecting one replaces the filters with its own (AC3). The selection lives in the
 * address with the filters (AC4, AC11), so Find a venue opens with the first selected (AC1). An
 * address naming a requirement that is not the event's is corrected to the first, with its
 * filters, before anything is searched (AC8).
 *
 * Story 12.5: the banner says which requirements have a venue (AC2), and the stray address is
 * corrected as Find a venue now opens - to the first requirement that needs a venue, or to none
 * once every one has a request (AC5). A venue requested with none selected is an additional
 * venue, which the banner says (AC5). As decided on 10 Oct 2026, a selected requirement that
 * already has a venue shows that venue above the results, and no venue offers a request
 * (AC11). Decided 11 Oct 2026: while that request is pending, the coordinator withdraws it
 * from there, as from the event's page (12.2), and each venue below offers Switch to this
 * venue instead, through the request step; the empty list reads "No other venues".
 *
 * AC12 (f8.1.1): Venue Staff manage venues from this same page, not a separate
 * one. Holding VENUES_MANAGE adds New venue, Show withdrawn venues, and Edit and Delete on every
 * card; the backend still refuses those writes to anyone else.
 */
export function VenueCataloguePage() {
  const location = useLocation()
  const { can } = useAuth()
  const canManageVenues = can(PERMISSIONS.VENUES_MANAGE)
  const {
    event,
    bookings,
    selectedRequirement,
    selectedCovering,
    requestingEvent,
    error: eventError,
    applyBookingChange,
    isResolving,
  } = useRequestingEvent()
  const { search, updateSearch, replaceSearch, clearFilters } = useVenueSearch()
  /** Story 8.4 AC8: the address names a requirement that is not one of the event's. */
  const isStrayRequirement =
    event !== null && search.requirementId !== undefined && selectedRequirement === null
  const hasChangedFilters =
    event !== null &&
    selectedRequirement !== null &&
    !hasSameFilters(search, venueSearchFor(event, selectedRequirement))
  const isWaiting = isResolving || isStrayRequirement
  const judgedEventId = requestingEvent?.id
  const query = useMemo(() => searchQueryFor(search, judgedEventId), [search, judgedEventId])
  const [listRequest, setListRequest] = useState<VenueListRequest | null>(
    isWaiting ? null : { query },
  )
  if (!isWaiting && listRequest?.query !== query) setListRequest({ query })
  const [pendingDelete, setPendingDelete] = useState<VenueSummary | null>(null)
  const [pendingWithdraw, setPendingWithdraw] = useState<BookingOutcome | null>(null)
  const [isWithdrawing, setIsWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<string | null>(null)

  const loadVenues = useCallback(
    () => (listRequest === null ? untilTheEventResolves() : searchVenues(listRequest.query)),
    [listRequest],
  )
  const { data: result, error, setData: setResult } = useLoaded(loadVenues)
  const isPeriodSearched = query.starts_at !== undefined

  // Story 8.4 AC8: opened as Find a venue would open it - story 12.5 AC2/AC5: the event's first
  // requirement that needs a venue, or none, with the event's own dates and attendance, once
  // every one has a request or when it records none.
  useEffect(() => {
    if (event !== null && isStrayRequirement) {
      replaceSearch(venueSearchFor(event, firstRequirementNeedingVenue(event, bookings ?? [])))
    }
  }, [event, bookings, isStrayRequirement, replaceSearch])

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
    setListRequest((current) => current && { ...current })
  }

  /** Story 12.5 (decided 11 Oct 2026): withdraw the selected requirement's request here, as
   *  from the event's page (12.2), after the same confirmation. */
  function askToWithdraw(booking: BookingOutcome) {
    setWithdrawError(null)
    setPendingWithdraw(booking)
  }

  function cancelWithdraw() {
    setPendingWithdraw(null)
  }

  /** The requirement needs a venue again, and the venue it held is free, so the list reloads. */
  async function confirmWithdraw() {
    if (pendingWithdraw === null) return
    setIsWithdrawing(true)
    setWithdrawError(null)
    try {
      applyBookingChange(await withdrawBooking(pendingWithdraw.id, pendingWithdraw.venue_name))
      setPendingWithdraw(null)
      reloadVenues()
    } catch (err) {
      setWithdrawError(formatApiError(err))
    } finally {
      setIsWithdrawing(false)
    }
  }

  function removeFilter(hint: RelaxHint) {
    updateSearch(RELAX_CHANGES[hint.filter])
  }

  /** Story 8.4 AC3/AC7: the filters become the requirement's own, even when it is already the
   *  selected one and they were changed by hand. */
  function selectRequirement(requirement: VenueRequirement) {
    if (event !== null) replaceSearch(venueSearchFor(event, requirement))
  }

  /** Story 8.1 AC3's "Opening hours not recorded", and story 11.1 AC1's suitability, when the
   *  search carried the event. */
  function venueNotes(venue: VenueSearchHit) {
    const isHoursNoteShown = isPeriodSearched && venue.operating_hours_start === null
    if (!isHoursNoteShown && venue.suitability === null) return undefined
    return (
      <>
        {isHoursNoteShown && <p className="small muted">Opening hours not recorded</p>}
        {venue.suitability !== null && (
          <SuitabilityNote
            suitability={venue.suitability}
            requirementCount={requestingEvent?.venue_requirements.length ?? 0}
          />
        )}
      </>
    )
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
    if (requestingEvent && selectedCovering === null) {
      return (
        <Link
          to={venueRequestPath(requestingEvent.id, venue.id, location.search)}
          className="button brand button-sm"
        >
          Request this venue
        </Link>
      )
    }
    // Story 12.5 AC11: a selected requirement takes one request at a time. While its request is
    // pending, a venue is offered in its place (decided 11 Oct 2026); once booked, none is.
    if (requestingEvent && selectedCovering !== null && !isBooked(selectedCovering)) {
      return (
        <Link
          to={venueSwitchPath(requestingEvent.id, venue.id, location.search, selectedCovering.id)}
          className="button brand button-sm"
        >
          Switch to this venue
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
      {event && (
        <RequestingEventBanner
          event={event}
          bookings={bookings}
          selectedRequirement={selectedRequirement}
          hasChangedFilters={hasChangedFilters}
          isAdditionalVenue={
            requestingEvent !== null &&
            event.venue_requirements.length > 0 &&
            search.requirementId === undefined
          }
          onSelectRequirement={selectRequirement}
        />
      )}

      <div className="catalogue-layout">
        <VenueFilterPanel
          search={search}
          onChange={updateSearch}
          onClear={clearFilters}
          canShowWithdrawn={canManageVenues}
          error={error}
        />

        <div className="stack">
          {event !== null && selectedRequirement !== null && selectedCovering !== null && (
            <CoveringBookingCard
              booking={selectedCovering}
              requirementName={requirementName(event, selectedRequirement)}
              search={location.search}
              onWithdraw={requestingEvent === null ? undefined : askToWithdraw}
            />
          )}
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
              {/* Story 12.5: beside the selected requirement's own venue, the others. */}
              {selectedCovering === null
                ? 'No venues match these filters.'
                : 'No other venues match these filters.'}{' '}
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

      {pendingWithdraw && (
        <ConfirmDialog
          title="Withdraw this booking request?"
          confirmLabel="Withdraw"
          isBusy={isWithdrawing}
          error={withdrawError}
          onConfirm={confirmWithdraw}
          onCancel={cancelWithdraw}
        >
          <p>
            The request for {pendingWithdraw.venue_name} will be withdrawn and its hold on the venue
            released. Venue Staff will be told.
          </p>
        </ConfirmDialog>
      )}

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
