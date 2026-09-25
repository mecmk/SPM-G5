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

// Story 8.3: venue records.
export const VENUES_MANAGE_PATH = '/venues/manage'
export const VENUE_NEW_PATH = '/venues/new'
export const VENUE_EDIT_PATH = '/venues/:venueId/edit'

export function venueEditPath(venueId: string): string {
  return VENUE_EDIT_PATH.replace(':venueId', encodeURIComponent(venueId))
}

// Story 4.1: the coordinator review queue.
export const EVENTS_INBOX_PATH = '/events/inbox'

// Story 12.1: raise a venue booking request.
export const BOOKING_REQUEST_NEW_PATH = '/bookings/new'

// Story 13.1: the venue staff booking requests queue. Venue Staff's own section, structured
// as separate concerns (team decision, 21 Sep 2026): booking requests, schedule, and venues
// (which reuses the existing catalogue/manage routes above rather than a duplicate).
export const BOOKING_REQUESTS_PATH = '/venue-staff/booking-requests'
export const BOOKING_REQUEST_PATH = '/venue-staff/booking-requests/:bookingId'
export const VENUE_SCHEDULE_PATH = '/venue-staff/schedule'

export function bookingRequestPath(bookingId: string): string {
  return BOOKING_REQUEST_PATH.replace(':bookingId', encodeURIComponent(bookingId))
}

// Story 13.2.1: the same booking detail page, reachable by anyone who can read the booking
// (BOOKINGS_READ) rather than only Venue Staff who can decide it (BOOKINGS_DECIDE) - the
// requesting coordinator's route into 13.2.1 AC4, distinct from BOOKING_REQUEST_PATH so the
// venue staff queue's own permission gate is untouched.
export const BOOKING_DETAIL_PATH = '/bookings/:bookingId'

export function bookingDetailPath(bookingId: string): string {
  return BOOKING_DETAIL_PATH.replace(':bookingId', encodeURIComponent(bookingId))
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
