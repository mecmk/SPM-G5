import { api } from './client'
import type { EquipmentInput, VenueRequirementInput } from './events'

/** Story 19.1 AC4: the longest reason. Keep in step with the backend's `CHANGE_REASON_MAX_LENGTH`
 * in app/change_requests/schemas.py. */
export const CHANGE_REASON_MAX_LENGTH = 2000

/** Values of `ck_event_change_requests_field_name` (migration 015): what may be requested. */
export type ChangeRequestField =
  'schedule' | 'expected_attendance' | 'venue_requirements' | 'equipment'

/** Values of `ck_event_change_requests_status`. */
export type ChangeRequestStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'WITHDRAWN'

/** Mirrors `ProposedSchedule`: the event's new start and end, requested together. */
export interface ProposedSchedule {
  starts_at: string
  ends_at: string
}

/**
 * Mirrors the `ChangeRequestIn` union: one field and the value proposed for it, plus why. The
 * value's shape is the one story 2.1/2.7's request form sends for the same field.
 */
export type ChangeRequestInput =
  | { field: 'schedule'; proposed: ProposedSchedule; reason: string }
  | { field: 'expected_attendance'; proposed: number; reason: string }
  | { field: 'venue_requirements'; proposed: VenueRequirementInput[]; reason: string }
  | { field: 'equipment'; proposed: EquipmentInput[]; reason: string }

/**
 * Mirrors `ChangeRequestOut`: story 19.1 AC1, a change request as the organiser and the assigned
 * coordinator see it. `current_value` and `proposed_value` are in the canonical shape the backend
 * stores (app/change_requests/service.py): a schedule as `{ starts_at, ends_at }` in UTC, the
 * attendance as a number, and each list without ids.
 */
export interface ChangeRequest {
  id: string
  event_id: string
  field: ChangeRequestField
  current_value: unknown
  proposed_value: unknown
  reason: string
  status: ChangeRequestStatus
  requested_by_id: string
  requested_by_name: string
  created_at: string
  updated_at: string
}

/** The registry codes change request writes give their refusals; each arrives with the backend's
 * own sentence. */
const CHANGE_REQUEST_ERRORS = {
  404: 'EVENT_NOT_FOUND',
  409: 'CHANGE_REQUEST_REFUSED',
  422: 'CHANGE_REQUEST_INVALID',
} as const

/** Story 19.1 AC1: the event's change requests, newest first. */
export function listChangeRequests(eventId: string): Promise<ChangeRequest[]> {
  return api<ChangeRequest[]>(`/events/${eventId}/change-requests`, {
    errorCodes: { 404: 'EVENT_NOT_FOUND' },
  })
}

/** Story 19.1 AC1-AC8: ask for one field of the organiser's Planning event to change. */
export function raiseChangeRequest(
  eventId: string,
  input: ChangeRequestInput,
  fieldLabel: string,
): Promise<ChangeRequest> {
  return api<ChangeRequest>(`/events/${eventId}/change-requests`, {
    method: 'POST',
    body: input,
    errorCodes: CHANGE_REQUEST_ERRORS,
    notify: {
      title: 'Change requested',
      message: `Your change to the ${fieldLabel} was sent to the coordinator.`,
    },
  })
}

/** Story 19.1 AC9/AC10: withdraw one of the organiser's pending change requests. */
export function withdrawChangeRequest(
  eventId: string,
  changeRequestId: string,
  fieldLabel: string,
): Promise<ChangeRequest> {
  return api<ChangeRequest>(`/events/${eventId}/change-requests/${changeRequestId}/withdraw`, {
    method: 'POST',
    errorCodes: { ...CHANGE_REQUEST_ERRORS, 404: 'NOT_FOUND' },
    notify: {
      title: 'Change request withdrawn',
      message: `Your change to the ${fieldLabel} was withdrawn.`,
    },
  })
}
