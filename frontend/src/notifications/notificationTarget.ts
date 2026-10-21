import type { NotificationTarget } from '../api/notifications'
import {
  CHANGE_REQUEST_QUEUE_PATH,
  EQUIPMENT_REQUESTS_PATH,
  EVENTS_UNASSIGNED_PATH,
  MY_REGISTRATIONS_PATH,
  bookingRequestPath,
  eventPath,
  safetyCheckPath,
} from '../routes'
import { TARGET_KINDS } from './notificationText'

/**
 * Story 20.2 AC1: the page a notification's target opens, or null when there is none to open - no
 * target, a kind this build does not know, or a page of one record sent without its id. The server
 * sends a kind and an id and never an address, so every route is named here.
 */
export function routeForTarget(target: NotificationTarget | null): string | null {
  if (target === null) return null
  switch (target.kind) {
    case TARGET_KINDS.EVENT:
      return target.id === null ? null : eventPath(target.id)
    case TARGET_KINDS.BOOKING_REQUEST:
      return target.id === null ? null : bookingRequestPath(target.id)
    case TARGET_KINDS.SAFETY_CHECK:
      return target.id === null ? null : safetyCheckPath(target.id)
    case TARGET_KINDS.EQUIPMENT_REQUESTS:
      return EQUIPMENT_REQUESTS_PATH
    case TARGET_KINDS.REGISTRATIONS:
      return MY_REGISTRATIONS_PATH
    case TARGET_KINDS.UNASSIGNED_EVENTS:
      return EVENTS_UNASSIGNED_PATH
    case TARGET_KINDS.CHANGE_REQUEST_QUEUE:
      return CHANGE_REQUEST_QUEUE_PATH
    default:
      return null
  }
}
