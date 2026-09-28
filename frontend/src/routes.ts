/** Route paths used by more than one file (frontend/STYLE.md: one constant per shared literal). */
export const HOME_PATH = '/'
export const LOGIN_PATH = '/login'

/** Story c3's component gallery, served in development builds only. */
export const COMPONENT_GALLERY_PATH = '/dev/components'

// Story 8.1: venue catalogue.
export const VENUE_CATALOGUE_PATH = '/venues'
export const VENUE_PATH = '/venues/:venueId'

export function venuePath(venueId: string): string {
  return VENUE_PATH.replace(':venueId', encodeURIComponent(venueId))
}

// f12.1.1 (story 12.1 AC15) and story 8.1 AC4: the venue catalogue's filters in the page
// address. The event page's Find a venue writes them and 8.1's filter panel reads and writes them,
// so both use these names. `event` names the event a venue is being found for. `search`,
// `capacity_max` and `withdrawn` are the panel's own (s8.1); Find a venue never sets them.
export const VENUE_SEARCH_PARAMS = {
  event: 'event',
  search: 'search',
  capacity: 'capacity',
  capacityMax: 'capacity_max',
  from: 'from',
  to: 'to',
  layout: 'layout',
  facility: 'facility',
  accessibility: 'accessibility',
  withdrawn: 'withdrawn',
} as const

/** A catalogue search. `from` / `to` are Singapore `datetime-local` values; codes are the shared
 *  reference codes (room layouts, facilities, accessibility features). */
export interface VenueSearch {
  eventId?: string
  /** Name or location contains this text. */
  search?: string
  capacity?: number
  capacityMax?: number
  from?: string
  to?: string
  layout?: string
  facilities?: readonly string[]
  accessibilityFeatures?: readonly string[]
  /** Story 8.1 AC12: withdrawn venues listed too, for Venue Staff. */
  includeWithdrawn?: boolean
}

/** The address query for `search`, holding only the filters it sets. */
export function venueSearchParams(search: VenueSearch): URLSearchParams {
  const params = new URLSearchParams()
  if (search.eventId) params.set(VENUE_SEARCH_PARAMS.event, search.eventId)
  if (search.search) params.set(VENUE_SEARCH_PARAMS.search, search.search)
  if (search.capacity !== undefined) {
    params.set(VENUE_SEARCH_PARAMS.capacity, String(search.capacity))
  }
  if (search.capacityMax !== undefined) {
    params.set(VENUE_SEARCH_PARAMS.capacityMax, String(search.capacityMax))
  }
  if (search.from) params.set(VENUE_SEARCH_PARAMS.from, search.from)
  if (search.to) params.set(VENUE_SEARCH_PARAMS.to, search.to)
  if (search.layout) params.set(VENUE_SEARCH_PARAMS.layout, search.layout)
  for (const code of search.facilities ?? []) params.append(VENUE_SEARCH_PARAMS.facility, code)
  for (const code of search.accessibilityFeatures ?? []) {
    params.append(VENUE_SEARCH_PARAMS.accessibility, code)
  }
  if (search.includeWithdrawn) params.set(VENUE_SEARCH_PARAMS.withdrawn, 'true')
  return params
}

/** Story 8.1 AC4: the search a catalogue address holds - the reverse of `venueSearchParams`. A
 *  capacity that is not a whole number is ignored rather than sent. */
export function readVenueSearch(params: URLSearchParams): VenueSearch {
  return {
    eventId: params.get(VENUE_SEARCH_PARAMS.event) ?? undefined,
    search: params.get(VENUE_SEARCH_PARAMS.search) ?? undefined,
    capacity: capacityLimit(params.get(VENUE_SEARCH_PARAMS.capacity)),
    capacityMax: capacityLimit(params.get(VENUE_SEARCH_PARAMS.capacityMax)),
    from: params.get(VENUE_SEARCH_PARAMS.from) ?? undefined,
    to: params.get(VENUE_SEARCH_PARAMS.to) ?? undefined,
    layout: params.get(VENUE_SEARCH_PARAMS.layout) ?? undefined,
    facilities: params.getAll(VENUE_SEARCH_PARAMS.facility),
    accessibilityFeatures: params.getAll(VENUE_SEARCH_PARAMS.accessibility),
    includeWithdrawn: params.get(VENUE_SEARCH_PARAMS.withdrawn) === 'true',
  }
}

