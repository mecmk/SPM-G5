import { ApiError, api } from './client'
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
 * AC4: `over_capacity` when the booking's `people_to_hold` is more than `capacity`, the venue's
 * capacity in the booked layout (its own where the layout has none recorded). */
export interface SafetyVenue {
  venue: Venue
  layout: string | null
  capacity: number
  people_to_hold: number
  over_capacity: boolean
}

/** Values of `SafetyArrangement` (backend/app/safety/models.py): what a finding says must be
 * rebooked (story 21.2 AC4). */
export type SafetyArrangement = 'VENUE_BOOKINGS' | 'EQUIPMENT'

/** Mirrors `SafetyFactorOut`: story 21.2 AC2, a factor the review considers. */
export interface SafetyFactor {
  code: string
  name: string
  description: string | null
}

/** Mirrors `SafetyFindingOut`: story 21.2 AC4, one thing the officer requires changed. */
export interface SafetyFinding {
  factor_code: string
  factor_name: string
  required_change: string
  arrangement: SafetyArrangement | null
}

/** Mirrors `SafetyReviewOut`: story 21.1 AC3, one previous review of the event, with its findings
 * and the arrangements they flag (story 21.2 AC4). */
export interface SafetyReview {
  id: string
  reviewed_at: string
  reviewed_by_name: string
  outcome: SafetyReviewOutcome
  findings: SafetyFinding[]
  flagged_arrangements: SafetyArrangement[]
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
  | 'accessibility_notes'
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
  /** Story 21.2 AC2: the factors the review considers, in order. */
  factors: SafetyFactor[]
  /** Story 21.2 AC20: sent back with the decision, so it is refused if the facts moved since. */
  facts_fingerprint: string
}

/** Mirrors `SafetyFindingIn`: story 21.2 AC4/AC10. */
export interface SafetyFindingInput {
  factor_code: string
  required_change: string
  arrangement: SafetyArrangement | null
}

/** Mirrors `SafetyDecisionIn`: story 21.2 AC2-AC5. Findings only with CHANGES_REQUESTED.
 * AC20: `facts_fingerprint` is the one the page was read with (`SafetyCheckDetail`). */
export interface SafetyDecisionInput {
  outcome: SafetyReviewOutcome
  findings: SafetyFindingInput[]
  facts_fingerprint: string
}

/** Mirrors `EventSafetyOut`: story 21.2 AC4/AC7, the event page's safety summary. The blockers
 * are null unless the viewer is the assigned coordinator (AC18); an empty list offers the action.
 * AC12: `unchanged_warning` is the warning a request would raise, so the page asks first. */
export interface EventSafety {
  event_id: string
  status: EventStatus
  latest_review: SafetyReview | null
  request_blockers: string[] | null
  confirm_blockers: string[] | null
  unchanged_warning: string | null
}

/** Story 21.2 AC9: the longest required change the officer may write, mirroring
 * `MAX_SAFETY_TEXT_LENGTH` in backend/app/safety/schemas.py. */
export const MAX_SAFETY_TEXT_LENGTH = 2000

const SAFETY_ACTION_ERROR_CODES = { 404: 'EVENT_NOT_FOUND', 409: 'SAFETY_REVIEW_CONFLICT' } as const

/** Story 21.1 AC2: the events in one tab, or in every tab when `status` is null, oldest first. */
export function listSafetyChecks(status: SafetyQueueStatus | null): Promise<SafetyQueueEntry[]> {
  if (status === null) return api<SafetyQueueEntry[]>('/safety-checks')
  return api<SafetyQueueEntry[]>(`/safety-checks?${new URLSearchParams({ status })}`)
}

/** Story 21.1 AC3: one event's safety details, while it awaits the check or once reviewed. */
export function getSafetyCheck(eventId: string): Promise<SafetyCheckDetail> {
  return api<SafetyCheckDetail>(`/safety-checks/${eventId}`, { errorCodes: { 404: 'NOT_FOUND' } })
}

/** Story 21.2 AC4/AC7: the latest review and what stops the coordinator acting, for the event
 * page. */
export function getEventSafety(eventId: string): Promise<EventSafety> {
  return api<EventSafety>(`/events/${eventId}/safety-review`, {
    errorCodes: { 404: 'EVENT_NOT_FOUND' },
  })
}

/** Story 21.2 AC1/AC12: send a secured event for the safety check. `acknowledgeUnchanged` sends
 * it although an arrangement the last review flagged is unchanged. */
export function requestSafetyReview(
  eventId: string,
  name: string,
  acknowledgeUnchanged: boolean,
): Promise<EventSafety> {
  return api<EventSafety>(`/safety-checks/${eventId}/request`, {
    method: 'POST',
    body: { acknowledge_unchanged: acknowledgeUnchanged },
    errorCodes: SAFETY_ACTION_ERROR_CODES,
    notify: {
      title: 'Safety review requested',
      message: `"${name}" was sent to the Safety Officer.`,
    },
  })
}

/** Story 21.2 AC12: the arrangements a refused request found unchanged, or null when the refusal
 * was something else. */
export function unchangedArrangementsOf(error: unknown): SafetyArrangement[] | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const { detail } = error
  if (detail && typeof detail === 'object' && 'unchanged_arrangements' in detail) {
    return detail.unchanged_arrangements as SafetyArrangement[]
  }
  return null
}

/** Story 21.2 AC2-AC5: record the officer's decision. */
export function decideSafetyCheck(
  eventId: string,
  name: string,
  decision: SafetyDecisionInput,
): Promise<SafetyCheckDetail> {
  return api<SafetyCheckDetail>(`/safety-checks/${eventId}/decision`, {
    method: 'POST',
    body: decision,
    errorCodes: { 404: 'EVENT_NOT_FOUND', 409: 'SAFETY_DECISION_CONFLICT' },
    notify: {
      title: 'Safety decision recorded',
      message: `Your decision on "${name}" was recorded.`,
      importance: 'important',
    },
  })
}

/** Story 21.2 AC7: confirm a safety-approved event. */
export function confirmEvent(eventId: string, name: string): Promise<EventSafety> {
  return api<EventSafety>(`/events/${eventId}/confirm`, {
    method: 'POST',
    errorCodes: SAFETY_ACTION_ERROR_CODES,
    notify: {
      title: 'Event confirmed',
      message: `"${name}" is confirmed.`,
      importance: 'important',
    },
  })
}
