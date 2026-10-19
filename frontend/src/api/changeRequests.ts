import { api } from './client'
import type { EquipmentInput, EventStatus, VenueRequirementInput } from './events'
import type { UnavailabilityReason } from './venues'

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
 * attendance as a number, and each venue requirement and equipment item with its `id` (null for a
 * new one; absent on a request raised before ids were kept). Story 19.2 AC2/AC3: once decided,
 * who decided, when, and a rejection's reason; all null while it waits or once withdrawn. AC7:
 * `is_out_of_date` when it waits but the event no longer has the value it recorded as current -
 * another request's approval moved it - so it can only be rejected.
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
  decided_by_id: string | null
  decided_by_name: string | null
  decided_at: string | null
  decision_reason: string | null
  is_out_of_date: boolean
  created_at: string
  updated_at: string
}

/** Mirrors `ChangeRequestQueueEntryOut`: story 19.2 AC1, a change request in the coordinator's
 *  queue - pending, or in their record of decisions - with the event it is for. */
export interface ChangeRequestQueueEntry extends ChangeRequest {
  event_name: string
  event_status: EventStatus
  event_starts_at: string | null
  event_ends_at: string | null
}

/** The registry codes change request writes give their refusals; each arrives with the backend's
 * own sentence. */
const CHANGE_REQUEST_ERRORS = {
  404: 'EVENT_NOT_FOUND',
  409: 'CHANGE_REQUEST_REFUSED',
  422: 'CHANGE_REQUEST_INVALID',
} as const

/** Story 19.2: the registry codes a decision's refusals take; each arrives with the backend's own
 *  sentence (already decided or withdrawn, the event closed, changed since, or a creation rule). */
const CHANGE_REQUEST_DECISION_ERRORS = {
  403: 'NOT_PERMITTED',
  404: 'NOT_FOUND',
  409: 'CHANGE_REQUEST_DECISION_REFUSED',
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

/** Story 19.2 AC1: the change requests on the coordinator's own events - pending ones first,
 *  oldest first, then those decided or withdrawn, latest first. */
export function listCoordinatorChangeRequests(): Promise<ChangeRequestQueueEntry[]> {
  return api<ChangeRequestQueueEntry[]>('/change-requests')
}

/** Story 19.2 AC2: approve a pending change request, applying it to the event. Story 19.3 AC7:
 *  with the fingerprint of the impact assessment the coordinator saw; a 412 means the impact has
 *  changed since, and nothing was applied. */
export function approveChangeRequest(
  eventId: string,
  changeRequestId: string,
  assessmentFingerprint: string,
  fieldLabel: string,
): Promise<ChangeRequest> {
  return api<ChangeRequest>(`/events/${eventId}/change-requests/${changeRequestId}/approve`, {
    method: 'POST',
    body: { assessment_fingerprint: assessmentFingerprint },
    errorCodes: { ...CHANGE_REQUEST_DECISION_ERRORS, 412: 'CHANGE_REQUEST_IMPACT_CHANGED' },
    notify: {
      title: 'Change approved',
      message: `The change to the ${fieldLabel} was approved and applied to the event.`,
    },
  })
}

/** Story 19.2 AC3/AC4: reject a pending change request with a non-blank reason. */
export function rejectChangeRequest(
  eventId: string,
  changeRequestId: string,
  reason: string,
  fieldLabel: string,
): Promise<ChangeRequest> {
  return api<ChangeRequest>(`/events/${eventId}/change-requests/${changeRequestId}/reject`, {
    method: 'POST',
    body: { reason },
    errorCodes: CHANGE_REQUEST_DECISION_ERRORS,
    notify: {
      title: 'Change rejected',
      message: `The change to the ${fieldLabel} was rejected, and the organiser told why.`,
    },
  })
}

/** Mirrors `CapacityWarningOut`: story 19.3 AC1/AC4, the booked venue holds fewer people than the
 *  change needs - in the booked layout (`layout_name`) where the venue records its capacity, else
 *  its maximum. A warning only: whether the booking is cancelled is `will_be_cancelled`. */
export interface CapacityWarning {
  people_needed: number
  venue_capacity: number
  layout_name: string | null
}

/** Mirrors `HoldingBookingOut`: another booking holding the venue over the period needed. */
export interface HoldingBooking {
  event_name: string
  held_from: string
  held_until: string
}

/** Mirrors `ClosureOut`: a period the venue is unavailable for over the period needed. */
export interface Closure {
  reason: UnavailabilityReason
  notes: string | null
  starts_at: string
  ends_at: string
}

/** Mirrors `CountedVenueOut`: one booked venue counted towards a `CapacityShortfall`. */
export interface CountedVenue {
  venue_name: string
  capacity: number
  layout_name: string | null
}

/** Mirrors `CapacityShortfallOut`: story 19.3 AC1/AC4, an attendance change asks for more people
 *  than the venues still booked after approval hold between them. A warning only. */
export interface CapacityShortfall {
  proposed_attendance: number
  booked_capacity: number
  shortfall: number
  venues: CountedVenue[]
}

/** Mirrors `BookingImpactOut`: story 19.3 AC1/AC2, one venue booking the change affects. */
export interface BookingImpact {
  booking_id: string
  venue_id: string
  venue_name: string
  /** Null for an additional venue (12.5). */
  requirement_name: string | null
  status: string
  starts_at: string
  ends_at: string
  will_be_cancelled: boolean
  reasons: string[]
  capacity_warning: CapacityWarning | null
  /** The period a replacement would need, for a cancelled booking whose requirement remains. */
  needed_starts_at: string | null
  needed_ends_at: string | null
  held_by: HoldingBooking | null
  closure: Closure | null
  is_outside_opening_hours: boolean
  after_approval: string
}

/** Values of `EquipmentImpactOut.change`. */
export type EquipmentImpactChange = 'removed' | 'changed' | 'added' | 'rechecked'

/** Mirrors `EquipmentImpactOut`: story 19.3 AC1/AC2/AC5, one equipment item the change affects.
 *  `required`/`available` are null for a removed item; `status_after` null when it is deleted. */
export interface EquipmentImpact {
  item_id: string | null
  equipment_type_code: string
  equipment_type_name: string
  change: EquipmentImpactChange
  current_status: string | null
  required: number | null
  available: number | null
  shortfall: number
  status_after: string | null
  technical_support_told: boolean
  after_approval: string
}

/** Mirrors `RegistrationImpactOut`: story 19.3 AC1, the registrations affected, counted. */
export interface RegistrationImpact {
  active_count: number
  proposed_attendance: number | null
  over_by: number
  dates_change: boolean
}

/** Mirrors `ChangeRequestImpactOut`: story 19.3, what approving a pending change request would
 *  affect, worked out by the backend from the records as they stand. `fingerprint` goes back with
 *  the approval (AC7). */
export interface ChangeRequestImpact {
  change_request_id: string
  assessed_at: string
  fingerprint: string
  is_out_of_date: boolean
  refused_because: string | null
  venue_bookings: BookingImpact[]
  equipment: EquipmentImpact[]
  registrations: RegistrationImpact | null
  capacity_shortfall: CapacityShortfall | null
  has_impact: boolean
}

/** Story 19.3 AC1-AC6: the impact of approving a pending change request, for the event's
 *  assigned coordinator. */
export function getChangeRequestImpact(
  eventId: string,
  changeRequestId: string,
): Promise<ChangeRequestImpact> {
  return api<ChangeRequestImpact>(`/events/${eventId}/change-requests/${changeRequestId}/impact`, {
    errorCodes: CHANGE_REQUEST_DECISION_ERRORS,
  })
}
