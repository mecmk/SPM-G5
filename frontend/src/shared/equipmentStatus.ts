import type { EquipmentItemStatus } from '../api/events'
import { formatDateTime } from './format'

/** Story 15.1 AC1: how each item status reads on the event page, and story 19.3 in a change
 *  request's impact. Story 17.1 AC1/AC4: an accepted item is reserved, and one cancelled with its
 *  event (6.2) or removed by an approved change (19.2) is released. Story 17.2 AC3: one the
 *  coordinator withdrew says so. */
export const EQUIPMENT_STATUS_LABELS: Record<EquipmentItemStatus, string> = {
  REQUESTED: 'Not yet sent',
  PENDING: 'Pending',
  ACCEPTED: 'Accepted (reserved)',
  DECLINED: 'Declined',
  UNAVAILABLE: 'Unavailable',
  CANCELLED: 'Released',
  WITHDRAWN: 'Withdrawn',
}

/** Story 19.2 AC5, 17.2 AC3: an item kept only for Technical Support's record - cancelled after it
 *  was sent, or withdrawn by the coordinator - and no longer the event's. Mirrors the backend's
 *  `KEPT_FOR_RECORD` (backend/app/events/service.py). */
export const KEPT_FOR_RECORD_STATUSES: readonly EquipmentItemStatus[] = ['CANCELLED', 'WITHDRAWN']

/** Story 17.2 AC3/AC4: when an item was withdrawn and by whom, as the event page and Technical
 *  Support's queue both show it. */
export function withdrawnWhenAndBy(withdrawnAt: string, withdrawnByName: string | null): string {
  return withdrawnByName === null
    ? formatDateTime(withdrawnAt)
    : `${formatDateTime(withdrawnAt)} by ${withdrawnByName}`
}

/** Story 16.2 AC4: the mark on an event's item that units out of service leave short, as its
 *  coordinator reads it on the event's page. */
export function describeItemShort(unitsShort: number, quantity: number): string {
  return `Short: ${unitsShort} of ${quantity} out of service`
}
