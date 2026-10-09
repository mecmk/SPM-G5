import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import { listBookingsForEvent, type BookingOutcome } from '../api/bookings'
import { getEvent, type EventDetail, type VenueRequirement } from '../api/events'
import { useAuth } from '../auth/authContext'
import { PERMISSIONS } from '../auth/permissions'
import { VENUE_SEARCH_PARAMS } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { canRequestVenueFor, coveringBooking } from '../shared/venueRequest'

/** What a venue page knows about the event named in its address. */
export interface RequestingEventState {
  /** Story 8.4 AC10: the event named in the address, once loaded, for anyone who may read it -
   * so the catalogue's banner lists its venue requirements. Null with no event in the address. */
  event: EventDetail | null
  /** Story 12.5 AC2: the event's venue bookings, so the banner can say which of its requirements
   * have a venue - for whoever may read bookings. Null for anyone else, or if they did not load. */
  bookings: BookingOutcome[] | null
  /** Story 8.4: the event's venue requirement the address selects, if it names one of the event's. */
  selectedRequirement: VenueRequirement | null
  /** Story 12.5 AC11 (decided 10 Oct 2026): the pending or approved request that already covers
   * the selected requirement, so no page offers another request for it. Null while it needs one. */
  selectedCovering: BookingOutcome | null
  /** The event a venue is being found for, when the signed-in user may request one for it. */
  requestingEvent: EventDetail | null
  /** Why the event in the address, or its bookings, could not be loaded, otherwise null. */
  error: string | null
  /** Story 11.1: the address names an event that has not loaded or failed yet, so it is not known
   * whether the user may request a venue for it. The catalogue waits for this before searching,
   * so it searches once - with the event, or without it. Story 12.5: likewise its bookings. */
  isResolving: boolean
}

/** One event's venue bookings, with the event they are for: `useLoaded` keeps the last ones while
 *  a changed address loads. */
interface EventBookings {
  eventId: string
  bookings: BookingOutcome[]
}

/**
 * f12.1.1 (story 12.1 AC15): the event named by the page address (`?event=`). `requestingEvent`
 * is that event when the signed-in user may request a venue for it - its assigned coordinator,
 * while it can take a booking; for anyone else, or with no event in the address, it is null and
 * the catalogue and the venue's record offer no request. `POST /bookings` checks the same when the
 * request is sent. Story 8.4 AC10: `event` is the event for anyone the backend lets read it.
 *
 * Story 12.5: with the event come its venue bookings (`GET /bookings/for-event`, bookings:read),
 * loaded alongside it so the event is given once both are known, and the request covering the
 * requirement the address selects (`?requirement=`).
 */
export function useRequestingEvent(): RequestingEventState {
  const [searchParams] = useSearchParams()
  const eventId = searchParams.get(VENUE_SEARCH_PARAMS.event)
  const requirementId = searchParams.get(VENUE_SEARCH_PARAMS.requirement)
  const { user, can } = useAuth()
  const canReadBookings = can(PERMISSIONS.BOOKINGS_READ)
  const loadEvent = useCallback(
    () => (eventId === null ? Promise.resolve(null) : getEvent(eventId)),
    [eventId],
  )
  const { data: event, error } = useLoaded(loadEvent)
  const loadBookings = useCallback(
    () =>
      eventId === null || !canReadBookings
        ? Promise.resolve(null)
        : listBookingsForEvent(eventId).then((bookings): EventBookings => ({ eventId, bookings })),
    [eventId, canReadBookings],
  )
  const { data: eventBookings, error: bookingsError } = useLoaded(loadBookings)

  // `useLoaded` keeps the last event while a changed address loads, so check it is this one.
  const addressEvent = event !== null && event.id === eventId ? event : null
  const bookings =
    eventBookings !== null && eventBookings.eventId === eventId ? eventBookings.bookings : null
  const isLoadingBookings =
    eventId !== null && canReadBookings && bookingsError === null && bookings === null
  const isResolving =
    eventId !== null && error === null && (addressEvent === null || isLoadingBookings)
  const resolvedEvent = isResolving ? null : addressEvent
  const isRequestable = resolvedEvent !== null && canRequestVenueFor(resolvedEvent, user, can)
  const selectedRequirement =
    resolvedEvent?.venue_requirements.find((requirement) => requirement.id === requirementId) ??
    null
  return {
    event: resolvedEvent,
    bookings,
    selectedRequirement,
    selectedCovering:
      selectedRequirement === null || bookings === null
        ? null
        : coveringBooking(selectedRequirement, bookings),
    requestingEvent: isRequestable ? resolvedEvent : null,
    error: error ?? bookingsError,
    isResolving,
  }
}
