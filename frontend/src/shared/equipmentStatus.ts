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
  OUT_OF_SERVICE: 'Out of service',
}

/** Story 19.2 AC5, 17.2 AC3: an item kept only for Technical Support's record - cancelled after it
 *  was sent, withdrawn by the coordinator, or closed as out of service (fix f16.2.4) - and no
 *  longer the event's. Mirrors the backend's `KEPT_FOR_RECORD` (backend/app/events/service.py). */
export const KEPT_FOR_RECORD_STATUSES: readonly EquipmentItemStatus[] = [
  'CANCELLED',
  'WITHDRAWN',
  'OUT_OF_SERVICE',
]

/** Story 17.2 AC3, 15.1 AC6 (fix f15.1.1): items a correction leaves alone - those kept only for
 *  the record, and a declined one, which the event page lists as history and which does not count.
 *  Mirrors the backend's `_NOT_CORRECTED` (backend/app/events/service.py). */
export const NOT_CORRECTED_STATUSES: readonly EquipmentItemStatus[] = [
  ...KEPT_FOR_RECORD_STATUSES,
  'DECLINED',
]

/** Fix f17.3.1 (17.3 AC8/AC9): how long equipment stays held. Unlike a venue booking's hold
 *  (12.7), an equipment hold has no expiry; the backend's `_release_holds` callers
 *  (backend/app/equipment/service.py) are what end one. */
export const HOLD_LENGTH_SENTENCE =
  "Equipment is held for the event's dates, with no expiry, until the item is withdrawn or removed, Technical Support declines it, an approved change removes it, the event moves to dates it can't be held for, or the event is cancelled or rejected."

/** The item statuses that hold units for the event (`_held_by_event`'s RESERVED holds): not yet
 *  sent, waiting on Technical Support, or accepted. */
export const HOLDING_STATUSES: readonly EquipmentItemStatus[] = ['REQUESTED', 'PENDING', 'ACCEPTED']

/** Story 17.2 AC3/AC4: when an item was withdrawn and by whom, as the event page and Technical
 *  Support's queue both show it. */
export function withdrawnWhenAndBy(withdrawnAt: string, withdrawnByName: string | null): string {
  return withdrawnByName === null
    ? formatDateTime(withdrawnAt)
    : `${formatDateTime(withdrawnAt)} by ${withdrawnByName}`
}

/** Story 16.2 AC4: the mark on an event's item that units out of service leave short, as its
 *  coordinator reads it on the event's page. Fix f16.2.2 (16.2 AC9): the holds schedule marks
 *  the hold the same way. Fix f16.2.4 (16.2 AC11): it says how many can still be supplied, and
 *  no longer tells anyone to withdraw or remove the item - one short of every unit is closed
 *  instead (AC10), so a short item has some left (but for one left so before that fix). */
export function describeItemShort(unitsShort: number, quantity: number): string {
  return `Short: ${unitsShort} of ${quantity} out of service, so only ${quantity - unitsShort} can be supplied`
}

/** Fix f16.2.4 (16.2 AC10): what an item closed as out of service says on its event's page. */
export const OUT_OF_SERVICE_SENTENCE =
  'Every unit held was taken out of service, so this item was closed and nothing is held for it. Request another type if you still need one.'

/** Fix f16.2.2 (16.2 AC8/AC9): an accepted item left short reads Accepted, not Accepted
 *  (reserved), since its units can't all be supplied. Its status, the decision, stays Accepted:
 *  the mark follows the records (16.2 AC4). */
const ACCEPTED_SHORT_LABEL = 'Accepted'

/** Story 15.1 AC1 with fix f16.2.2: how an item's status reads, given whether it is short. */
export function equipmentStatusLabel(status: EquipmentItemStatus, isShort: boolean): string {
  return status === 'ACCEPTED' && isShort ? ACCEPTED_SHORT_LABEL : EQUIPMENT_STATUS_LABELS[status]
}
