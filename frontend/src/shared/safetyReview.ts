import type { EventStatus } from '../api/events'
import type { SafetyArrangement } from '../api/safety'

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
