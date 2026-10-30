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

/** Story 18.5 AC6: the most guests an attendee may bring, as the backend's MAX_GUESTS. */
export const MAX_GUESTS = 10

/** Mirrors `GuestOut`: story 18.5 AC3/AC4, one guest registered with an attendee. Their dietary
 *  requirements are null when none were given, and on a list row no longer Registered. */
export interface Guest {
  full_name: string
  dietary_requirements: string | null
}

/** Mirrors `GuestIn`: story 18.5 AC1/AC6, one guest as the attendee sends them - a name, required,
 *  and dietary requirements, which the backend makes null when blank. Nothing else is asked. */
export interface GuestInput {
  full_name: string
  dietary_requirements: string
}

/** Mirrors `RegistrationOut`: story 18.1 AC1, the registration just made. Story 18.5 AC1: and the
 *  guests registered with it, in order. */
export interface Registration {
  id: string
  event_id: string
  status: string
  registered_at: string
  guests: Guest[]
}

/** Story 18.4 AC6: the most characters of dietary requirements, as the backend's
 *  DIETARY_REQUIREMENTS_MAX_LENGTH. */
export const DIETARY_REQUIREMENTS_MAX_LENGTH = 500
/** Story 18.4 AC1: the most characters of a name, as the backend's FULL_NAME_MAX_LENGTH. */
export const FULL_NAME_MAX_LENGTH = 200

/** Mirrors `AttendeeDetailsIn`: story 18.4, the details an attendee sends, on My profile or with a
 *  registration. The name (AC1) and phone number (AC7) are required; blank dietary requirements
 *  are no value, which the backend makes null. */
export interface AttendeeDetails {
  full_name: string
  phone: string
  dietary_requirements: string
}

/** Mirrors `ProfileOut`: story 18.4 AC1, My profile. `has_confirmed_details` is false until the
 *  attendee first gives their details, so their first registration asks for them (AC2). */
export interface Profile {
  full_name: string
  email: string
  phone: string | null
  dietary_requirements: string | null
  has_confirmed_details: boolean
}

/** Story 18.4 AC1: the signed-in attendee's profile. */
export function fetchProfile(): Promise<Profile> {
  return api<Profile>('/profile')
}

/** Story 18.4 AC3/AC4: save the signed-in attendee's details, answered with the profile as saved.
 *  The later of two saves wins (AC11). */
export function updateProfile(details: AttendeeDetails): Promise<Profile> {
  return api<Profile>('/profile', {
    method: 'PATCH',
    body: details,
    notify: {
      title: 'Details saved',
      message: 'Your name, phone number and dietary requirements were saved.',
    },
  })
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
 *  (AC2-AC4, AC6) carries the backend's sentence saying why. Story 18.4 AC2/AC3: `details` are the
 *  ones the attendee confirmed, saved to their profile with the registration. Story 18.5 AC1:
 *  `guests` are registered with them, as one group; a group that does not fit is refused whole
 *  (AC2). */
export function registerForEvent(
  event: RegistrationEvent,
  details: AttendeeDetails,
  guests: GuestInput[],
): Promise<Registration> {
  return api<Registration>('/registrations', {
    method: 'POST',
    body: { event_id: event.id, details, guests },
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
  /** Story 18.5 AC3: the guests registered with it, in order. */
  guests: Guest[]
  /** Story 18.5 AC3: whether the guests can still be changed, decided by the server on its clock. */
  can_change_guests: boolean
  /** Story 18.5 AC3: how many guests it may have - those it has and one per place left, at most
   *  MAX_GUESTS - worked out by the server. */
  max_guests: number
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

/** Story 18.5 AC3: replace the guests of one of the signed-in attendee's registrations, answered
 *  with the registration as saved. A refusal (AC3) carries the backend's sentence saying
 *  why. */
export function updateGuests(
  registration: MyRegistration,
  guests: GuestInput[],
): Promise<MyRegistration> {
  return api<MyRegistration>(`/registrations/${encodeURIComponent(registration.id)}/guests`, {
    method: 'PUT',
    body: { guests },
    errorCodes: { 404: 'REGISTRATION_NOT_FOUND', 409: 'GUESTS_CHANGE_REFUSED' },
    notify: {
      title: 'Guests saved',
      message: `Your guests for ${registration.event_name} were saved.`,
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
  /** Story 18.4 AC5: null when none was given, and on every row no longer Registered (AC9). */
  attendee_phone: string | null
  /** Story 18.4 AC5: null when none were given - shown as "None" (AC6) - and on every row no
   *  longer Registered (AC9). */
  dietary_requirements: string | null
  registered_at: string
  status: RegistrationStanding
  withdrawn_at: string | null
  /** Story 18.5 AC4: the guests registered with them, in order; AC9: on a row no longer Registered,
   *  by name only. */
  guests: Guest[]
}

/** Mirrors `EventRegistrationListOut`: story 18.3 AC1-AC3/AC7, one page of the list, how many
 *  registrations there are in all, and how many places the active ones take against capacity -
 *  their guests included (story 18.5 AC4) - all worked out on the server. */
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
