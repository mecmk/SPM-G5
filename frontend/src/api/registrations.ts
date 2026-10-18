import { api } from './client'

/** Values of `RegistrationState` (backend/app/registrations/service.py): story 18.1 AC1/AC3,
 *  where an event stands for the attendee looking at it. */
export type RegistrationState = 'OPEN' | 'NOT_YET_OPEN' | 'FULL' | 'CLOSED' | 'REGISTERED'

/** Mirrors `RegistrationVenueOut`: story 18.1 AC1, a venue booked for the event. */
export interface RegistrationVenue {
  name: string
  location: string
}

/**
 * Mirrors `RegistrationEventOut`: story 18.1 AC1, one event an attendee can register for.
 * `registration_closes_at` is when registration closes - the closing time, or the event's start
 * where none was recorded (AC2). `registered_at` is set only when `state` is REGISTERED. AC5:
 * nothing internal to the event's planning is sent.
 */
export interface RegistrationEvent {
  id: string
  name: string
  description: string | null
  /** Fix f18.1.1 (story 2.1 AC14): the event's cover picture, if it has one. */
  cover_image_url: string | null
  starts_at: string
  ends_at: string
  venues: RegistrationVenue[]
  registration_opens_at: string | null
  registration_closes_at: string
  places_left: number
  state: RegistrationState
  registered_at: string | null
}

/** Mirrors `RegistrationEventList`: story 18.1 AC1, one page of the list and its total. */
export interface RegistrationEventList {
  items: RegistrationEvent[]
  total: number
}

/** Mirrors `RegistrationOut`: story 18.1 AC1, the registration just made. */
export interface Registration {
  id: string
  event_id: string
  status: string
  registered_at: string
}

/** Story 18.1 AC1: how many events a page asks for - the backend's REGISTRATION_EVENTS_PAGE_SIZE.
 *  A refreshed list asks for at most REGISTRATION_EVENTS_MAX_LIMIT at once. */
export const REGISTRATION_EVENTS_PAGE_SIZE = 20
export const REGISTRATION_EVENTS_MAX_LIMIT = 100

/** Story 18.1 AC1: a page of the events open to attendees, from `offset`. */
export function listRegistrationEvents(
  offset: number,
  limit: number = REGISTRATION_EVENTS_PAGE_SIZE,
): Promise<RegistrationEventList> {
  return api<RegistrationEventList>(`/registrations/events?offset=${offset}&limit=${limit}`)
}

/** Story 18.1 AC1: register the signed-in attendee. The notice is AC1's confirmation; a refusal
 *  (AC2-AC4, AC6) carries the backend's sentence saying why. */
export function registerForEvent(event: RegistrationEvent): Promise<Registration> {
  return api<Registration>('/registrations', {
    method: 'POST',
    body: { event_id: event.id },
    errorCodes: { 404: 'REGISTRATION_EVENT_NOT_OPEN', 409: 'REGISTRATION_REFUSED' },
    notify: { title: 'Registered', message: `You are registered for ${event.name}.` },
  })
}
