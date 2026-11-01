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

/** Story 15.2 AC3: the statuses Technical Support's queue has a tab for; story 6.2 AC15:
 * Cancelled, read-only, for requests once sent to them. Mirrors `EquipmentQueueStatus`. */
export type EquipmentQueueStatus = 'PENDING' | 'ACCEPTED' | 'DECLINED' | 'CANCELLED'

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
  /** Story 6.2 AC15: null for a cancelled request, which holds nothing. */
  available: number | null
  shortfall: number | null
  decided_by_name: string | null
  decided_at: string | null
  decision_reason: string | null
  /** Story 6.2 AC16: when a cancelled request was cancelled; null otherwise, and for one
   * cancelled before that was recorded. */
  cancelled_at: string | null
}

/** Mirrors `EquipmentQueueCounts`: story 15.2 AC3, how many requests each tab holds. */
export interface EquipmentQueueCounts {
  pending: number
  accepted: number
  declined: number
  /** Story 6.2 AC15. */
  cancelled: number
}

/** Mirrors `EquipmentQueue`: story 15.2 AC1-AC3, one tab of the queue and every tab's count. */
export interface EquipmentQueue {
  items: EquipmentQueueEntry[]
  counts: EquipmentQueueCounts
}

/** Story 13.3 AC3: the orders the equipment queue offers. Mirrors `EquipmentQueueOrder`. */
export type EquipmentQueueOrder =
  'date' | 'date_desc' | 'requested' | 'requested_desc' | 'event_name' | 'equipment_type'

/** One tab of the equipment queue to ask for. */
export interface EquipmentQueueQuery {
  status: EquipmentQueueStatus | null
  /** Story 13.3 AC2: blank for no search. */
  search: string
  order: EquipmentQueueOrder
}

/** Story 15.2 AC1-AC3: one tab of Technical Support's queue; `null` is the All tab. Story 13.3
 * AC1-AC4: searched and ordered, soonest event first unless asked otherwise; a blank search is
 * left out, as the spaces around one are (AC5). */
