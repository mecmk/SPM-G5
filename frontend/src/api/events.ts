import { api } from './client'

/** Mirrors `ReviewQueueSort` in backend/app/events/schemas.py. */
export type ReviewQueueSort = 'submitted_at' | 'starts_at'
export type ReviewQueueStatus = 'UNDER_REVIEW' | 'CLARIFICATION_REQUESTED'

/** Mirrors `ReviewQueueEntry`: one row of the coordinator's review queue. */
export interface ReviewQueueEntry {
  id: string
  name: string
  organiser_name: string
  starts_at: string
  ends_at: string
  submitted_at: string | null
  status: ReviewQueueStatus
  cover_image_url: string | null
}

export interface ReviewQueueQuery {
  sort: ReviewQueueSort
  coordinatorId: string | null
}

/** Story 4.1 AC1/AC3: the requests waiting for a decision, in the chosen order. */
export function listReviewQueue(query: ReviewQueueQuery): Promise<ReviewQueueEntry[]> {
  const params = new URLSearchParams({ sort: query.sort })
  if (query.coordinatorId !== null) params.set('coordinator_id', query.coordinatorId)
  return api<ReviewQueueEntry[]>(`/events/review-queue?${params.toString()}`)
}

/**
 * Mirrors `EventStatus` in backend/app/events/models.py. SUBMITTED and APPROVED were retired by
 * migration 002 (bug b6.1.1): submitting a draft now goes straight to UNDER_REVIEW, and approving
 * a request now goes straight to PLANNING, with no separate in-between status.
 */
export type EventStatus =
  | 'DRAFT'
  | 'UNDER_REVIEW'
  | 'CLARIFICATION_REQUESTED'
  | 'PLANNING'
  | 'CONFIRMED'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'REJECTED'

/** Mirrors `MyEventEntry`: one row of the organiser's own list. A draft may have no dates. */
export interface MyEventEntry {
  id: string
  name: string
  starts_at: string | null
  ends_at: string | null
  status: EventStatus
  cover_image_url: string | null
}

/** Mirrors `MyEventList`: one page of the organiser's requests, and how many they own in all. */
export interface MyEventList {
  items: MyEventEntry[]
  total: number
}

/** Mirrors `AssignedEventEntry`: one row of the coordinator's assigned events, any status. */
export interface AssignedEventEntry {
  id: string
  name: string
  organiser_name: string
  starts_at: string
  ends_at: string
  submitted_at: string | null
  status: EventStatus
  cover_image_url: string | null
}

/** Mirrors `AssignedEventList`: one page of the coordinator's assigned events, and the total. */
export interface AssignedEventList {
  items: AssignedEventEntry[]
  total: number
}

/**
 * Story 6.1 AC1-AC3: every event assigned to the signed-in coordinator, in any status - unlike
 * `listReviewQueue`, which only ever returns the three awaiting-decision statuses.
 */
export function listAssignedEvents(offset: number): Promise<AssignedEventList> {
  return api<AssignedEventList>(`/events/assigned-to-me?offset=${offset}`)
}

/**
 * Story 2.6 AC1-AC6, AC9: the signed-in organiser's own requests, most recently updated first,
 * from the `offset`th on. The page size is the backend's, so a page is as many as it sends.
 */
export function listMyEvents(offset: number): Promise<MyEventList> {
  return api<MyEventList>(`/events/mine?offset=${offset}`)
}

/** Mirrors `ReferenceItemOut`: one option of a pick-list on the request form. */
export interface EventReferenceItem {
  code: string
  name: string
  description: string | null
}

/** Mirrors `EventReferenceData`: the pick-lists for the request form (story 2.1 AC4-AC6). */
export interface EventReferenceData {
  layouts: EventReferenceItem[]
  facilities: EventReferenceItem[]
  accessibility_features: EventReferenceItem[]
  equipment_types: EventReferenceItem[]
}

/** Mirrors `RequiredFacilityOut`. */
export interface RequiredFacility {
  code: string
  name: string
  quantity: number | null
  notes: string | null
}

/** Mirrors `AccessibilityNeedOut`. */
export interface AccessibilityNeed {
  code: string
  name: string
  notes: string | null
}

/** Mirrors `EquipmentLineOut`: one equipment item on a request. */
export interface EquipmentLine {
  id: string
  equipment_type_code: string
  equipment_type_name: string
  quantity: number
  technical_notes: string | null
  status: string
}

/**
 * Mirrors `EventDetailOut`: everything recorded on a request. `accessibility_none_required` true
 * means the organiser said no needs; false with no needs and no notes means not yet specified
 * (story 2.1 AC5). `venue_none_required` works the same way for venue requirements (AC4).
 * `decided_by_name`/`decided_at`/`decision_reason` are all `null` until the request has been
 * decided (story 4.6 AC1).
 */
export interface EventDetail {
  id: string
  name: string
  purpose: string | null
  description: string | null
  cover_image_url: string | null
  contact_name: string | null
  contact_email: string | null
  contact_phone: string | null
  /** Coordinator-only (story 7.2): null for a viewer without events:review. */
  internal_notes: string | null
  starts_at: string | null
  ends_at: string | null
  expected_attendance: number | null
  status: EventStatus
  organiser_id: string
  organiser_name: string
  assigned_coordinator_id: string | null
  assigned_coordinator_name: string | null
  submitted_at: string | null
  required_layout_code: string | null
  required_layout_name: string | null
  required_facilities: RequiredFacility[]
  venue_requirement_notes: string | null
  venue_none_required: boolean
  accessibility_none_required: boolean
  accessibility_needs: AccessibilityNeed[]
  accessibility_notes: string | null
  equipment: EquipmentLine[]
  decided_by_name: string | null
  decided_at: string | null
  decision_reason: string | null
  created_at: string
  updated_at: string
}

