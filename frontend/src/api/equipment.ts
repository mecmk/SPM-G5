import { api, ApiError } from './client'
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
 * item's type, quantity and notes, and who sent it and when (`null` when never recorded). AC2:
 * `available` for the event's period, not counting the event's own hold, and `shortfall`. Story
 * 16.1 AC2/AC3: who decided it and when, and the reason for declining - each `null` until it is
 * decided, and for requests decided before those were recorded.
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
  submitted_at: string | null
  status: EquipmentQueueStatus
  available: number
  shortfall: number
  decided_by_name: string | null
  decided_at: string | null
  decision_reason: string | null
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

/** Story 16.1: what Technical Support may decide. Mirrors `EquipmentDecisionOutcome`. */
export type EquipmentDecisionOutcome = 'ACCEPTED' | 'DECLINED'

/** Mirrors `EquipmentDecisionIn`: story 16.1, a decision. AC4: a decline carries a reason, and an
 * accept carries none. */
export type EquipmentDecision = { outcome: 'ACCEPTED' } | { outcome: 'DECLINED'; reason: string }

/** Story 16.1 AC6: the figures an accept refused for a shortfall carries beside its sentence. */
export interface EquipmentShortfall {
  available: number
  shortfall: number
}

/** The figures of an accept refused for a shortfall (story 16.1 AC6), or `null` for any other
 * failure. */
export function shortfallOf(error: unknown): EquipmentShortfall | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const { detail } = error
  if (!detail || typeof detail !== 'object') return null
  if (!('available' in detail) || !('shortfall' in detail)) return null
  const { available, shortfall } = detail
  if (typeof available !== 'number' || typeof shortfall !== 'number') return null
  return { available, shortfall }
}

/** Story 16.1 AC1/AC2: accept a pending request, or decline it with a reason; returns the request
 * as the queue shows it. 409 (`EQUIPMENT_DECISION_REFUSED`) when it is no longer pending, its
 * event will not go ahead, or the units are no longer there - each with the backend's sentence. */
export function decideEquipmentRequest(
  entry: EquipmentQueueEntry,
  decision: EquipmentDecision,
): Promise<EquipmentQueueEntry> {
  const isAccepted = decision.outcome === 'ACCEPTED'
  return api<EquipmentQueueEntry>(`/equipment-requests/${entry.id}/decision`, {
    method: 'POST',
    body: decision,
    errorCodes: { 404: 'NOT_FOUND', 409: 'EQUIPMENT_DECISION_REFUSED', 422: 'EQUIPMENT_INVALID' },
    notify: {
      title: isAccepted ? 'Equipment request accepted' : 'Equipment request declined',
      message: `${entry.equipment_type_name} ×${entry.quantity} for ${entry.event_name} was ${
        isAccepted ? 'accepted and reserved' : 'declined'
      }.`,
      importance: 'important',
    },
  })
}

/** Story 16.1: one request as the queue shows it, for its own page. 404 once the queue would no
 * longer list it. */
export function getEquipmentRequest(itemId: string): Promise<EquipmentQueueEntry> {
  return api<EquipmentQueueEntry>(`/equipment-requests/${itemId}`, {
    errorCodes: { 404: 'NOT_FOUND' },
  })
}