export function listEquipmentRequests(query: EquipmentQueueQuery): Promise<EquipmentQueue> {
  const params = new URLSearchParams({ order: query.order })
  if (query.status !== null) params.set('status', query.status)
  if (query.search.trim() !== '') params.set('search', query.search.trim())
  return api<EquipmentQueue>(`/equipment-requests?${params}`)
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

// =============================================================================================
// Story 16.2: units of an equipment type out of service
// =============================================================================================

/** Values of `OutOfServiceReason` (backend/app/equipment/schemas.py): story 16.2 AC1. */
export type OutOfServiceReason = 'DAMAGED' | 'MAINTENANCE' | 'LOST' | 'OTHER'

/** Story 16.2 AC1: the most characters of a note, as the backend's
 *  OUT_OF_SERVICE_NOTES_MAX_LENGTH. */
export const OUT_OF_SERVICE_NOTES_MAX_LENGTH = 1000

/** Mirrors `EquipmentCatalogueEntryOut`: story 16.2 AC2, one type in the catalogue. */
export interface EquipmentCatalogueEntry {
  id: string
  code: string
  name: string
  total_quantity: number
  out_of_service_now: number
}

/** Mirrors `OutOfServiceOut`: story 16.2 AC2, one record. `ends_at` null: out until ended. */
export interface OutOfServiceRecord {
  id: string
  quantity: number
  reason: OutOfServiceReason
  notes: string | null
  starts_at: string
  ends_at: string | null
}

/** Mirrors `EquipmentTypePageOut`: story 16.2 AC2, one type's page and its current records,
 *  soonest first. */
export interface EquipmentTypePage extends EquipmentCatalogueEntry {
  description: string | null
  storage_location: string | null
  records: OutOfServiceRecord[]
}

/** Mirrors `OutOfServiceIn`: story 16.2 AC1, a record as Technical Support sends it. */
export interface OutOfServiceInput {
  quantity: number
  reason: OutOfServiceReason
  notes: string | null
  starts_at: string
  ends_at: string | null
}

/** Mirrors `ShortHoldOut`: story 16.2 AC4/AC5, a hold a record leaves short. */
export interface ShortHold {
  event_id: string
  event_name: string
  coordinator_name: string | null
  units_held: number
  units_short: number
  starts_at: string
  ends_at: string
}

/** Mirrors `EquipmentShortageOut`: story 16.2 AC4, an event's item left short. */
export interface EquipmentShortage {
  item_id: string
  units_short: number
}

const OUT_OF_SERVICE_ERRORS = {
  404: 'OUT_OF_SERVICE_NOT_FOUND',
  409: 'OUT_OF_SERVICE_REFUSED',
} as const

function outOfServicePath(typeId: string): string {
  return `/equipment-types/${encodeURIComponent(typeId)}/out-of-service`
}

/** Story 16.2 AC2: every active type, with its stock and the units out of service now. */
export function listEquipmentCatalogue(): Promise<EquipmentCatalogueEntry[]> {
  return api<EquipmentCatalogueEntry[]>('/equipment-types')
}

/** Story 16.2 AC2: one type's page. */
export function fetchEquipmentType(typeId: string): Promise<EquipmentTypePage> {
  return api<EquipmentTypePage>(`/equipment-types/${encodeURIComponent(typeId)}`, {
    errorCodes: { 404: 'EQUIPMENT_TYPE_NOT_FOUND' },
  })
}

/** Story 16.2 AC5: the holds `input` would leave short - with `recordId`, as an edit of that
 *  record - refused as saving it would be (AC3). A read, so it lands in no notice. */
export function checkOutOfService(
  typeId: string,
  input: Pick<OutOfServiceInput, 'quantity' | 'starts_at' | 'ends_at'>,
  recordId: string | null,
): Promise<ShortHold[]> {
  const params = new URLSearchParams({
    quantity: String(input.quantity),
    starts_at: input.starts_at,
  })
  if (input.ends_at !== null) params.set('ends_at', input.ends_at)
  if (recordId !== null) params.set('record_id', recordId)
  return api<{ short_holds: ShortHold[] }>(`${outOfServicePath(typeId)}/check?${params}`, {
    errorCodes: OUT_OF_SERVICE_ERRORS,
  }).then((check) => check.short_holds)
}

/** Story 16.2 AC1: record units of `typeName` out of service. */
export function addOutOfService(
  typeId: string,
  typeName: string,
  input: OutOfServiceInput,
): Promise<OutOfServiceRecord> {
  return api<OutOfServiceRecord>(outOfServicePath(typeId), {
    method: 'POST',
    body: input,
    errorCodes: OUT_OF_SERVICE_ERRORS,
    notify: {
      title: 'Out of service',
      message: `${input.quantity} × ${typeName} recorded out of service.`,
    },
  })
}

/** Story 16.2 AC2: change a record - only the fields in `change` are sent. */
export function editOutOfService(
  typeId: string,
  typeName: string,
  recordId: string,
  change: Partial<OutOfServiceInput>,
): Promise<OutOfServiceRecord> {
  return api<OutOfServiceRecord>(`${outOfServicePath(typeId)}/${encodeURIComponent(recordId)}`, {
    method: 'PATCH',
    body: change,
    errorCodes: OUT_OF_SERVICE_ERRORS,
    notify: {
      title: 'Record changed',
      message: `A ${typeName} out-of-service record was changed.`,
    },
  })
}

/** Story 16.2 AC2: end a record in force now. */
export function endOutOfServiceNow(
  typeId: string,
  typeName: string,
  recordId: string,
): Promise<OutOfServiceRecord> {
  return api<OutOfServiceRecord>(`${outOfServicePath(typeId)}/${encodeURIComponent(recordId)}`, {
    method: 'PATCH',
    body: { end_now: true },
    errorCodes: OUT_OF_SERVICE_ERRORS,
    notify: { title: 'Record ended', message: `${typeName} units are back in service from now.` },
  })
}

/** Story 16.2 AC2: remove a record not yet started. */
export function removeOutOfService(
  typeId: string,
  typeName: string,
  recordId: string,
): Promise<void> {
  return api<void>(`${outOfServicePath(typeId)}/${encodeURIComponent(recordId)}`, {
    method: 'DELETE',
    errorCodes: OUT_OF_SERVICE_ERRORS,
    notify: {
      title: 'Record removed',
      message: `A ${typeName} out-of-service record was removed.`,
    },
  })
}

/** Story 16.2 AC4: the event's items that units out of service leave short. */
export function listEventShortages(eventId: string): Promise<EquipmentShortage[]> {
  return api<EquipmentShortage[]>(`/events/${encodeURIComponent(eventId)}/equipment-shortages`)
}
