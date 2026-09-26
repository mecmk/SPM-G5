import { api } from './client'

/** Mirrors `BookableEvent` in backend/app/bookings/schemas.py: one choice in the event picker. */
export interface BookableEvent {
  id: string
  name: string
  starts_at: string
  ends_at: string
  expected_attendance: number
}

/** Mirrors `BookingReferenceData`: the booking form's pick-lists. Venues come from `listVenues`. */
export interface BookingReferenceData {
  events: BookableEvent[]
}

export type BookingStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'WITHDRAWN' | 'CANCELLED'

/** Mirrors `BookingOut`: a venue booking request and, once decided, its outcome. */
export interface Booking {
  id: string
  event_id: string
  venue_id: string
  requested_by_id: string
  starts_at: string
  ends_at: string
  setup_minutes: number
  teardown_minutes: number
  held_from: string
  held_until: string
  expected_attendance: number
  required_layout_code: string | null
  requirement_notes: string | null
  suitability_override_reason: string | null
  status: BookingStatus
  decided_by_id: string | null
  decided_at: string | null
  decision_reason: string | null
  alternative_suggestion: string | null
  created_at: string
  updated_at: string
}

/** Mirrors `BookingRequestIn`: one event, one venue. Everything else is copied server-side. */
export interface BookingRequestInput {
  event_id: string
  venue_id: string
}

/** Story 12.1 AC1/AC4: the events this coordinator may raise a booking for. */
export function fetchBookingReferenceData(): Promise<BookingReferenceData> {
  return api<BookingReferenceData>('/bookings/reference-data')
}

/** Story 12.1 AC1-AC4. */
export function createBookingRequest(
  input: BookingRequestInput,
  venueName: string,
): Promise<Booking> {
  return api<Booking>('/bookings', {
    method: 'POST',
    body: input,
    errorCodes: { 409: 'BOOKING_NOT_ALLOWED' },
    notify: {
      title: 'Venue requested',
      message: `${venueName} was requested; it is with Venue Staff for review.`,
    },
  })
}

/** Mirrors `BookingQueueEntry` in backend/app/bookings/schemas.py. */
export interface BookingQueueEntry {
  id: string
  event_id: string
  event_name: string
  venue_id: string
  venue_name: string
  venue_location: string
  starts_at: string
  ends_at: string
  expected_attendance: number
  required_layout_code: string | null
  required_layout_name: string | null
  requirement_notes: string | null
  requested_by_name: string
  status: BookingStatus
  decision_reason: string | null
}

/** Story 13.1 AC1-AC3: every booking request regardless of status, for Venue Staff to decide
 * or review through the All / Pending / Approved / Rejected tabs. */
export function listBookingRequests(): Promise<BookingQueueEntry[]> {
  return api<BookingQueueEntry[]>('/bookings')
}

/** Story 13.1: the full record behind one queue entry, for the request's detail view. */
export function getBooking(bookingId: string): Promise<Booking> {
  return api<Booking>(`/bookings/${bookingId}`)
}

/** Story 13.2 AC1: approve a pending booking request. AC4: refused (409) on a venue conflict. */
export function approveBooking(bookingId: string, eventName: string): Promise<Booking> {
  return api<Booking>(`/bookings/${bookingId}/approve`, {
    method: 'POST',
    errorCodes: { 404: 'BOOKING_NOT_FOUND', 409: 'BOOKING_CONFLICT' },
    notify: {
      title: 'Booking approved',
      message: `${eventName}'s venue booking was approved.`,
      importance: 'important',
    },
  })
}

/** Story 13.2.1 AC1/AC2: reject a pending booking request with a mandatory reason. */
export function rejectBooking(
  bookingId: string,
  eventName: string,
  decisionReason: string,
): Promise<Booking> {
  return api<Booking>(`/bookings/${bookingId}/reject`, {
    method: 'POST',
    body: { decision_reason: decisionReason },
    errorCodes: { 404: 'BOOKING_NOT_FOUND', 409: 'BOOKING_REJECT_REFUSED' },
    notify: {
      title: 'Booking rejected',
      message: `${eventName}'s venue booking was rejected.`,
      importance: 'important',
    },
  })
}

/** Mirrors `BookingOutcome`: one booking's outcome as the event page shows it - venue name and
 * location rather than a raw id, since this is a read-only summary, not the full record. */
export interface BookingOutcome {
  id: string
  venue_id: string
  venue_name: string
  venue_location: string
  starts_at: string
  ends_at: string
  setup_minutes: number
  teardown_minutes: number
  status: BookingStatus
  decided_at: string | null
  decision_reason: string | null
}

/** Story 13.2.1 AC4: every venue booking ever raised for this event, most recent first - lets a
 * coordinator read the full history directly on the event page. An event may accumulate more
 * than one row over time (a rejected request followed by a fresh one), so this is a history, not
 * a single outcome; deciding a booking updates that same row in place, it never adds another. */
export function listBookingsForEvent(eventId: string): Promise<BookingOutcome[]> {
  return api<BookingOutcome[]>(`/bookings/for-event/${eventId}`)
}
