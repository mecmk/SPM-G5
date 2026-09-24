import type { EventStatus } from '../api/events'

/**
 * Story 6.1 (revised, bug b6.1.1): the 8 backend statuses, each with its own label, colour and
 * tab. SUBMITTED, APPROVED and the muted/collapsed treatment they and CONFIRMED once had are
 * gone - migration 002 retired SUBMITTED and APPROVED outright, and the team decided CONFIRMED
 * is a fully normal status rather than a transitory one.
 */
export const VISIBLE_EVENT_STATUSES = [
  'DRAFT',
  'UNDER_REVIEW',
  'CLARIFICATION_REQUESTED',
  'PLANNING',
  'CONFIRMED',
  'COMPLETED',
  'CANCELLED',
  'REJECTED',
] as const satisfies readonly EventStatus[]

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

/** Every status is its own tab now - there is no transitory status left to group into another. */
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
