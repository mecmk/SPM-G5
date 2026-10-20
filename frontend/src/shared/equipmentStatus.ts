import type { EquipmentItemStatus } from '../api/events'

/** Story 15.1 AC1: how each item status reads on the event page, and story 19.3 in a change
 *  request's impact. Story 17.1 AC1/AC4: an accepted item is reserved, and one cancelled with its
 *  event (6.2) or removed by an approved change (19.2) is released. */
export const EQUIPMENT_STATUS_LABELS: Record<EquipmentItemStatus, string> = {
  REQUESTED: 'Not yet sent',
  PENDING: 'Pending',
  ACCEPTED: 'Accepted (reserved)',
  DECLINED: 'Declined',
  UNAVAILABLE: 'Unavailable',
  CANCELLED: 'Released',
}
