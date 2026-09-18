import { api } from './client'

/**
 * Story 7.1. Mirrors `EventDetailOut` in backend/app/events/schemas.py — not implemented yet.
 * The backend endpoint is queued behind story 4.1 (`display-coordinator-review-queue`), which
 * is adding backend/app/events/{router,schemas,service}.py first; `getEvent` will fail with a
 * network or 404 error until that lands and this endpoint is added alongside it.
 */
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

/** Mirrors a planned `RequiredFacilityOut`: one row of `event_required_facilities`, resolved. */
export interface RequiredFacility {
  code: string
  name: string
  notes: string | null
}

/** Mirrors a planned `AccessibilityNeedOut`: one row of `event_accessibility_needs`, resolved. */
export interface AccessibilityNeed {
  code: string
  name: string
  notes: string | null
}

/** Mirrors a planned `EquipmentRequirementOut`: one row of `event_equipment_requests`. */
export interface EquipmentRequirement {
  equipment_type_code: string
  equipment_type_name: string
  quantity: number
  technical_notes: string | null
  status: string
}

/**
 * Mirrors a planned `EventDetailOut`. AC1: core details, venue and accessibility requirements,
 * equipment requirements, status and assigned coordinator. Venue bookings (story 13.4) and
 * equipment reservation status (story 17.3) are out of this story's scope.
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
  preferred_location: string | null
  required_layout_name: string | null
  required_facilities: RequiredFacility[]
  venue_requirement_notes: string | null
  /** True only when the organiser explicitly recorded no accessibility needs. */
  accessibility_none_required: boolean
  accessibility_needs: AccessibilityNeed[]
  accessibility_notes: string | null
  equipment: EquipmentRequirement[]
  assigned_coordinator_name: string | null
}

/**
 * Story 7.1 AC1/AC2. A relationship-based denial (the event exists but is not the caller's to
 * see) and a genuinely missing event both come back as a plain 404, so a caller cannot tell an
 * event apart from one they are simply not related to.
 */
export function getEvent(eventId: string): Promise<EventDetail> {
  // TEMP VISUAL PREVIEW - reverted once you're done looking, not part of the real change.
  return Promise.resolve({
    id: eventId,
    name: 'Nimbus Developer Conference',
    purpose: 'Annual customer conference',
    description: 'Keynotes in the morning, breakout tracks after lunch.',
    starts_at: '2026-11-25T09:00:00+08:00',
    ends_at: '2026-11-25T18:00:00+08:00',
    expected_attendance: 350,
    status: 'APPROVED',
    preferred_location: 'Tower A',
    required_layout_name: 'Theatre',
    required_facilities: [
      { code: 'PROJECTOR', name: 'Projector', notes: null },
      { code: 'SOUND_SYSTEM', name: 'Sound system', notes: null },
      { code: 'STAGE', name: 'Stage', notes: null },
    ],
    venue_requirement_notes: null,
    accessibility_none_required: false,
    accessibility_needs: [
      {
        code: 'WHEELCHAIR_ACCESS',
        name: 'Wheelchair access',
        notes: 'Two wheelchair users expected',
      },
      { code: 'HEARING_LOOP', name: 'Hearing loop', notes: null },
    ],
    accessibility_notes: null,
    equipment: [
      {
        equipment_type_code: 'WIRELESS_MIC',
        equipment_type_name: 'Wireless microphone',
        quantity: 6,
        technical_notes: 'Two per breakout room',
        status: 'REQUESTED',
      },
      {
        equipment_type_code: 'LAPTOP',
        equipment_type_name: 'Laptop',
        quantity: 2,
        technical_notes: null,
        status: 'REQUESTED',
      },
    ],
    assigned_coordinator_name: 'Chloe Coordinator',
  })
  // return api<EventDetail>(`/events/${eventId}`)
}
