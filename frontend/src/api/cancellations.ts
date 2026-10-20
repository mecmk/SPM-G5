import { api } from './client'
import type { EventDetail } from './events'

/** Story 6.2: the refusals cancelling can meet, beyond the client's generic ones. */
const CANCEL_EVENT_ERROR_CODES = {
  404: 'EVENT_NOT_FOUND',
  409: 'EVENT_NOT_CANCELLABLE',
} as const

/**
 * Story 6.2 AC1/AC7: the organiser cancels their own event with a mandatory reason, mirroring
 * `POST /events/{event_id}/cancel` (backend/app/cancellations/router.py). Returns the event, now
 * Cancelled; its bookings, equipment, registrations and pending change requests are released or
 * closed with it. Offered from `CANCELLABLE_STATUSES` (`../shared/eventStatus`).
 */
export function cancelEvent(eventId: string, reason: string, name: string): Promise<EventDetail> {
  return api<EventDetail>(`/events/${eventId}/cancel`, {
    method: 'POST',
    body: { reason },
    errorCodes: CANCEL_EVENT_ERROR_CODES,
    notify: {
      title: 'Event cancelled',
      message: `"${name}" was cancelled.`,
      importance: 'important',
    },
  })
}
