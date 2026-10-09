import { api } from './client'

export type BookingStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'WITHDRAWN' | 'CANCELLED'

/** Mirrors `BookingOut`: a venue booking request and, once decided, its outcome. */
export interface Booking {
  id: string
  event_id: string
  venue_id: string
  /** Story 12.5 AC1: the venue requirement the request is for; null for an additional venue. */
  venue_requirement_id: string | null
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

/** Story 11.1 AC2: the longest justification for requesting an unsuitable venue. Keep in step by
 * hand with SUITABILITY_OVERRIDE_REASON_MAX_LENGTH in backend/app/bookings/schemas.py. */
export const SUITABILITY_OVERRIDE_REASON_MAX_LENGTH = 2000

/** Mirrors `BookingRequestIn`: one event, one venue. Everything else is copied server-side.
 * Story 11.1: `suitability_override_reason` is why a venue that does not suit is requested.
 * Story 12.5 AC1: `venue_requirement_id` is the event's venue requirement the request is for,
 * whose own times, people, layout and facilities it carries; left out, the request is for an
 * additional venue (AC5, AC7), carrying the event's own period and attendance. */
export interface BookingRequestInput {
  event_id: string
  venue_id: string
  venue_requirement_id?: string
  suitability_override_reason?: string
}

/** Story 12.1 AC1-AC4. Story 11.1 AC7: a venue that does not suit, sent without a justification,
 * is refused with a 422 - for instance when it stopped suiting after the step loaded. The code is
 * mapped by status alone, so it assumes `JustificationRequired` is this endpoint's only 422: give
 * any other 422 here its own code first, or it will be read as a missing justification.
 *
 * Story 12.5 AC3: the notice names the venue and the requirement it was requested for - or says
 * it is an additional venue, when `requirementName` is null. AC11/AC12: a requirement that
 * already has a pending or approved request is refused with a 409 naming its venue. */
export function createBookingRequest(
  input: BookingRequestInput,
  venueName: string,
  requirementName: string | null,
): Promise<Booking> {
  const requestedFor =
    requirementName === null ? 'as an additional venue' : `for ${requirementName}`
  return api<Booking>('/bookings', {
    method: 'POST',
    body: input,
    errorCodes: { 409: 'BOOKING_NOT_ALLOWED', 422: 'BOOKING_JUSTIFICATION_REQUIRED' },
    notify: {
      title: 'Venue requested',
      message: `${venueName} was requested ${requestedFor}; it is with Venue Staff for review.`,
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
  created_at: string
  decided_at: string | null
}

/** Mirrors `BookingStatusCounts`: how many requests hold each status, whatever tab or page was
 * asked for. */
export interface BookingStatusCounts {
  pending: number
  approved: number
  rejected: number
  withdrawn: number
  cancelled: number
}

/** Mirrors `BookingQueue`: one page of a queue tab, how many that tab holds, and every status's
 * count for the tab labels. */
export interface BookingQueue {
  items: BookingQueueEntry[]
  total: number
  counts: BookingStatusCounts
}

/**
 * Story 13.1 AC1-AC3: `'PENDING'` is the pending queue Venue Staff decide from. Story 13.1.2 AC1:
 * any other status is its own tab, and `null` is All. AC4: `limit` requests from the `offset`th
 * on - one numbered page.
 */
export function listBookingRequests(
  status: BookingStatus | null,
  offset: number,
  limit: number,
): Promise<BookingQueue> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  if (status !== null) params.set('status', status)
  return api<BookingQueue>(`/bookings?${params}`)
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

/** Story 12.2 AC2/AC3: withdraw a pending booking request. 403 (`NOT_PERMITTED`) once the
 * caller is not the event's assigned coordinator; 409 (`BOOKING_WITHDRAW_REFUSED`) once it is
 * no longer pending - both arrive with the backend's own sentence. */
export function withdrawBooking(bookingId: string, venueName: string): Promise<Booking> {
  return api<Booking>(`/bookings/${bookingId}/withdraw`, {
    method: 'POST',
    errorCodes: { 404: 'BOOKING_NOT_FOUND', 409: 'BOOKING_WITHDRAW_REFUSED' },
    notify: {
      title: 'Booking withdrawn',
      message: `The request for ${venueName} was withdrawn.`,
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
  /** Story 12.5 AC2/AC4: the venue requirement the booking is for, so the event's page and the
   * catalogue's banner can tell which requirements are covered. Both null for an additional
   * venue (AC5). */
  venue_requirement_id: string | null
  venue_requirement_name: string | null
  starts_at: string
  ends_at: string
  setup_minutes: number
  teardown_minutes: number
  status: BookingStatus
  decided_at: string | null
  decision_reason: string | null
  /** Story 11.1 AC6: why a venue that did not suit was requested; null when it suited. */
  suitability_override_reason: string | null
}

/** Story 13.2.1 AC4: every venue booking ever raised for this event, most recent first - lets a
 * coordinator read the full history directly on the event page. An event may accumulate more
 * than one row over time (a rejected request followed by a fresh one), so this is a history, not
 * a single outcome; deciding a booking updates that same row in place, it never adds another. */
export function listBookingsForEvent(eventId: string): Promise<BookingOutcome[]> {
  return api<BookingOutcome[]>(`/bookings/for-event/${eventId}`)
}
