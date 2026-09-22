import type { EventStatus } from '../api/events'
import { eventBadgeStatus, EVENT_STATUS_LABELS } from '../shared/eventStatus'
import { StatusBadge } from './StatusBadge'

/**
 * Story 6.1 - the one place an event's current status becomes a badge, so every page shows the
 * same status the same way (AC3). Wraps the generic StatusBadge with event-specific colour and
 * label rules rather than passing the raw status straight through.
 */
export function EventStatusBadge({ status }: { status: EventStatus }) {
  return <StatusBadge status={eventBadgeStatus(status)} label={EVENT_STATUS_LABELS[status]} />
}
