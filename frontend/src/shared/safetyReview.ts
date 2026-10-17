import type { EventStatus } from '../api/events'
import type { EventSafety, SafetyArrangement } from '../api/safety'

/** Story 21.2 AC4: how a flagged arrangement is named, where the officer picks it and where the
 * coordinator reads it. */
export const ARRANGEMENT_LABELS: Record<SafetyArrangement, string> = {
  VENUE_BOOKINGS: 'Venue bookings',
  EQUIPMENT: 'Equipment',
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
