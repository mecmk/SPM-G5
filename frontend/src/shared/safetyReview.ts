import type { EventStatus } from '../api/events'
import type { EventSafety, ReleasedBooking, SafetyArrangement, SafetyVenue } from '../api/safety'
import { ADDITIONAL_VENUE, formatCalendarDate } from './format'

/** Story 21.2 AC4: how a flagged arrangement is named, where the officer picks it and where the
 * coordinator reads it. */
export const ARRANGEMENT_LABELS: Record<SafetyArrangement, string> = {
  VENUE_BOOKINGS: 'Venue bookings',
  EQUIPMENT: 'Equipment',
}

/** Story 21.3 AC1: the group the officer ticks bookings to release in, and what it says. */
export const RELEASE_BOOKINGS_LEGEND = 'Bookings to release'
export const RELEASE_BOOKINGS_HINT =
  'Recording the decision cancels each booking you tick and frees its venue.'

/** Story 21.3 AC1: a booking the officer may release, as its checkbox names it - its venue, the
 * requirement it is for or "Additional venue", and its date, or both dates when it spans days. */
export function bookingChoiceLabel(booking: SafetyVenue): string {
  const requirement = booking.requirement_name ?? ADDITIONAL_VENUE
  const first = formatCalendarDate(booking.starts_at)
  const last = formatCalendarDate(booking.ends_at)
  const dates = first === last ? first : `${first} – ${last}`
  return `${booking.venue.name} · ${requirement} · ${dates}`
}

/** Story 21.3 AC9: a booking a review round released, as the finding lists it. */
export function releasedLine(booking: ReleasedBooking): string {
  return `Released: ${booking.venue_name} (${booking.requirement_name ?? ADDITIONAL_VENUE})`
}

/** Story 21.2: the statuses in which an event has a safety review to show or request. */
export const SAFETY_REVIEW_STATUSES: readonly EventStatus[] = [
  'PLANNING',
  'AWAITING_SAFETY_CHECK',
  'CONFIRMED',
  'COMPLETED',
  'CANCELLED',
]

/** Story 21.2 AC4: the line on an event page section the latest review says must change. */
export const FLAGGED_BY_SAFETY_REVIEW = 'Flagged by the safety review'

/** Story 21.2 AC4: the arrangements to highlight on the event page - those the latest review
 * flagged, while it asks for changes and the event is back in Planning for them. */
export function flaggedArrangements(safety: EventSafety | null): SafetyArrangement[] {
  const review = safety?.latest_review
  if (safety?.status !== 'PLANNING' || review?.outcome !== 'CHANGES_REQUESTED') return []
  return review.flagged_arrangements
}
