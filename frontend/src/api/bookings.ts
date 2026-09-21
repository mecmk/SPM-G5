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
      message: `${venueName} was requested; Venue Staff will assess it.`,
    },
  })
}
