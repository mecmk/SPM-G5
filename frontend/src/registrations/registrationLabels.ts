import type {
  Guest,
  MyRegistration,
  RegistrationEvent,
  RegistrationStanding,
  RegistrationState,
  RegistrationVenue,
} from '../api/registrations'
import { FULL_LABEL } from '../components/RegistrationCount'
import { eventBadgeStatus } from '../shared/eventStatus'
import { formatDateTime, NONE, NOT_RECORDED } from '../shared/format'

/** Story 18.1: the title of the list of events an attendee can register for, which an event's
 *  page links back to (AC9, fix f18.1.2). */
export const UPCOMING_EVENTS_TITLE = 'Upcoming events'

/** Story 18.2: the title of the attendee's own registrations, which an event's page opened from
 *  one links back to (AC9, fix f18.2.1). */
export const MY_REGISTRATIONS_TITLE = 'My registrations'

/** Story 18.2 AC3: why an active registration offers no Withdraw - its event has started. */
export const STARTED_NOTE = 'This event has started, so it can no longer be withdrawn.'

/** A registration badge: the status that picks its colour (App.css's `badge-<status>`) and its
 *  label. */
export interface RegistrationBadge {
  status: string
  label: string
}

/** Stories 18.1 AC1 and 18.2 AC1: an attendee's active registration, as Upcoming events and My
 *  registrations both show it. */
export const REGISTERED_BADGE: RegistrationBadge = { status: 'registered', label: 'Registered' }

/** Story 18.1 AC1/AC3/AC9: each state's label, and the badge colour it takes (App.css), on an
 *  event's card and its page. */
export const STATE_BADGES: Record<RegistrationState, RegistrationBadge> = {
  OPEN: { status: 'success', label: 'Open' },
  NOT_YET_OPEN: { status: 'info', label: 'Not yet open' },
  FULL: { status: 'warning', label: FULL_LABEL },
  CLOSED: { status: 'neutral', label: 'Closed' },
  REGISTERED: REGISTERED_BADGE,
}

/** Story 18.1 AC1: what a Confirmed event with no approved venue booking shows. */
const NO_VENUE_YET = 'Venue to be confirmed'

/** Story 18.1 AC1/AC9: a booked venue's name and location. */
export function describeVenue(venue: RegistrationVenue): string {
  return `${venue.name}, ${venue.location}`
}

/** Story 18.1 AC1/AC9: each venue a listed event has booked, on its card and its page - or that
 *  one is still to be confirmed. */
export function describeVenues(venues: RegistrationVenue[]): string[] {
  return venues.length === 0 ? [NO_VENUE_YET] : venues.map(describeVenue)
}

/** Story 18.1 AC1/AC9: the places left are shown (decided 14 Oct 2026). */
export function describePlacesLeft(placesLeft: number): string {
  return `${placesLeft} ${placesLeft === 1 ? 'place' : 'places'} left`
}

/** Story 18.1 AC2/AC3: when registration opens, while it has not. */
function describeOpening(opensAt: string): string {
  return `Registration opens ${formatDateTime(opensAt)}`
}

/** Story 18.1 AC2: when registration closes, or closed - the closing time, or the event's start
 *  where none was recorded, as the server sends it. */
function describeClosing(event: RegistrationEvent): string {
  const verb = event.state === 'CLOSED' ? 'closed' : 'closes'
  return `Registration ${verb} ${formatDateTime(event.registration_closes_at)}`
}

/**
 * Story 18.1 AC1-AC3: the one time an event's card gives - when the attendee registered (AC1's
 * confirmation, kept after a reload), when registration opens while it has not, or when it
 * closes or closed.
 */
export function describeRegistration(event: RegistrationEvent): string {
  if (event.registered_at !== null) {
    return describeRegisteredAt(event.registered_at)
  }
  if (event.registration_opens_at !== null && event.state === 'NOT_YET_OPEN') {
    return describeOpening(event.registration_opens_at)
  }
  return describeClosing(event)
}

/**
 * Story 18.1 AC9 (fix f18.1.2): the times an event's page gives - when the attendee registered,
 * once they have; otherwise when registration opens, while it has not, and when it closes or
 * closed.
 */
export function describeRegistrationTimes(event: RegistrationEvent): string[] {
  if (event.registered_at !== null) {
    return [describeRegisteredAt(event.registered_at)]
  }
  if (event.registration_opens_at !== null && event.state === 'NOT_YET_OPEN') {
    return [describeOpening(event.registration_opens_at), describeClosing(event)]
  }
  return [describeClosing(event)]
}

/** Stories 18.2 AC1/AC8 and 18.3 AC4: each standing's label, and the badge colour it takes
 *  (App.css), as the attendee and the event's organiser and coordinator both see it. Registered
 *  is 18.1's badge; Event cancelled is a cancelled event's colour, as every event status page
 *  shows it, not a cancelled booking's (shared/eventStatus.ts keeps the two apart). */
export const STANDING_BADGES: Record<RegistrationStanding, RegistrationBadge> = {
  REGISTERED: REGISTERED_BADGE,
  WITHDRAWN: { status: 'withdrawn', label: 'Withdrawn' },
  EVENT_CANCELLED: { status: eventBadgeStatus('CANCELLED'), label: 'Event cancelled' },
}

/** Stories 18.1 AC1 and 18.2 AC1: when the attendee registered, as both pages say it. */
export function describeRegisteredAt(registeredAt: string): string {
  return `You registered on ${formatDateTime(registeredAt)}`
}

/** Story 18.2 AC1/AC9: when the attendee registered, while they still are - on their card on My
 *  registrations and on the event's page - and, story 18.5 AC3, the guests registered with them,
 *  when there are any. Where they stand now, not a history: a registration withdrawn or cancelled
 *  gives no time, and its guests went with it (18.5 AC7). */
export function describeActiveRegistration(registration: MyRegistration): string[] {
  if (registration.status !== 'REGISTERED') return []
  const lines = [describeRegisteredAt(registration.registered_at)]
  if (registration.guests.length > 0) {
    lines.push(`Your guests: ${describeGuests(registration.guests)}`)
  }
  return lines
}

/** Story 18.4 AC6: an attendee's dietary requirements as every page shows them - "None" when they
 *  left them blank. */
export function describeDietaryRequirements(dietaryRequirements: string | null): string {
  return dietaryRequirements ?? NONE
}

/** Story 18.4 AC7: an attendee's phone number as every page shows it. It is required (CL-166),
 *  but an attendee who registered before 18.4 and has not been asked since has none yet. */
export function describePhone(phone: string | null): string {
  return phone ?? NOT_RECORDED
}

/** Story 18.5 AC3: one guest as the attendee sees them on My registrations - their name, and
 *  their dietary requirements beside it when there are any to show. */
export function describeGuest(guest: Guest): string {
  return guest.dietary_requirements === null
    ? guest.full_name
    : `${guest.full_name} (${guest.dietary_requirements})`
}

/** Story 18.5 AC3: the guests registered with the attendee, in order, as My registrations
 *  names them. */
export function describeGuests(guests: Guest[]): string {
  return guests.map(describeGuest).join(', ')
}

/** Story 18.5 AC4: whose guest a row of the registration list is. */
export function describeGuestOf(attendeeName: string): string {
  return `Guest of ${attendeeName}`
}
