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
  /** Story 18.4 AC14 (fix f18.4.1): the guest registered with it, null with none. */
  guest_name: string | null
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

/** Mirrors `GuestIn`: story 18.4 AC12 (fix f18.4.1), the one guest an attendee brings, typed in
 *  with the registration and never saved to their profile. The name and phone number are
 *  required, by the attendee's own rules; blank dietary requirements are no value. */
export interface GuestDetails {
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

/** Story 18.1 AC1: how many events a page asks for - the backend's REGISTRATION_EVENTS_PAGE_SIZE. */
export const REGISTRATION_EVENTS_PAGE_SIZE = 20

/** Story 18.1 AC1: a page of the events open to attendees, from `offset`. */
export function listRegistrationEvents(offset: number): Promise<RegistrationEventList> {
  return api<RegistrationEventList>(
    `/registrations/events?offset=${offset}&limit=${REGISTRATION_EVENTS_PAGE_SIZE}`,
  )
}

/**
 * Mirrors `AttendeeEventOut`: story 18.1 AC9 / 18.2 AC9-AC10 (fixes f18.1.2, f18.2.1), one event's
 * page for the signed-in attendee. `listing` is what its card on Upcoming events shows, null once
 * it is not listed (18.2 AC10: started, cancelled, sent back to Planning or made Private), and
 * `venues` then are only those it still has booked. `registration` is the attendee's own latest
 * registration for it, null if they never registered. 18.1 AC5: nothing internal is sent.
 */
export interface AttendeeEvent {
  id: string
  name: string
  description: string | null
  /** Story 18.1 AC8: the event's cover picture, if it has one. */
  cover_image_url: string | null
  starts_at: string
  ends_at: string
  venues: RegistrationVenue[]
  listing: RegistrationEvent | null
  registration: MyRegistration | null
}

/** Story 18.1 AC9 / 18.2 AC9: one event's page. 18.1 AC10: one that is neither listed nor
 *  registered for by the attendee is a 404, saying it is not open for registration, as for an
 *  unknown event. */
export function fetchAttendeeEvent(eventId: string): Promise<AttendeeEvent> {
  return api<AttendeeEvent>(`/registrations/events/${encodeURIComponent(eventId)}`, {
    errorCodes: { 404: 'REGISTRATION_EVENT_NOT_OPEN' },
  })
}

/** Story 18.1 AC1: register the signed-in attendee. The notice is AC1's confirmation; a refusal
 *  (AC2-AC4, AC6) carries the backend's sentence saying why. Story 18.4 AC2/AC3: `details` are the
 *  ones the attendee confirmed, saved to their profile with the registration. AC12 (fix f18.4.1):
 *  `guest`, the one they bring, if any; AC13: one place left for the two is a 422, as details the
 *  server refuses are, since the attendee fixes it in the same dialog. */
export function registerForEvent(
  event: Pick<RegistrationEvent, 'id' | 'name'>,
  details: AttendeeDetails,
  guest: GuestDetails | null,
): Promise<Registration> {
  return api<Registration>('/registrations', {
    method: 'POST',
    body: { event_id: event.id, details, guest },
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
  /** Story 18.4 AC14 (fix f18.4.1): the guest they brought, null with none. */
  guest_name: string | null
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

/** Mirrors `RegistrationGuestOut`: story 18.4 AC15 (fix f18.4.1), the guest a registration brought,
 *  as the event's organiser and coordinator see them. */
export interface RegistrationGuest {
  full_name: string
  /** Null on a registration no longer Registered (AC9), as the attendee's own. */
  phone: string | null
  /** Null when none were given - shown as "None" (AC6) - and on a registration no longer
   *  Registered (AC9). */
  dietary_requirements: string | null
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
  /** Story 18.4 AC15 (fix f18.4.1): the guest they brought, null with none. */
  guest: RegistrationGuest | null
}

/** Mirrors `EventRegistrationListOut`: story 18.3 AC1-AC3/AC7, one page of the list, how many
 *  registrations there are in all, and how many places the active ones take against capacity -
 *  guests included (18.4 AC13) - all worked out on the server. */
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
