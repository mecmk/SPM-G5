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
  /** Story 18.1 AC8 (fix f18.1.1): the event's cover picture, if it has one. */
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

/** Values of `RegistrationStanding` (backend/app/registrations/service.py): story 18.2 AC1/AC8,
 *  where the attendee stands with an event they registered for. */
export type RegistrationStanding = 'REGISTERED' | 'WITHDRAWN' | 'EVENT_CANCELLED'

/**
 * Mirrors `MyRegistrationOut`: story 18.2 AC1, one of the attendee's own registrations.
 * `withdrawn_at` is set only when `status` is WITHDRAWN. `can_withdraw` is decided by the server,
 * on its clock (AC3). AC5: nothing internal to the event's planning is sent.
 */
export interface MyRegistration {
  id: string
  event_id: string
  event_name: string
  /** Story 2.1 AC14: the event's cover picture, if it has one. */
  cover_image_url: string | null
  starts_at: string
  ends_at: string
  status: RegistrationStanding
  registered_at: string
  withdrawn_at: string | null
  can_withdraw: boolean
}

/** Story 18.2 AC1: the signed-in attendee's registrations, one per event, events not yet started
 *  first. */
export function listMyRegistrations(): Promise<MyRegistration[]> {
  return api<MyRegistration[]>('/registrations')
}

/** Story 18.2 AC1/AC2: withdraw one of the signed-in attendee's registrations. The notice is the
 *  confirmation; a refusal (AC3, AC6-AC8) carries the backend's sentence saying why. */
export function withdrawRegistration(registration: MyRegistration): Promise<MyRegistration> {
  return api<MyRegistration>(`/registrations/${encodeURIComponent(registration.id)}/withdraw`, {
    method: 'POST',
    errorCodes: { 404: 'REGISTRATION_NOT_FOUND', 409: 'WITHDRAWAL_REFUSED' },
    notify: {
      title: 'Withdrawn',
      message: `You have withdrawn from ${registration.event_name}.`,
    },
  })
}

/** Mirrors `EventRegistrationOut`: story 18.3 AC1/AC4, one registration in an event's list, with
 *  where the attendee stands as 18.2 tells them. `withdrawn_at` is set only when `status` is
 *  WITHDRAWN. */
export interface EventRegistration {
  id: string
  attendee_name: string
  attendee_email: string
  registered_at: string
  status: RegistrationStanding
  withdrawn_at: string | null
}

/** Mirrors `EventRegistrationListOut`: story 18.3 AC1-AC3/AC7, one page of the list, how many
 *  registrations there are in all, and how many are active against capacity, all worked out on
 *  the server. */
export interface EventRegistrationList {
  items: EventRegistration[]
  total: number
  active_count: number
  capacity: number
  is_full: boolean
}

/** Story 18.3 AC1: how many registrations a page of the list asks for - the backend's
 *  REGISTRATION_LIST_PAGE_SIZE. */
export const REGISTRATION_LIST_PAGE_SIZE = 50

/** Mirrors `ManagedRegistrationEventOut`: story 18.3 AC5, one event on the registrations
 *  report's picker. */
export interface ManagedRegistrationEvent {
  id: string
  name: string
  starts_at: string
  ends_at: string
}

/** Story 18.3 AC5: the events past draft that the signed-in user organises or coordinates and
 *  that take or hold registrations, soonest first. */
export function listManagedRegistrationEvents(): Promise<ManagedRegistrationEvent[]> {
  return api<ManagedRegistrationEvent[]>('/registrations/managed')
}

/** Story 18.3: a page of the registrations for an event the signed-in user organises or
 *  coordinates, from `offset`. */
export function listEventRegistrations(
  eventId: string,
  offset: number = 0,
  limit: number = REGISTRATION_LIST_PAGE_SIZE,
): Promise<EventRegistrationList> {
  return api<EventRegistrationList>(
    `/events/${encodeURIComponent(eventId)}/registrations?offset=${offset}&limit=${limit}`,
    { errorCodes: { 404: 'REGISTRATION_LIST_NOT_FOUND' } },
  )
}
