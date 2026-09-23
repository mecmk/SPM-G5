import type { EventStatus } from '../api/events'

/**
 * Story 6.1 - which of the 10 backend statuses get a distinct, prominent presence in the UI.
 * Team decision, 22 Sep 2026: SUBMITTED, APPROVED and CONFIRMED are transitory - the workflow
 * advances through them immediately, so a user essentially never sees an event sitting in one.
 * They still render (never a blank badge), just with the same plain weight as DRAFT rather than
 * a colour or tab of their own. The other seven are visible: each gets its own label, colour and
 * tab.
 */
export const VISIBLE_EVENT_STATUSES = [
  'DRAFT',
  'UNDER_REVIEW',
  'CLARIFICATION_REQUESTED',
  'PLANNING',
  'COMPLETED',
  'CANCELLED',
  'REJECTED',
] as const satisfies readonly EventStatus[]

export const EVENT_STATUS_LABELS: Record<EventStatus, string> = {
  DRAFT: 'Draft',
  SUBMITTED: 'Submitted',
  UNDER_REVIEW: 'Under review',
  CLARIFICATION_REQUESTED: 'Clarification requested',
  APPROVED: 'Approved',
  PLANNING: 'Planning',
  CONFIRMED: 'Confirmed',
  COMPLETED: 'Completed',
  CANCELLED: 'Cancelled',
  REJECTED: 'Rejected',
}

/**
 * The status `StatusBadge` actually keys its CSS class off, so the shared `.badge-<status>`
 * classes never have to be repainted for events. Several literal status strings mean something
 * different, with their own colour, in another domain (a venue booking's own APPROVED and
 * CANCELLED render via the same generic StatusBadge - see bookings/*.tsx), so an event borrows a
 * safe, unshared class instead of repainting a shared one:
 * - the three transitory statuses borrow DRAFT's muted class outright ("same visual weight as
 *   DRAFT" - team decision, 22 Sep 2026);
 * - CLARIFICATION_REQUESTED and COMPLETED are event-only literals, so they can be repainted in
 *   App.css directly without touching another domain;
 * - CANCELLED is not (a venue booking can be CANCELLED too), so events get their own
 *   `EVENT_CANCELLED` class instead of repainting the shared one.
 */
const BADGE_STATUS: Record<EventStatus, string> = {
  DRAFT: 'DRAFT',
  SUBMITTED: 'DRAFT',
  UNDER_REVIEW: 'UNDER_REVIEW',
  CLARIFICATION_REQUESTED: 'CLARIFICATION_REQUESTED',
  APPROVED: 'DRAFT',
  PLANNING: 'PLANNING',
  CONFIRMED: 'DRAFT',
  COMPLETED: 'COMPLETED',
  CANCELLED: 'EVENT_CANCELLED',
  REJECTED: 'REJECTED',
}

export function eventBadgeStatus(status: EventStatus): string {
  return BADGE_STATUS[status]
}

export type EventStatusTabKey = 'ALL' | (typeof VISIBLE_EVENT_STATUSES)[number]

/**
 * Which tab an event's raw status falls under. A transitory status groups with the visible
 * status it leads into - SUBMITTED with UNDER_REVIEW (matching the review queue's own former
 * "awaiting decision" grouping), APPROVED and CONFIRMED with PLANNING - so a request is never
 * simply missing from every specific tab while it briefly sits in one of them. This is separate
 * from the badge colour: a SUBMITTED event shows the muted badge but still lives under the
 * Under Review tab.
 */
const TAB_OF_STATUS: Record<EventStatus, EventStatusTabKey> = {
  DRAFT: 'DRAFT',
  SUBMITTED: 'UNDER_REVIEW',
  UNDER_REVIEW: 'UNDER_REVIEW',
  CLARIFICATION_REQUESTED: 'CLARIFICATION_REQUESTED',
  APPROVED: 'PLANNING',
  PLANNING: 'PLANNING',
  CONFIRMED: 'PLANNING',
  COMPLETED: 'COMPLETED',
  CANCELLED: 'CANCELLED',
  REJECTED: 'REJECTED',
}

export function eventStatusTab(status: EventStatus): EventStatusTabKey {
  return TAB_OF_STATUS[status]
}

/** Story 6.1: the tab strip both the organiser's and the coordinator's event lists share. */
export const EVENT_STATUS_TABS: { key: EventStatusTabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'DRAFT', label: 'Draft' },
  { key: 'UNDER_REVIEW', label: 'Under Review' },
  { key: 'CLARIFICATION_REQUESTED', label: 'Clarification Requested' },
  { key: 'PLANNING', label: 'Planning' },
  { key: 'COMPLETED', label: 'Completed' },
  { key: 'CANCELLED', label: 'Cancelled' },
  { key: 'REJECTED', label: 'Rejected' },
]
