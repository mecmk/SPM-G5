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
// so both use these names. `event` names the event a venue is being found for, and `requirement`
// which of its venue requirements is selected in the catalogue's banner (story 8.4 AC4). `search`,
// `capacity_max` and `withdrawn` are the panel's own (s8.1); Find a venue never sets them.
export const VENUE_SEARCH_PARAMS = {
  event: 'event',
  requirement: 'requirement',
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
  /** Story 8.4 AC4: the event's venue requirement selected in the catalogue's banner. */
  requirementId?: string
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
  if (search.requirementId) params.set(VENUE_SEARCH_PARAMS.requirement, search.requirementId)
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
    requirementId: params.get(VENUE_SEARCH_PARAMS.requirement) ?? undefined,
    search: searchText(params.get(VENUE_SEARCH_PARAMS.search)),
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
 * Story 8.1 AC3: name or location text, typed or in the address. Only spaces is no filter: the
 * server ignores it, so the panel must not count it as one either. Other text is kept as typed,
 * so a pause after "tower " does not lose the space before "b".
 */
export function searchText(value: string | null): string | undefined {
  return value === null || value.trim() === '' ? undefined : value
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

// Story 5.4: the Event Coordinator Lead's queue of submitted events with no coordinator yet.
export const EVENTS_UNASSIGNED_PATH = '/events/unassigned'

// Story 5.5: the Lead's overview of every active event and each coordinator's assignments. Its
// view and filters live in the address (AC1), so a link or a reload keeps them.
export const EVENTS_ASSIGNMENTS_PATH = '/events/assignments'
export const ASSIGNMENT_SEARCH_PARAMS = {
  view: 'view',
  status: 'status',
  coordinator: 'coordinator',
  assignedByMe: 'assigned',
} as const
/** The `view` value for the per-coordinator view; without it, the page shows the overview. The
 *  `assigned` value for "Assigned by me" is the API's own, `ASSIGNED_BY_ME_FILTER`. */
export const COORDINATORS_VIEW = 'coordinators'

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

// Story 12.5 (decided 11 Oct 2026): Switch to this venue opens the same step, its address also
// naming the pending request it replaces. The step's back link leaves it out.
export const VENUE_REQUEST_REPLACES_PARAM = 'replaces'

export function venueSwitchPath(
  eventId: string,
  venueId: string,
  search: string,
  replacedBookingId: string,
): string {
  const params = new URLSearchParams(search)
  params.set(VENUE_REQUEST_REPLACES_PARAM, replacedBookingId)
  return venueRequestPath(eventId, venueId, `?${params}`)
}

// Story 13.1: the venue staff booking requests queue. Venue Staff's own section is structured as
// separate concerns (team decision, 21 Sep 2026): booking requests, schedule, and venues (which reuses the venue catalogue
// above rather than a duplicate).
export const BOOKING_REQUESTS_PATH = '/venue-staff/booking-requests'
export const BOOKING_REQUEST_PATH = '/venue-staff/booking-requests/:bookingId'
export const VENUE_SCHEDULE_PATH = '/venue-staff/schedule'

export function bookingRequestPath(bookingId: string): string {
  return BOOKING_REQUEST_PATH.replace(':bookingId', encodeURIComponent(bookingId))
}

// Story 15.2: Technical Support's queue of the equipment requests sent to it. Story 16.1: each
// request's own page, where it can be accepted or declined.
export const EQUIPMENT_REQUESTS_PATH = '/equipment/requests'
export const EQUIPMENT_REQUEST_PATH = '/equipment/requests/:itemId'

export function equipmentRequestPath(itemId: string): string {
  return EQUIPMENT_REQUEST_PATH.replace(':itemId', encodeURIComponent(itemId))
}

// Story 21.1: the Safety Officer's queue of events awaiting the safety check, and each one's page.
export const SAFETY_CHECKS_PATH = '/safety-checks'
export const SAFETY_CHECK_PATH = '/safety-checks/:eventId'

export function safetyCheckPath(eventId: string): string {
  return SAFETY_CHECK_PATH.replace(':eventId', encodeURIComponent(eventId))
}

// Story 19.2: the coordinator's queue of change requests waiting for a decision.
export const CHANGE_REQUEST_QUEUE_PATH = '/change-requests/review'

// Story 18.1: the events an attendee can browse and register for.
export const UPCOMING_EVENTS_PATH = '/browse'

// Story 18.2: the attendee's own registrations, and withdrawing one.
export const MY_REGISTRATIONS_PATH = '/registrations'

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

// Story 7.2: the assigned Event Coordinator edits an event - its internal notes until it is
// closed, and the organiser's request too until it is confirmed (f7.2.4).
export const EVENT_COORDINATOR_EDIT_PATH = '/events/:eventId/coordinator-edit'

export function eventCoordinatorEditPath(eventId: string): string {
  return EVENT_COORDINATOR_EDIT_PATH.replace(':eventId', encodeURIComponent(eventId))
}
