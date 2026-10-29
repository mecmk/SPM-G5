import { api } from './client'

/** Story 12.7 AC3: EXPIRED is an approved booking whose hold lapsed before its event was
 * confirmed. */
export type BookingStatus =
  'PENDING' | 'APPROVED' | 'REJECTED' | 'WITHDRAWN' | 'CANCELLED' | 'EXPIRED'

/** Mirrors `HoldExpiryChangedBy`: the Venue Staff member who last changed a hold's expiry
 * (story 12.7 AC7, decided 12 Oct 2026). */
export interface HoldExpiryChangedBy {
  id: string
  full_name: string
}

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
  /** Story 12.7 AC1: when an approved booking's hold expires unless its event is confirmed first,
   * or when an expired one's did; null while pending. AC4: when the event's confirmation
   * completed it; null while it is open. */
  hold_expires_at: string | null
  hold_completed_at: string | null
  /** Story 12.7 AC7, decided 12 Oct 2026: the latest change to that expiry - why, by whom and
   * when; all null until Venue Staff make one. */
  hold_expiry_change_reason: string | null
  hold_expiry_changed_by: HoldExpiryChangedBy | null
  hold_expiry_changed_at: string | null
  /** Story 9.4 AC3: when the booking was marked "Venue unavailable - alternative needed"; null
   * when unmarked, and always null once the booking is no longer pending or approved. */
  venue_unavailable_marked_at: string | null
  /** Story 12.6 AC2/AC3: the booking this one replaces and the one that replaced it. For Venue
   * Staff deciding a replacement (AC3, AC6): the venue replaced, the venue approving will release -
   * only while that booking still holds its venue - and whether the original is still marked. All
   * null for a booking that replaces and is replaced by nothing. */
  replaces_booking_id: string | null
  replaced_by_booking_id: string | null
  replaces_venue_name: string | null
  approval_releases_venue_name: string | null
  original_is_marked: boolean | null
  decided_by_id: string | null
  decided_at: string | null
  decision_reason: string | null
  alternative_suggestion: string | null
  /** Story 6.2 AC16: when a cancelled booking was cancelled; null otherwise. */
  cancelled_at: string | null
  created_at: string
  updated_at: string
}

/** Story 11.1 AC2: the longest justification for requesting an unsuitable venue. Keep in step by
 * hand with SUITABILITY_OVERRIDE_REASON_MAX_LENGTH in backend/app/bookings/schemas.py. */
export const SUITABILITY_OVERRIDE_REASON_MAX_LENGTH = 2000

/** f12.1.2 (story 12.1 AC5): the longest setup or teardown, 14 days in minutes - the longest an
 * event may run. Keep in step by hand with TURNAROUND_MAX_MINUTES in
 * backend/app/bookings/schemas.py. */
export const TURNAROUND_MAX_MINUTES = 14 * 24 * 60

/** Mirrors `BookingRequestIn`: one event, one venue. Everything else is copied server-side.
 * Story 11.1: `suitability_override_reason` is why a venue that does not suit is requested.
 * Story 12.5 AC1: `venue_requirement_id` is the event's venue requirement the request is for,
 * whose own times, people, layout and facilities it carries; left out, the request is for an
 * additional venue (AC5, AC7), carrying the event's own period and attendance.
 * f12.1.2 (story 12.1 AC1/AC5): `setup_minutes` and `teardown_minutes` hold the venue that long
 * before the request's own times start and after they end - whole minutes from 0 to
 * `TURNAROUND_MAX_MINUTES`, and 0 when left out. The step refuses any other value before sending,
 * since the server's 422 for one would read as a missing justification (`createBookingRequest`). */
export interface BookingRequestInput {
  event_id: string
  venue_id: string
  venue_requirement_id?: string
  suitability_override_reason?: string
  setup_minutes?: number
  teardown_minutes?: number
}

/** Story 12.1 AC1-AC4. Story 11.1 AC7: a venue that does not suit, sent without a justification,
 * is refused with a 422 - for instance when it stopped suiting after the step loaded. The code is
 * mapped by status alone, so it assumes `JustificationRequired` is the only 422 the step can meet:
 * give any other 422 here its own code first, or it will be read as a missing justification.
 * f12.1.2: the server also answers 422 for a setup or teardown out of range, which the step
 * refuses before sending (`turnaroundProblem` in src/bookings/turnaround.ts), so it never meets it.
 *
 * Story 12.5 AC3: the notice names the venue and the requirement it was requested for - or says
 * it is an additional venue, when `requirementName` is null. AC11/AC12: a requirement that
 * already has a pending or approved request is refused with a 409 naming its venue. */
