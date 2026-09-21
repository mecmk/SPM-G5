import { api } from './client'

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
  status: string
}

/** Story 13.1 AC1-AC3: every pending booking request, for Venue Staff to decide. */
export function listBookingRequests(): Promise<BookingQueueEntry[]> {
  return api<BookingQueueEntry[]>('/bookings')
}

/** Mirrors `BookingOut` in backend/app/bookings/schemas.py (story 13.2's read/approve shape). */
export interface Booking {
  id: string
  event_id: string
  venue_id: string
  requested_by_id: string
  starts_at: string
  ends_at: string
  expected_attendance: number
  required_layout_code: string | null
  requirement_notes: string | null
  status: string
  decided_by_id: string | null
  decided_at: string | null
  decision_reason: string | null
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
