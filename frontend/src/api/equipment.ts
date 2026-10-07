import { api } from './client'
import type { EquipmentLine } from './events'

/** Story 15.1 AC5: the longest technical note. Keep in step with the backend's
 * `TECHNICAL_NOTES_MAX_LENGTH` in app/equipment/schemas.py. */
export const TECHNICAL_NOTES_MAX_LENGTH = 1000

/**
 * Mirrors `EventEquipmentAvailabilityOut`: story 15.1 AC3, how many units of one active type an
 * event can have over its period, counting what it already holds.
 */
export interface EquipmentAvailability {
  equipment_type_code: string
  equipment_type_name: string
  available: number
}

/** Mirrors `EquipmentItemIn`: story 15.1 AC1, a new item. */
export interface EquipmentItemInput {
  equipment_type_code: string
  quantity: number
  technical_notes: string | null
}

/** Mirrors `EquipmentItemUpdate`: story 15.1 AC2, a partial edit. Notes left out keep their
 * value; null clears them. */
export interface EquipmentItemChange {
  quantity: number
  technical_notes?: string | null
}

/** The registry codes the equipment writes give their refusals; each arrives with the backend's
 * own sentence. */
const EQUIPMENT_ERRORS = {
  404: 'NOT_FOUND',
  409: 'EQUIPMENT_REFUSED',
  422: 'EQUIPMENT_INVALID',
} as const

/** Story 15.1 AC3: the figures the form shows next to each type, for the event's own period. */
export function fetchEquipmentAvailability(eventId: string): Promise<EquipmentAvailability[]> {
  return api<EquipmentAvailability[]>(`/events/${eventId}/equipment-availability`, {
    errorCodes: { 404: 'EVENT_NOT_FOUND' },
  })
}

/** Story 15.1 AC1/AC2: record an item on the event, held at once and not yet sent. */
export function addEquipmentItem(
  eventId: string,
  item: EquipmentItemInput,
  typeName: string,
): Promise<EquipmentLine> {
  return api<EquipmentLine>(`/events/${eventId}/equipment`, {
    method: 'POST',
    body: item,
    errorCodes: EQUIPMENT_ERRORS,
    notify: {
      title: 'Equipment added',
      message: `${typeName} ×${item.quantity} is held for this event, ready to send.`,
    },
  })
}

/** Story 15.1 AC2: change an item's quantity or notes, adjusting what it holds. */
export function updateEquipmentItem(
  eventId: string,
  itemId: string,
  change: EquipmentItemChange,
  typeName: string,
): Promise<EquipmentLine> {
  return api<EquipmentLine>(`/events/${eventId}/equipment/${itemId}`, {
    method: 'PATCH',
    body: change,
    errorCodes: EQUIPMENT_ERRORS,
    notify: { title: 'Equipment updated', message: `${typeName} was updated.` },
  })
}

/** Story 15.1 AC2: remove an item, releasing what it holds. */
export function removeEquipmentItem(
  eventId: string,
  itemId: string,
  typeName: string,
): Promise<void> {
  return api<void>(`/events/${eventId}/equipment/${itemId}`, {
    method: 'DELETE',
    errorCodes: EQUIPMENT_ERRORS,
    notify: { title: 'Equipment removed', message: `${typeName} was removed from this event.` },
  })
}

/** Story 15.1 AC1: send every item not yet sent to Technical Support; returns the items sent. */
export function submitEquipment(eventId: string): Promise<EquipmentLine[]> {
  return api<EquipmentLine[]>(`/events/${eventId}/equipment-submissions`, {
    method: 'POST',
    errorCodes: EQUIPMENT_ERRORS,
    notify: {
      title: 'Equipment sent',
      message: 'The equipment was sent to Technical Support.',
    },
  })
}

/** Story 15.2 AC3: the statuses Technical Support's queue has a tab for. Mirrors
 * `EquipmentQueueStatus`. */
export type EquipmentQueueStatus = 'PENDING' | 'ACCEPTED' | 'DECLINED'

/**
 * Mirrors `EquipmentQueueEntry`: story 15.2 AC1, a request with its event's name and dates, the
 * item's type, quantity and notes, and who sent it (`null` when that was never recorded). AC2:
 * `available` for the event's period, not counting the event's own hold, and `shortfall`.
 */
export interface EquipmentQueueEntry {
  id: string
  event_id: string
  event_name: string
  starts_at: string
  ends_at: string
  equipment_type_code: string
  equipment_type_name: string
  quantity: number
  technical_notes: string | null
  requested_by_name: string | null
  status: EquipmentQueueStatus
  available: number
  shortfall: number
}

/** Mirrors `EquipmentQueueCounts`: story 15.2 AC3, how many requests each tab holds. */
export interface EquipmentQueueCounts {
  pending: number
  accepted: number
  declined: number
}

/** Mirrors `EquipmentQueue`: story 15.2 AC1-AC3, one tab of the queue and every tab's count. */
export interface EquipmentQueue {
  items: EquipmentQueueEntry[]
  counts: EquipmentQueueCounts
}

/** Story 15.2 AC1-AC3: one tab of Technical Support's queue, soonest event first; `null` is the
 * All tab. */
export function listEquipmentRequests(
  status: EquipmentQueueStatus | null,
): Promise<EquipmentQueue> {
  if (status === null) return api<EquipmentQueue>('/equipment-requests')
  return api<EquipmentQueue>(`/equipment-requests?${new URLSearchParams({ status })}`)
}
