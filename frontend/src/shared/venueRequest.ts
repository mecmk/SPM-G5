import type { CurrentUser } from '../api/auth'
import type { BookingOutcome, BookingStatus } from '../api/bookings'
import type { EventDetail, RequiredFacility, VenueRequirement } from '../api/events'
import { PERMISSIONS, type Permission } from '../auth/permissions'
import type { VenueSearch } from '../routes'
import { BOOKABLE_EVENT_STATUSES } from './eventStatus'
import { instantToInput } from './format'

const APPROVED: BookingStatus = 'APPROVED'
/** Story 12.5 AC10: the statuses of the one request a venue requirement may hold at a time. */
const COVERING_STATUSES: readonly BookingStatus[] = ['PENDING', APPROVED]

/** Story 12.5 AC2: a requirement's request reads "Booked" once Venue Staff approved it, and
 *  "Requested" while it is pending. */
export function isBooked(booking: BookingOutcome): boolean {
  return booking.status === APPROVED
}

/** Story 2.7 AC8: a requirement's name, or its place when a draft left it unnamed. */
export function requirementName(event: EventDetail, requirement: VenueRequirement): string {
  return (
    requirement.name ?? `Venue requirement ${event.venue_requirements.indexOf(requirement) + 1}`
  )
}

/**
 * Story 12.5 AC2: the request that covers `requirement` - its one pending or approved booking -
 * or null while it needs a venue. A rejected or withdrawn request covers nothing (AC8).
 */
export function coveringBooking(
  requirement: VenueRequirement,
  bookings: readonly BookingOutcome[],
): BookingOutcome | null {
  return (
    bookings.find(
      (booking) =>
        booking.venue_requirement_id === requirement.id &&
        COVERING_STATUSES.includes(booking.status) &&
        !isPendingReplacementOfLiveOriginal(booking, bookings),
    ) ?? null
  )
}

/**
 * Story 12.6 AC10: a pending replacement whose original still holds its venue covers nothing - the
 * original does - as the backend's `find_covering_booking` and its one-per-requirement index leave
 * it out. Once the original stops holding, the replacement is the requirement's request.
 */
function isPendingReplacementOfLiveOriginal(
  booking: BookingOutcome,
  bookings: readonly BookingOutcome[],
): boolean {
  if (booking.status !== 'PENDING' || booking.replaces_booking_id === null) return false
  const original = bookings.find((each) => each.id === booking.replaces_booking_id)
  return original !== undefined && COVERING_STATUSES.includes(original.status)
}

/** Story 9.4 AC3: Venue Staff's closure marked the booking "Venue unavailable - alternative
 * needed"; the mark is null once the booking holds nothing. */
export function isMarked(booking: BookingOutcome): boolean {
  return booking.venue_unavailable_marked_at !== null
}

/** Story 12.6 AC1/AC9: only an approved booking still marked is replaced; a marked pending one is
 * switched to another venue (12.5). */
export function isReplaceable(booking: BookingOutcome): boolean {
  return booking.status === APPROVED && isMarked(booking)
}

/** Story 12.6 AC4: the replacement asked for `booking`, while it is pending. */
export function pendingReplacementFor(
  booking: BookingOutcome,
  bookings: readonly BookingOutcome[],
): BookingOutcome | null {
  return (
    bookings.find((each) => each.replaces_booking_id === booking.id && each.status === 'PENDING') ??
    null
  )
}

/** Story 12.6 AC1: the venue requirement `booking` is for, null for an additional venue. */
export function requirementOfBooking(
  event: EventDetail,
  booking: BookingOutcome,
): VenueRequirement | null {
  return event.venue_requirements.find((each) => each.id === booking.venue_requirement_id) ?? null
}

/**
 * Story 12.5 AC11: why a requirement takes no other request - "Meeting room already has a venue
 * booked: Seminar Room 2.1." The venue's record says it in place of Request this venue.
 */
export function describeCoveredRequirement(
  requirementName: string,
  covering: BookingOutcome,
): string {
  const state = isBooked(covering) ? 'booked' : 'requested'
  return `${requirementName} already has a venue ${state}: ${covering.venue_name}.`
}

/**
 * Story 12.5 AC2/AC3: the first of `event`'s venue requirements that still needs a venue - the one
 * Find a venue selects, and the one a sent request moves on to. Null once every requirement has a
 * pending or approved request (AC4, AC5), or when the event lists none (AC7).
 */
