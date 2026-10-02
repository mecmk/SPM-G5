import type { CurrentUser } from '../api/auth'
import type { EventDetail, RequiredFacility, VenueRequirement } from '../api/events'
import { PERMISSIONS, type Permission } from '../auth/permissions'
import { BOOKABLE_EVENT_STATUSES } from './eventStatus'

/**
 * Story 2.7 / 12.1 AC2: the venue requirement a booking request is for - the event's first, as
 * the backend's `create_booking_request` copies it - until story 12.5 lets a request name its
 * requirement. Null when the event lists none.
 */
export function firstVenueRequirement(event: EventDetail): VenueRequirement | null {
  return event.venue_requirements[0] ?? null
}

/** What a booking request for `event` asks the venue for. */
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
 * Story 2.7 / 12.1 AC2: the period, number of people, layout and facilities a booking request
 * carries - the first venue requirement's, each falling back to the event's own when it has none
 * - exactly as `create_booking_request` writes them. One copy for Find a venue and the request
 * step, so neither can drift from what the backend books.
 */
export function venueRequestTermsFor(event: EventDetail): VenueRequestTerms {
  const requirement = firstVenueRequirement(event)
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
 * Story 12.1 AC1/AC4 and f12.1.1 (AC15): whether `user` may request a venue for `event` - they
 * hold bookings:request, are its assigned coordinator, and it can take a booking. These are the
 * rules `POST /bookings` enforces, so Find a venue, Request this venue and the request step offer
 * a request only when it would be accepted. One copy for all three pages, so a rule change cannot
 * reach one and miss another (review of PR #67).
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
