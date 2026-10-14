import { api } from './client'

/** Mirrors `CoordinatorOption` (story 5.1 AC2): an Event Coordinator selectable for assignment,
 *  with how many active events they already hold (story 5.4 AC3). */
export interface CoordinatorOption {
  id: string
  full_name: string
  email: string
  department: string | null
  active_event_count: number
}

/** Mirrors `UnassignedEventEntry` (story 5.4 AC2): a submitted event waiting for a coordinator. */
export interface UnassignedEventEntry {
  id: string
  name: string
  starts_at: string
  ends_at: string
  expected_attendance: number
  organiser_name: string
  /** Null if the submission time was never recorded. */
  submitted_at: string | null
}

/** Mirrors `EventCoordinatorOut`: the event's coordinator after an assign/reassign, who made the
 *  change and when (story 5.1 AC3, story 5.2 AC1/AC2). */
export interface EventCoordinatorOut {
  assignment_id: string
  event_id: string
  coordinator_id: string
  coordinator_name: string
  coordinator_email: string
  assigned_by_id: string | null
  assigned_by_name: string | null
  assigned_at: string
  note: string | null
}

const COORDINATOR_ERROR_CODES = { 404: 'EVENT_NOT_FOUND' } as const

/**
 * Story 5.1 AC2: the coordinators offered for assignment. Story 5.2 AC4: pass `excludeEventId`
 * for the reassignment picker, which must leave that event's current coordinator out of its own
 * eligible list.
 */
export function listCoordinators(excludeEventId?: string): Promise<CoordinatorOption[]> {
  const query = excludeEventId ? `?exclude_event_id=${excludeEventId}` : ''
  return api<CoordinatorOption[]>(`/coordinators${query}`)
}

/** Story 5.4 AC2: every submitted event with no coordinator, oldest submission first. */
export function listUnassignedEvents(): Promise<UnassignedEventEntry[]> {
  return api<UnassignedEventEntry[]>('/coordination/unassigned-events')
}

/**
 * Story 5.4 AC3: the Lead gives an unassigned event its first coordinator. Same endpoint as
 * `assignCoordinator`, with its own notice. 409 (`CONFLICT`) when another Lead assigned it first
 * (AC8), with the backend's sentence naming who got it.
 */
export function assignUnassignedEvent(
  eventId: string,
  coordinatorId: string,
): Promise<EventCoordinatorOut> {
  return api<EventCoordinatorOut>(`/events/${eventId}/coordinator`, {
    method: 'PUT',
    body: { coordinator_id: coordinatorId },
    errorCodes: COORDINATOR_ERROR_CODES,
    notify: {
      title: 'Coordinator assigned',
      message: 'The event was assigned to its coordinator.',
    },
  })
}

/**
 * Story 5.2 AC1: hand an event to a different coordinator.
 * 403 (`NOT_PERMITTED`) once the event already has a coordinator and the caller is not them
 * (5.2 AC6); 409 (`CONFLICT`) if the coordinator changed since the caller last read it (5.2 AC7) -
 * both arrive with the backend's own sentence, so the default registry codes need no override.
 */
export function assignCoordinator(
  eventId: string,
  coordinatorId: string,
): Promise<EventCoordinatorOut> {
  return api<EventCoordinatorOut>(`/events/${eventId}/coordinator`, {
    method: 'PUT',
    body: { coordinator_id: coordinatorId },
    errorCodes: COORDINATOR_ERROR_CODES,
    notify: {
      title: 'Coordinator reassigned',
      message: 'The event was handed to its new coordinator.',
    },
  })
}