export function firstRequirementNeedingVenue(
  event: EventDetail,
  bookings: readonly BookingOutcome[],
): VenueRequirement | null {
  return (
    event.venue_requirements.find(
      (requirement) => coveringBooking(requirement, bookings) === null,
    ) ?? null
  )
}

/** What finding or booking a venue for one of an event's venue requirements asks the venue for. */
export interface VenueRequestTerms {
  requirement: VenueRequirement | null
  startsAt: string | null
  endsAt: string | null
  capacity: number | null
  layoutCode: string | null
  layoutName: string | null
  facilities: RequiredFacility[]
}

/**
 * Story 2.7 / 8.4 / 12.5 AC1: the period, number of people, layout and facilities `requirement` of
 * `event` asks for - each falling back to the event's own when the requirement has none, as
 * `create_booking_request` writes them. With no requirement - an additional venue (12.5 AC5, AC7)
 * - the event's own period and attendance.
 */
export function venueRequirementTerms(
  event: EventDetail,
  requirement: VenueRequirement | null,
): VenueRequestTerms {
  const hasOwnTimes = requirement !== null && requirement.starts_at !== null
  return {
    requirement,
    startsAt: hasOwnTimes ? requirement.starts_at : event.starts_at,
    endsAt: hasOwnTimes ? requirement.ends_at : event.ends_at,
    capacity: requirement?.capacity ?? event.expected_attendance,
    layoutCode: requirement?.layout_code ?? null,
    layoutName: requirement?.layout_name ?? null,
    facilities: requirement?.facilities ?? [],
  }
}

/**
 * f12.1.1 (story 12.1 AC15) and story 8.4 AC1/AC2: the catalogue search for `requirement` of
 * `event`, holding only what the event recorded - the requirement's times, its number of people as
 * the minimum capacity, its layout and facilities, plus the event's accessibility needs - and
 * naming the requirement, so the catalogue shows it selected. Find a venue opens it for the first
 * requirement that needs a venue (story 12.5 AC2) and the catalogue's banner for whichever is
 * selected, so both build the same search. With no requirement, the event's own dates and
 * attendance (8.4 AC6), selecting none: an additional venue (12.5 AC5).
 */
export function venueSearchFor(
  event: EventDetail,
  requirement: VenueRequirement | null,
  replacingBookingId?: string,
): VenueSearch {
  const terms = venueRequirementTerms(event, requirement)
  return {
    eventId: event.id,
    requirementId: requirement?.id,
    replacingBookingId,
    capacity: terms.capacity ?? undefined,
    from: terms.startsAt ? instantToInput(terms.startsAt) : undefined,
    to: terms.endsAt ? instantToInput(terms.endsAt) : undefined,
    layout: terms.layoutCode ?? undefined,
    facilities: terms.facilities.map((facility) => facility.code),
    accessibilityFeatures: event.accessibility_needs.map((need) => need.code),
  }
}

/**
 * Story 12.6 AC1: the catalogue's address for replacing `booking`, an approved booking marked
 * "Venue unavailable": its requirement's own search - or, for an additional venue, the event's
 * own period and attendance - with the booking named, so the catalogue leaves its venue out. For
 * a marked pending booking, the requirement's search alone: its venues offer Switch (12.5).
 */
export function replacementSearchFor(event: EventDetail, booking: BookingOutcome): VenueSearch {
  return venueSearchFor(
    event,
    requirementOfBooking(event, booking),
    isReplaceable(booking) ? booking.id : undefined,
  )
}

/**
 * Story 12.1 AC1/AC4 and f12.1.1 (AC15): whether `user` may request a venue for `event` - they
 * hold bookings:request, are its assigned coordinator, and it can take a booking. These are the
 * rules `POST /bookings` enforces, so Find a venue, Request this venue and the request step offer
 * a request only when it would be accepted. One copy for all three pages, so a rule change cannot
 * reach one and miss another.
 */
export function canRequestVenueFor(
  event: EventDetail,
  user: CurrentUser | null,
  can: (permission: Permission) => boolean,
): boolean {
  return (
    can(PERMISSIONS.BOOKINGS_REQUEST) &&
    event.assigned_coordinator_id === user?.id &&
    BOOKABLE_EVENT_STATUSES.includes(event.status)
  )
}