/** Mirrors `EventEquipmentIn`. An `id` keeps and edits an existing line; without one it is new. */
export interface EquipmentInput {
  id: string | null
  equipment_type_code: string
  quantity: number
  technical_notes: string | null
}

/**
 * Mirrors `EventCreate` / `EventUpdate`. The form always sends every field, so on an edit each
 * list replaces the stored one and a null clears an optional field.
 */
export interface EventInput {
  name: string
  purpose: string | null
  description: string | null
  starts_at: string | null
  ends_at: string | null
  expected_attendance: number | null
  required_layout_code: string | null
  venue_requirement_notes: string | null
  required_facilities: { code: string; quantity: number | null; notes: string | null }[]
  venue_none_required: boolean
  accessibility_none_required: boolean
  accessibility_needs: { code: string; notes: string | null }[]
  accessibility_notes: string | null
  equipment: EquipmentInput[]
}

const EVENT_ERROR_CODES = { 404: 'EVENT_NOT_FOUND', 409: 'EVENT_ALREADY_SUBMITTED' } as const

/** Story 2.1 AC4-AC6: the pick-lists for the request form. */
export function fetchEventReferenceData(): Promise<EventReferenceData> {
  return api<EventReferenceData>('/events/reference-data')
}

/** Story 2.1 AC7/AC8: one request, as its organiser or a reviewing internal role sees it. */
export function getEvent(eventId: string): Promise<EventDetail> {
  return api<EventDetail>(`/events/${eventId}`, { errorCodes: EVENT_ERROR_CODES })
}

/** Mirrors `ClarificationOut.kind`. */
export type ClarificationKind = 'REQUEST' | 'RESPONSE' | 'NOTE'

/** Mirrors `ClarificationOut`: one entry of the clarification conversation on a request. */
export interface Clarification {
  id: string
  kind: ClarificationKind
  author_id: string
  author_name: string
  message: string
  created_at: string
}

/** Story 4.6 AC2: the clarification conversation on a request, oldest first. */
export function listClarifications(eventId: string): Promise<Clarification[]> {
  return api<Clarification[]>(`/events/${eventId}/clarifications`, {
    errorCodes: EVENT_ERROR_CODES,
  })
}

/** Story 2.1 AC1-AC6: record a new request. It starts as a draft. */
export function createEvent(input: EventInput): Promise<EventDetail> {
  return api<EventDetail>('/events', {
    method: 'POST',
    body: input,
    notify: { title: 'Draft saved', message: `"${input.name}" was saved as a draft.` },
  })
}

/** Story 2.1 AC7: change a draft. Only a draft can be changed. */
export function updateEvent(eventId: string, input: EventInput): Promise<EventDetail> {
  return api<EventDetail>(`/events/${eventId}`, {
    method: 'PATCH',
    body: input,
    errorCodes: EVENT_ERROR_CODES,
    notify: { title: 'Draft saved', message: `"${input.name}" was saved.` },
  })
}

/** Story 2.1 AC9-AC11: send a draft for review. */
export function submitEvent(eventId: string, name: string): Promise<EventDetail> {
  return api<EventDetail>(`/events/${eventId}/submit`, {
    method: 'POST',
    errorCodes: EVENT_ERROR_CODES,
    notify: {
      title: 'Request submitted',
      message: `"${name}" was sent to an Event Coordinator for review.`,
      importance: 'important',
    },
  })
}

/**
 * Mirrors `EventRoutineUpdate` (story 7.2). Only the routine fields: description, contact
 * details and internal notes. A partial update - only the fields sent change, and `null` clears
 * an optional one.
 */
/** Partial update, mirroring `EventRoutineUpdate`: a field is left out entirely to leave it
 * unchanged, present with a value to set it, or present as `null` to clear it. */
export interface EventRoutineInput {
  description?: string | null
  contact_name?: string | null
  contact_email?: string | null
  contact_phone?: string | null
  internal_notes?: string | null
}

/**
 * Story 7.2 AC1-AC3: the coordinator assigned to the event edits its routine information
 * directly. Rejected with an EVENT_ROUTINE_EDIT_CLOSED 409 once the event is completed,
 * cancelled or rejected.
 */
export function updateEventRoutineInformation(
  eventId: string,
  input: EventRoutineInput,
): Promise<EventDetail> {
  return api<EventDetail>(`/events/${eventId}/routine-information`, {
    method: 'PATCH',
    body: input,
    errorCodes: { 404: 'EVENT_NOT_FOUND', 409: 'EVENT_ROUTINE_EDIT_CLOSED' },
    notify: { title: 'Event updated', message: 'The routine event information was saved.' },
  })
}

/** Mirrors `EquipmentAvailabilityOut`: units of one equipment type free for a period. */
export interface EquipmentAvailability {
  equipment_type_code: string
  available: number
}

/** Story 2.1 AC6: how many of each equipment type are free for the proposed dates. */
export function fetchEquipmentAvailability(
  startsAt: string,
  endsAt: string,
): Promise<EquipmentAvailability[]> {
  const params = new URLSearchParams({ starts_at: startsAt, ends_at: endsAt })
  return api<EquipmentAvailability[]>(`/events/equipment-availability?${params.toString()}`)
}
