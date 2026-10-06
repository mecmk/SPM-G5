import type { EventStatus } from '../api/events'

/** Story 6.1: the 8 backend statuses, each with its own label, colour and tab. */
const VISIBLE_EVENT_STATUSES = [
  'DRAFT',
  'UNDER_REVIEW',
  'CLARIFICATION_REQUESTED',
  'PLANNING',
  'CONFIRMED',
  'COMPLETED',
  'CANCELLED',
  'REJECTED',
] as const satisfies readonly EventStatus[]

/**
 * Story 12.1 AC1: the statuses a venue booking can be requested from, mirroring
 * `_BOOKABLE_EVENT_STATUSES` in backend/app/bookings/service.py. f12.1.1 offers Find a venue,
 * Request this venue and the request step only on these (`canRequestVenueFor` in
 * `./venueRequest.ts`), so no page offers what `POST /bookings` would refuse.
 */
export const BOOKABLE_EVENT_STATUSES: readonly EventStatus[] = ['PLANNING', 'CONFIRMED']

/** Story 7.2 AC3: routine editing (and the internal-notes view) closes at these statuses. */
export const TERMINAL_STATUSES: readonly EventStatus[] = ['COMPLETED', 'CANCELLED', 'REJECTED']

/**
 * Stories 4.4 AC1 / 4.5 AC1: both approving and rejecting are allowed only while a request
 * awaits a decision, mirroring the backend's `_AWAITING_DECISION_STATUSES`
 * (backend/app/events/service.py).
 */
export const AWAITING_DECISION_STATUSES: readonly EventStatus[] = [
  'UNDER_REVIEW',
  'CLARIFICATION_REQUESTED',
]

/**
 * Story 7.2 AC4: the statuses in which the assigned coordinator corrects the organiser's details,
 * mirroring the backend's `_DETAILS_CORRECTABLE_STATUSES`. Clarification Requested was added to
 * AC4 in the backlog's Change Log.
 */
export const DETAILS_CORRECTABLE_STATUSES: readonly EventStatus[] = [
  'UNDER_REVIEW',
  'CLARIFICATION_REQUESTED',
]

/**
 * Story 7.2 AC5: approved and still running - the organiser's details are read-only and further
 * changes go through a change request (19.1). Mirrors `_DETAILS_LOCKED_STATUSES`.
 */
export const DETAILS_LOCKED_STATUSES: readonly EventStatus[] = ['PLANNING', 'CONFIRMED']

/**
 * Story 7.2 AC5: why the organiser's details cannot be edited once the event is approved, said to
 * the assigned coordinator on the event details page and on the coordinator's edit page.
 */
export const DETAILS_LOCKED_HINT =
  'Event details can no longer be edited directly after approval. Further changes must go through the change request process.'

export const EVENT_STATUS_LABELS: Record<EventStatus, string> = {
  DRAFT: 'Draft',
  UNDER_REVIEW: 'Under review',
  CLARIFICATION_REQUESTED: 'Clarification requested',
  PLANNING: 'Planning',
  CONFIRMED: 'Confirmed',
  COMPLETED: 'Completed',
  CANCELLED: 'Cancelled',
  REJECTED: 'Rejected',
}

/**
 * The status `StatusBadge` actually keys its CSS class off, so the shared `.badge-<status>`
 * classes never have to be repainted for events. CANCELLED is not event-only (a venue booking
 * can be CANCELLED too, with its own colour), so events get their own `EVENT_CANCELLED` class
 * instead of repainting the shared one. Every other event status is a literal no other domain
 * uses, so it can be repainted in App.css directly.
 */
const BADGE_STATUS: Record<EventStatus, string> = {
  DRAFT: 'DRAFT',
  UNDER_REVIEW: 'UNDER_REVIEW',
  CLARIFICATION_REQUESTED: 'CLARIFICATION_REQUESTED',
  PLANNING: 'PLANNING',
  CONFIRMED: 'CONFIRMED',
  COMPLETED: 'COMPLETED',
  CANCELLED: 'EVENT_CANCELLED',
  REJECTED: 'REJECTED',
}

export function eventBadgeStatus(status: EventStatus): string {
  return BADGE_STATUS[status]
}

export type EventStatusTabKey = 'ALL' | (typeof VISIBLE_EVENT_STATUSES)[number]

/** Every status is its own tab: none is grouped into another. */
export function eventStatusTab(status: EventStatus): EventStatusTabKey {
  return status
}

/** Story 6.1: the tab strip both the organiser's and the coordinator's event lists share. */
export const EVENT_STATUS_TABS: { key: EventStatusTabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'DRAFT', label: 'Draft' },
  { key: 'UNDER_REVIEW', label: 'Under Review' },
  { key: 'CLARIFICATION_REQUESTED', label: 'Clarification Requested' },
  { key: 'PLANNING', label: 'Planning' },
  { key: 'CONFIRMED', label: 'Confirmed' },
  { key: 'COMPLETED', label: 'Completed' },
  { key: 'CANCELLED', label: 'Cancelled' },
  { key: 'REJECTED', label: 'Rejected' },
]
