import type { CurrentUser } from '../api/auth'
import type { EventDetail } from '../api/events'
import { PERMISSIONS, type Permission } from '../auth/permissions'
import { BOOKABLE_EVENT_STATUSES } from './eventStatus'

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
