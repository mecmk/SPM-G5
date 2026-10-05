import type { EventStatus } from '../api/events'

/** Story 7.2 AC3: routine editing (and the internal-notes view) closes at these statuses. */
export const TERMINAL_STATUSES: readonly EventStatus[] = ['COMPLETED', 'CANCELLED', 'REJECTED']

/** Stories 4.4 AC1 / 4.5 AC1 (bug b6.1.1's narrower reject rule has been reversed): both
 *  approving and rejecting are allowed only while a request awaits a decision, mirroring the
 *  backend's `_AWAITING_DECISION_STATUSES` (backend/app/events/service.py). */
export const AWAITING_DECISION_STATUSES: readonly EventStatus[] = [
  'UNDER_REVIEW',
  'CLARIFICATION_REQUESTED',
]

/** Story 7.2 AC4: the only status in which the assigned coordinator corrects the organiser's
 *  details, mirroring the backend's `_DETAILS_CORRECTABLE_STATUS`. CLARIFICATION_REQUESTED is
 *  not included: that round-trip belongs to stories 4.2/4.3. */
export const DETAILS_CORRECTABLE_STATUS: EventStatus = 'UNDER_REVIEW'

/** Story 7.2 AC5: approved and still running - the organiser's details are read-only and further
 *  changes go through a change request (19.1). Mirrors `_DETAILS_LOCKED_STATUSES`. */
export const DETAILS_LOCKED_STATUSES: readonly EventStatus[] = ['PLANNING', 'CONFIRMED']