/**
 * Story 8.1 AC6: a capacity limit, typed or in the address - a whole number above 0. Anything else
 * (blank, 0, a negative or a fraction) is no limit, so it is left out of the search rather than
 * refused by the server.
 */
export function capacityLimit(value: string | null): number | undefined {
  const parsed = Number(value)
  return value === null || value.trim() === '' || !Number.isInteger(parsed) || parsed < 1
    ? undefined
    : parsed
}

/** The catalogue's address for `search`, holding only the filters it sets. */
export function venueSearchPath(search: VenueSearch): string {
  const query = venueSearchParams(search).toString()
  return query === '' ? VENUE_CATALOGUE_PATH : `${VENUE_CATALOGUE_PATH}?${query}`
}

// Story 8.3: venue records. f8.1.1 (8.1 AC12) removed the Manage venues page - Venue Staff manage
// venues from the catalogue - so this address is kept only to redirect old links there.
export const VENUES_MANAGE_PATH = '/venues/manage'
export const VENUE_NEW_PATH = '/venues/new'
export const VENUE_EDIT_PATH = '/venues/:venueId/edit'

export function venueEditPath(venueId: string): string {
  return VENUE_EDIT_PATH.replace(':venueId', encodeURIComponent(venueId))
}

// Story 4.1: the coordinator review queue.
export const EVENTS_INBOX_PATH = '/events/inbox'

// Story 12.1: the old Request a venue page. f12.1.1 moved the request into the event's context,
// so this address is kept only to redirect old links to the Events inbox.
export const BOOKING_REQUEST_NEW_PATH = '/bookings/new'

// f12.1.1 (story 12.1 AC15): the request step for one event and one venue, reached with Request
// this venue from the catalogue in that event's context. `search` is the catalogue's own query,
// carried along so the step's back link returns to the same search.
export const VENUE_REQUEST_PATH = '/events/:eventId/request-venue/:venueId'

export function venueRequestPath(eventId: string, venueId: string, search = ''): string {
  const path = VENUE_REQUEST_PATH.replace(':eventId', encodeURIComponent(eventId)).replace(
    ':venueId',
    encodeURIComponent(venueId),
  )
  return `${path}${search}`
}

// Story 13.1: the venue staff booking requests queue. Venue Staff's own section, structured
// as separate concerns (team decision, 21 Sep 2026): booking requests, schedule, and venues
// (which reuses the venue catalogue above rather than a duplicate).
export const BOOKING_REQUESTS_PATH = '/venue-staff/booking-requests'
export const BOOKING_REQUEST_PATH = '/venue-staff/booking-requests/:bookingId'
export const VENUE_SCHEDULE_PATH = '/venue-staff/schedule'

export function bookingRequestPath(bookingId: string): string {
  return BOOKING_REQUEST_PATH.replace(':bookingId', encodeURIComponent(bookingId))
}

// Story 2.6: the organiser's own list of event requests.
export const EVENTS_MINE_PATH = '/events/mine'

// Story 2.1: raising and editing an event request.
export const EVENT_NEW_PATH = '/events/new'
export const EVENT_EDIT_PATH = '/events/:eventId/edit'

export function eventEditPath(eventId: string): string {
  return EVENT_EDIT_PATH.replace(':eventId', encodeURIComponent(eventId))
}

// Story 7.1: the canonical event details page, for every role related to the event.
export const EVENT_PATH = '/events/:eventId'

export function eventPath(eventId: string): string {
  return EVENT_PATH.replace(':eventId', encodeURIComponent(eventId))
}

// Story 7.2: the assigned Event Coordinator edits an event's routine information.
export const EVENT_EDIT_ROUTINE_PATH = '/events/:eventId/routine-information'

export function eventEditRoutinePath(eventId: string): string {
  return EVENT_EDIT_ROUTINE_PATH.replace(':eventId', encodeURIComponent(eventId))
}
