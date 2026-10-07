import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import { getEvent, type EventDetail } from '../api/events'
import { useAuth } from '../auth/authContext'
import { VENUE_SEARCH_PARAMS } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { canRequestVenueFor } from '../shared/venueRequest'

/** What a venue page knows about the event named in its address. */
export interface RequestingEventState {
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
 * f12.1.1 (story 12.1 AC15): the event named by the page address (`?event=`), when the signed-in
 * user may request a venue for it - its assigned coordinator, while it can take a booking. For
 * anyone else, or with no event in the address, `requestingEvent` is null and the catalogue and
 * the venue's record stay as they are. `POST /bookings` checks the same when the request is sent.
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
  const isRequestable =
    event !== null && event.id === eventId && canRequestVenueFor(event, user, can)
  const isResolving = eventId !== null && error === null && event?.id !== eventId
  return { requestingEvent: isRequestable ? event : null, error, isResolving }
}
