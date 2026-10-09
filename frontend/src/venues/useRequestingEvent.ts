import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import { getEvent, type EventDetail } from '../api/events'
import { useAuth } from '../auth/authContext'
import { VENUE_SEARCH_PARAMS } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { canRequestVenueFor } from '../shared/venueRequest'

/** What a venue page knows about the event named in its address. */
export interface RequestingEventState {
  /** Story 8.4 AC10: the event named in the address, once loaded, for anyone who may read it -
   * so the catalogue's banner lists its venue requirements. Null with no event in the address. */
  event: EventDetail | null
  /** The event a venue is being found for, when the signed-in user may request one for it. */
  requestingEvent: EventDetail | null
  /** Why the event in the address could not be loaded, otherwise null. */
  error: string | null
  /** Story 11.1: the address names an event that has not loaded or failed yet, so it is not known
   * whether the user may request a venue for it. The catalogue waits for this before searching,
   * so it searches once - with the event, or without it. */
  isResolving: boolean
}

/**
 * f12.1.1 (story 12.1 AC15): the event named by the page address (`?event=`). `requestingEvent`
 * is that event when the signed-in user may request a venue for it - its assigned coordinator,
 * while it can take a booking; for anyone else, or with no event in the address, it is null and
 * the catalogue and the venue's record offer no request. `POST /bookings` checks the same when the
 * request is sent. Story 8.4 AC10: `event` is the event for anyone the backend lets read it.
 */
export function useRequestingEvent(): RequestingEventState {
  const [searchParams] = useSearchParams()
  const eventId = searchParams.get(VENUE_SEARCH_PARAMS.event)
  const { user, can } = useAuth()
  const loadEvent = useCallback(
    () => (eventId === null ? Promise.resolve(null) : getEvent(eventId)),
    [eventId],
  )
  const { data: event, error } = useLoaded(loadEvent)

  // `useLoaded` keeps the last event while a changed address loads, so check it is this one.
  const addressEvent = event !== null && event.id === eventId ? event : null
  const isRequestable = addressEvent !== null && canRequestVenueFor(addressEvent, user, can)
  const isResolving = eventId !== null && error === null && addressEvent === null
  return {
    event: addressEvent,
    requestingEvent: isRequestable ? addressEvent : null,
    error,
    isResolving,
  }
}