export function createBookingRequest(
  input: BookingRequestInput,
  venueName: string,
  requirementName: string | null,
): Promise<Booking> {
  return api<Booking>('/bookings', {
    method: 'POST',
    body: input,
    errorCodes: { 409: 'BOOKING_NOT_ALLOWED', 422: 'BOOKING_JUSTIFICATION_REQUIRED' },
    notify: {
      title: 'Venue requested',
      message: `${venueName} was requested ${requestedFor(requirementName)}; it is with Venue Staff for review.`,
    },
  })
}

/** Story 12.5 AC3: what a request is for, as its notice words it. */
function requestedFor(requirementName: string | null): string {
  return requirementName === null ? 'as an additional venue' : `for ${requirementName}`
}

/** Mirrors `BookingSwitchIn`: the venue a pending request is switched to. Story 11.1:
 * `suitability_override_reason` is why a venue that does not suit is requested. f12.1.2 (story
 * 12.1 AC1): `setup_minutes` and `teardown_minutes` as for `BookingRequestInput` - a switch is a
 * new request, so it carries its own, never the replaced request's. */
export interface BookingSwitchInput {
  venue_id: string
  suitability_override_reason?: string
  setup_minutes?: number
  teardown_minutes?: number
}

/**
 * Story 12.5 (decided 11 Oct 2026): switch the pending request `bookingId` to another venue,
 * for the same venue requirement. The server withdraws it and requests the new venue together,
 * so a refusal - 409 or 422, as for `createBookingRequest` - leaves it as it was. The notice
 * names the new venue, the requirement and the venue it replaces.
 */
export function switchBookingRequest(
  bookingId: string,
  input: BookingSwitchInput,
  venueName: string,
  requirementName: string | null,
  replacedVenueName: string,
): Promise<Booking> {
  return api<Booking>(`/bookings/${bookingId}/switch`, {
    method: 'POST',
    body: input,
    errorCodes: {
      404: 'BOOKING_NOT_FOUND',
      409: 'BOOKING_NOT_ALLOWED',
      422: 'BOOKING_JUSTIFICATION_REQUIRED',
    },
    notify: {
      title: 'Venue switched',
      message: `${venueName} was requested ${requestedFor(requirementName)} in place of ${replacedVenueName}; it is with Venue Staff for review.`,
    },
  })
}

/** Mirrors `BookingReplacementIn`: the venue asked for as the replacement of an approved booking
 * whose venue became unavailable (story 12.6 AC2). Story 11.1: `suitability_override_reason` is why
 * a venue that does not suit is requested. `setup_minutes` and `teardown_minutes` default, when
 * left out, to the original's; a 0 sent is a choice. */
export interface BookingReplacementInput {
  venue_id: string
  suitability_override_reason?: string
  setup_minutes?: number
  teardown_minutes?: number
}

/**
 * Story 12.6 AC2: ask for `venueName` as the replacement of the approved booking `bookingId`, which
 * Venue Staff's closure marked "Venue unavailable". The original stays approved until Venue Staff
 * approve the replacement (AC4). A refusal - 409, or 422 for a venue that does not suit with no
 * justification, as for `createBookingRequest` - writes nothing. The notice names the new venue and
 * the one it replaces.
 */
