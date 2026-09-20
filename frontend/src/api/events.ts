import { api } from './client'

/** Mirrors `ReviewQueueSort` in backend/app/events/schemas.py. */
export type ReviewQueueSort = 'submitted_at' | 'starts_at'
export type ReviewQueueStatus = 'SUBMITTED' | 'UNDER_REVIEW' | 'CLARIFICATION_REQUESTED'

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

/** Mirrors `EventStatus` in backend/app/events/models.py. */
export type EventStatus =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'UNDER_REVIEW'
  | 'CLARIFICATION_REQUESTED'
  | 'APPROVED'
  | 'PLANNING'
  | 'CONFIRMED'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'REJECTED'

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
 */
export interface EventDetail {
  id: string
  name: string
  purpose: string | null
  description: string | null
  starts_at: string | null
  ends_at: string | null
  expected_attendance: number | null
  status: EventStatus
  organiser_id: string
  organiser_name: string
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
