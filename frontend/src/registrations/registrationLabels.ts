import type { RegistrationStanding } from '../api/registrations'
import { eventBadgeStatus } from '../shared/eventStatus'
import { formatDateTime, NONE, NOT_RECORDED } from '../shared/format'

/** A registration badge: the status that picks its colour (App.css's `badge-<status>`) and its
 *  label. */
export interface RegistrationBadge {
  status: string
  label: string
}

/** Stories 18.1 AC1 and 18.2 AC1: an attendee's active registration, as Upcoming events and My
 *  registrations both show it. */
export const REGISTERED_BADGE: RegistrationBadge = { status: 'registered', label: 'Registered' }

/** Stories 18.2 AC1/AC8 and 18.3 AC4: each standing's label, and the badge colour it takes
 *  (App.css), as the attendee and the event's organiser and coordinator both see it. Registered
 *  is 18.1's badge; Event cancelled is a cancelled event's colour, as every event status page
 *  shows it, not a cancelled booking's (shared/eventStatus.ts keeps the two apart). */
export const STANDING_BADGES: Record<RegistrationStanding, RegistrationBadge> = {
  REGISTERED: REGISTERED_BADGE,
  WITHDRAWN: { status: 'withdrawn', label: 'Withdrawn' },
  EVENT_CANCELLED: { status: eventBadgeStatus('CANCELLED'), label: 'Event cancelled' },
}

/** Stories 18.1 AC1 and 18.2 AC1: when the attendee registered, as both pages say it. */
export function describeRegisteredAt(registeredAt: string): string {
  return `You registered on ${formatDateTime(registeredAt)}`
}

/** Story 18.4 AC6: an attendee's dietary requirements as every page shows them - "None" when they
 *  left them blank. */
export function describeDietaryRequirements(dietaryRequirements: string | null): string {
  return dietaryRequirements ?? NONE
}

/** Story 18.4 AC7: an attendee's phone number as every page shows it. It is required (CL-166),
 *  but an attendee who registered before 18.4 and has not been asked since has none yet. */
export function describePhone(phone: string | null): string {
  return phone ?? NOT_RECORDED
}