export function requestReplacementBooking(
  bookingId: string,
  input: BookingReplacementInput,
  venueName: string,
  replacedVenueName: string | null,
): Promise<Booking> {
  return api<Booking>(`/bookings/${bookingId}/replacements`, {
    method: 'POST',
    body: input,
    errorCodes: {
      404: 'BOOKING_NOT_FOUND',
      409: 'BOOKING_NOT_ALLOWED',
      422: 'BOOKING_JUSTIFICATION_REQUIRED',
    },
    notify: {
      title: 'Replacement requested',
      message: `${venueName} was requested to replace ${replacedVenueName ?? 'a booking'}; it is with Venue Staff for review.`,
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
  /** Story 6.2 AC16: when a cancelled booking was cancelled, shown beside its approval; null
   * otherwise, and for one cancelled before that was recorded. */
  cancelled_at: string | null
  /** Story 12.7 AC1: when an approved booking's hold expires, or an expired one's did, and when
   * the event's confirmation completed it. R14: the booked start, which the Approve dialog's
   * expiry may not pass (AC5). */
  hold_expires_at: string | null
  hold_completed_at: string | null
  held_from: string
  /** f12.1.2 (story 12.1 AC17): the setup and teardown, the booked period's end and the venue's
   * opening hours ("HH:MM:SS", null when not recorded, as `Venue` has them), so the card can say
   * when setup or teardown runs outside those hours. */
  setup_minutes: number
  teardown_minutes: number
  held_until: string
  venue_operating_hours_start: string | null
  venue_operating_hours_end: string | null
  /** Story 9.4 AC3: the mark, for Venue Staff deciding the request; null when unmarked. */
  venue_unavailable_marked_at: string | null
  /** Story 12.6 AC3, AC6: for a replacement, the venue it replaces, the venue approving it will
   * release (only while that booking still holds its venue) and whether the original is still
   * marked; null for any other request. */
  replaces_venue_name: string | null
  approval_releases_venue_name: string | null
  original_is_marked: boolean | null
  /** Story 12.6 AC3: when a released original was released - its replacement's approval; null for
   * any other request, one story 19.2 released included. */
  released_at: string | null
}

/** Mirrors `BookingStatusCounts`: how many requests hold each status, whatever tab or page was
 * asked for. */
export interface BookingStatusCounts {
  pending: number
  approved: number
  rejected: number
  withdrawn: number
  cancelled: number
  /** Story 12.7 AC3. */
  expired: number
}

/** Mirrors `BookingQueue`: one page of a queue tab, how many that tab holds, and every status's
 * count for the tab labels. */
export interface BookingQueue {
  items: BookingQueueEntry[]
  total: number
  counts: BookingStatusCounts
}

/** Story 13.3 AC3: the orders the booking queue offers. Mirrors `BookingQueueOrder`. */
export type BookingQueueOrder =
  'date' | 'date_desc' | 'requested' | 'requested_desc' | 'event_name' | 'venue_name'

/** One page of the booking queue to ask for. */
export interface BookingQueueQuery {
  status: BookingStatus | null
  /** Story 13.3 AC2: blank for no search. */
  search: string
  order: BookingQueueOrder
  offset: number
  limit: number
}

/**
 * Story 13.1 AC1-AC3: `'PENDING'` is the pending queue Venue Staff decide from. Story 13.1.2 AC1:
 * any other status is its own tab, and `null` is All. AC4: `limit` requests from the `offset`th
 * on - one numbered page. Story 13.3 AC1-AC4: the tab searched and ordered before it is paged; a
 * blank search is left out, as the spaces around one are (AC5).
 */
export function listBookingRequests(query: BookingQueueQuery): Promise<BookingQueue> {
  const params = new URLSearchParams({
    order: query.order,
    offset: String(query.offset),
    limit: String(query.limit),
  })
  if (query.status !== null) params.set('status', query.status)
  if (query.search.trim() !== '') params.set('search', query.search.trim())
  return api<BookingQueue>(`/bookings?${params}`)
}

/** Story 13.1: the full record behind one queue entry, for the request's detail view. */
export function getBooking(bookingId: string): Promise<Booking> {
  return api<Booking>(`/bookings/${bookingId}`)
}

/** Mirrors `BookingApproval`: when the hold an approval starts expires - a moment with its zone,
 * as `inputToInstant` writes one (story 12.7 AC1, the customer's hold of 12 Oct 2026). */
export interface BookingApprovalInput {
  hold_expires_at: string
}

/** Story 13.2 AC1: approve a pending booking request. AC4: refused (409) on a venue conflict.
 * Story 12.7 AC1/AC5: the approval starts the booking's hold, with the expiry Venue Staff give;
 * 422 for one in the past or after the booked period starts, 409 once the period has started.
 * Each arrives with the backend's own sentence. */
export function approveBooking(
  bookingId: string,
  input: BookingApprovalInput,
  eventName: string,
): Promise<Booking> {
  return api<Booking>(`/bookings/${bookingId}/approve`, {
    method: 'POST',
    body: input,
    errorCodes: {
      404: 'BOOKING_NOT_FOUND',
      409: 'BOOKING_CONFLICT',
      422: 'BOOKING_HOLD_EXPIRY_REFUSED',
    },
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

/** Mirrors `BookingHoldUpdate`: a hold's new expiry - a moment with its zone, as `inputToInstant`
 * writes one - and why it changed (decided 12 Oct 2026). */
export interface BookingHoldUpdateInput {
  hold_expires_at: string
  hold_expiry_change_reason: string
}

/** Story 12.7 AC1/AC7: Venue Staff give an approved booking's open hold a new expiry, with a
 * reason. 422 for one in the past or after the booked period starts (AC5), or with no reason; 409
 * for a booking with no open hold - not approved, an expired one included, or completed by its
 * event's confirmation (AC7); both arrive with the backend's own sentence. */
export function changeHoldExpiry(
  bookingId: string,
  input: BookingHoldUpdateInput,
  eventName: string,
): Promise<Booking> {
  return api<Booking>(`/bookings/${bookingId}`, {
    method: 'PATCH',
    body: input,
    errorCodes: {
      404: 'BOOKING_NOT_FOUND',
      409: 'BOOKING_HOLD_EXPIRY_REFUSED',
      422: 'BOOKING_HOLD_EXPIRY_REFUSED',
    },
    notify: {
      title: 'Hold expiry changed',
      message: `${eventName}'s venue hold has a new expiry; its coordinator has been told.`,
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

/** Mirrors `OrganiserBooking` (fix f7.1.2): one venue booking as the event's organiser reads it -
 * which venue, where, for which requirement and when, without Venue Staff's internal detail. */
export interface OrganiserBooking {
  id: string
  venue_name: string
  venue_location: string
  /** Null for an additional venue (story 12.5 AC5). */
  venue_requirement_name: string | null
  starts_at: string
  ends_at: string
  setup_minutes: number
  teardown_minutes: number
  status: BookingStatus
}

/** Fix f7.1.2 (story 7.1 AC1): the organiser's own event's approved and pending bookings, most
 * recent first. Another organiser's event answers 404 (AC2). */
export function listBookingsForOwnEvent(eventId: string): Promise<OrganiserBooking[]> {
  return api<OrganiserBooking[]>(`/bookings/for-my-event/${eventId}`)
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
  /** Story 6.2 AC16: when a cancelled booking was cancelled; null otherwise. */
  cancelled_at: string | null
  /** Story 11.1 AC6: why a venue that did not suit was requested; null when it suited. */
  suitability_override_reason: string | null
  /** Story 12.7 AC1/AC8: when an approved booking's hold expires, and when it expired once
   * expired; AC4: when the event's confirmation completed it. */
  hold_expires_at: string | null
  hold_completed_at: string | null
  /** Story 12.7 AC7, decided 12 Oct 2026: the latest change to that expiry - why, by whom and
   * when; all null until Venue Staff make one. */
  hold_expiry_change_reason: string | null
  hold_expiry_changed_by: HoldExpiryChangedBy | null
  hold_expiry_changed_at: string | null
  /** Story 9.4 AC3: when the booking was marked "Venue unavailable - alternative needed"; null
   * when unmarked, and always null once the booking is no longer pending or approved. */
  venue_unavailable_marked_at: string | null
  /** Story 12.6 AC2-AC4: the booking this one replaces and the one that replaced it, and their
   * venues: "Replaces <venue>" on a replacement, "Replaced by <venue>" on an original released by
   * an approved one (never for a replacement that was not approved, AC8), and "Replacement
   * requested: <venue>" on an original while one is pending. */
  replaces_booking_id: string | null
  replaced_by_booking_id: string | null
  replaces_venue_name: string | null
  replaced_by_venue_name: string | null
  pending_replacement_venue_name: string | null
  /** Story 12.6 AC3: when an original was released - its replacement's approval, which is when it
   * closed; null for any other booking, one story 19.2 released included. */
  released_at: string | null
}

/** Story 13.2.1 AC4: every venue booking ever raised for this event, most recent first - lets a
 * coordinator read the full history directly on the event page. An event may accumulate more
 * than one row over time (a rejected request followed by a fresh one), so this is a history, not
 * a single outcome; deciding a booking updates that same row in place, it never adds another. */
export function listBookingsForEvent(eventId: string): Promise<BookingOutcome[]> {
  return api<BookingOutcome[]>(`/bookings/for-event/${eventId}`)
}
