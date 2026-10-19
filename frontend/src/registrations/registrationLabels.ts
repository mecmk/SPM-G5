import { formatDateTime } from '../shared/format'

/** A registration badge: the status that picks its colour (App.css's `badge-<status>`) and its
 *  label. */
export interface RegistrationBadge {
  status: string
  label: string
}

/** Stories 18.1 AC1 and 18.2 AC1: an attendee's active registration, as Upcoming events and My
 *  registrations both show it. */
export const REGISTERED_BADGE: RegistrationBadge = { status: 'registered', label: 'Registered' }

/** Stories 18.1 AC1 and 18.2 AC1: when the attendee registered, as both pages say it. */
export function describeRegisteredAt(registeredAt: string): string {
  return `You registered on ${formatDateTime(registeredAt)}`
}
