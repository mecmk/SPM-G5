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
