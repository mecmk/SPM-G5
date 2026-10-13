import { api } from './client'
import type { AccessibilityNeed, EquipmentLine, EventStatus } from './events'
import type { Venue } from './venues'

/** Values of `SafetyQueueStatus` (backend/app/safety/service.py): the queue's tabs. PENDING awaits
 * the check; ACCEPTED and DECLINED no longer do, by their latest review's outcome. */
export type SafetyQueueStatus = 'PENDING' | 'ACCEPTED' | 'DECLINED'

/** Mirrors `SafetyQueueEntry`: story 21.1 AC2, one event in the safety queue. */
export interface SafetyQueueEntry {
  id: string
  name: string
  starts_at: string
  ends_at: string
  expected_attendance: number
  venue_names: string[]
  status: EventStatus
  /** The tab the event belongs to. */
  safety_status: SafetyQueueStatus
}

/** Mirrors `SafetyVenueOut`: story 21.1 AC3, one approved venue with its full record (story 8.2).
 * AC4: `over_capacity` when the event expects more people than the venue holds. */
export interface SafetyVenue {
  venue: Venue
  layout: string | null
  over_capacity: boolean
}

/** Mirrors `SafetyReviewOut`: story 21.1 AC3, one previous review of the event. */
export interface SafetyReview {
  id: string
  reviewed_at: string
  reviewed_by_name: string
  outcome: SafetyReviewOutcome
  notes: string | null
}

/** Values of `outcome` on `event_safety_reviews`. */
export type SafetyReviewOutcome = 'APPROVED' | 'CHANGES_REQUESTED'

/** The facts a safety review is judged on, the keys of `safety_facts` in
 * backend/app/safety/service.py. */
export type SafetyFact =
  | 'description'
  | 'expected_attendance'
  | 'starts_at'
  | 'ends_at'
  | 'venues'
  | 'accessibility'
  | 'equipment'

/** Mirrors `FactChangeOut`: story 21.1 AC5, one fact as the last review saw it and as it is now.
 * `before` and `after` are the fact's raw JSON, shaped as `safety_facts` writes it. */
export interface FactChange {
  fact: SafetyFact
  before: unknown
  after: unknown
}

/** Mirrors `SafetyCheckDetail`: story 21.1 AC3-AC5, everything about an event that affects its
 * safety. Nulls are passed through for the page to show as not recorded (AC5). */
export interface SafetyCheckDetail {
  id: string
  name: string
  description: string | null
  starts_at: string
  ends_at: string
  expected_attendance: number
  status: EventStatus
  venues: SafetyVenue[]
  accessibility_notes: string | null
  accessibility_needs: AccessibilityNeed[]
  equipment: EquipmentLine[]
  changes_since_last_review: FactChange[]
  previous_reviews: SafetyReview[]
}

/** Story 21.1 AC2: the events in one tab, or in every tab when `status` is null, oldest first. */
export function listSafetyChecks(status: SafetyQueueStatus | null): Promise<SafetyQueueEntry[]> {
  if (status === null) return api<SafetyQueueEntry[]>('/safety-checks')
  return api<SafetyQueueEntry[]>(`/safety-checks?${new URLSearchParams({ status })}`)
}

/** Story 21.1 AC3: one event's safety details, while it awaits the check or once reviewed. */
export function getSafetyCheck(eventId: string): Promise<SafetyCheckDetail> {
  return api<SafetyCheckDetail>(`/safety-checks/${eventId}`, { errorCodes: { 404: 'NOT_FOUND' } })
}
