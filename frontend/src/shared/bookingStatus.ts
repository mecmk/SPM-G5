import type { Booking, BookingOutcome, BookingStatus, BookingStatusCounts } from '../api/bookings'
import { UNAVAILABILITY_REASON_NAMES } from '../api/venues'
import { formatTime, NONE } from './format'

export type BookingStatusTabKey =
  'ALL' | 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED' | 'CANCELLED'

/** The one status Venue Staff can still decide: the queue card and detail page offer Approve /
 * Reject only for it. */
export const PENDING_BOOKING_STATUS: BookingStatus = 'PENDING'
export const APPROVED_BOOKING_STATUS: BookingStatus = 'APPROVED'

/** Story 12.6 AC2-AC4, kept by story 9.5 AC7: how every page words a replacement raised before
 * 9.5 - on the replacement ("Replaces"), on the original once an approved replacement released it
 * ("Replaced by"), and on the original while one is pending. AC3: what Venue Staff are told
 * approving will release. */
export function replacesLine(venueName: string): string {
  return `Replaces ${venueName}`
}
export function replacedByLine(venueName: string): string {
  return `Replaced by ${venueName}`
}
export function replacementRequestedLine(venueName: string): string {
  return `Replacement requested: ${venueName}`
}
export function approvalReleasesLine(venueName: string): string {
  return `Approving this releases ${venueName}`
}
/** Story 21.3 AC2: how the event page and Venue Staff's pages say a booking the Safety Officer's
 * finding named was released, and what the event page adds to that. */
export const RELEASED_BY_SAFETY_REVIEW_LABEL = 'Released by the safety review'
export const RELEASED_BY_SAFETY_REVIEW_MESSAGE =
  'The Safety Officer released this booking, so the venue is free for other events.'

/** Story 21.3 AC2: whether the safety review released this booking. */
export function isReleasedBySafetyReview(booking: Pick<Booking, 'release_cause'>): boolean {
  return booking.release_cause === 'SAFETY_REVIEW'
}

/** Story 12.8 AC2: how the event page and Venue Staff's pages say a booking its coordinator
 * cancelled was released, and what the event page adds to that. */
export const CANCELLED_BY_COORDINATOR_LABEL = 'Cancelled by the coordinator'
export const CANCELLED_BY_COORDINATOR_MESSAGE =
  'The coordinator cancelled this booking, so the venue is free for other events.'

/** Story 12.8 AC2: whether the event's coordinator cancelled this booking. */
export function isCancelledByCoordinator(booking: Pick<Booking, 'release_cause'>): boolean {
  return booking.release_cause === 'COORDINATOR_CANCELLED'
}

/** Story 9.5 AC2: how the event page and Venue Staff's pages say a booking a venue closure
 * cancelled was released, and what the event page adds to that. */
export const CANCELLED_BY_CLOSURE_LABEL = 'Cancelled: the venue closed'
export const CANCELLED_BY_CLOSURE_MESSAGE =
  'A closure of the venue cancelled this booking, so the venue is free for other events.'

/** Story 9.5 AC2: whether a venue closure cancelled this booking. */
export function isCancelledByClosure(booking: Pick<Booking, 'release_cause'>): boolean {
  return booking.release_cause === 'VENUE_UNAVAILABLE'
}

/** Story 9.5 AC2: "Reason: Maintenance", the closure's reason as the calendar names it, for a
 * booking a closure cancelled; null for any other. A request a closure rejected says its reason
 * as its decision reason, "Venue closed: Maintenance". */
export function closureReasonLine(
  booking: Pick<Booking, 'release_cause' | 'closure_reason'>,
): string | null {
  if (!isCancelledByClosure(booking) || booking.closure_reason === null) return null
  return `Reason: ${UNAVAILABILITY_REASON_NAMES[booking.closure_reason]}`
}

/** Story 21.3 AC2, story 12.8 AC2, story 9.5 AC2: the line naming who released a closed booking,
 * for the releases that record why in their own words or by their closure; null for any other
 * booking. */
export function releasedByLabel(booking: Pick<Booking, 'release_cause'>): string | null {
  if (isReleasedBySafetyReview(booking)) return RELEASED_BY_SAFETY_REVIEW_LABEL
  if (isCancelledByCoordinator(booking)) return CANCELLED_BY_COORDINATOR_LABEL
  if (isCancelledByClosure(booking)) return CANCELLED_BY_CLOSURE_LABEL
  return null
}

/** Story 21.3 AC2, story 12.8 AC2: why a closed booking was closed, as its page words it - the
 * finding's required change for a booking the safety review released, the coordinator's reason
 * for one they cancelled, otherwise the decision's own reason. Null for a booking a closure
 * cancelled, whose reason is `closureReasonLine`'s. */
export function closingReason(
  booking: Pick<Booking, 'decision_reason' | 'release_cause' | 'release_reason'>,
): string | null {
  if (isCancelledByClosure(booking)) return null
  return releasedByLabel(booking) !== null ? booking.release_reason : booking.decision_reason
}

/** "None", "1 hr", "1 hr 30 min" or "45 min" - the setup/teardown line's duration wording, and
 * f12.1.3's (story 12.1 AC18/AC19) for a setup or teardown against the venue's default. */
export function formatMinutesDuration(minutes: number): string {
  if (minutes === 0) return NONE
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  const parts: string[] = []
  if (hours > 0) parts.push(`${hours} hr${hours > 1 ? 's' : ''}`)
  if (remainder > 0) parts.push(`${remainder} min`)
  return parts.join(' ')
}

/** Story 12.1 AC1/AC17, and story 21.3 AC1: the line that says what a booking's period is made of -
 * "Setup: 30 min · Event: 09:00–17:00 · Teardown: None" - on the event page's booking card and
 * under each booking the Safety Officer may release. */
export function turnaroundLine(
  booking: Pick<Booking, 'setup_minutes' | 'teardown_minutes' | 'starts_at' | 'ends_at'>,
): string {
  const event = `${formatTime(booking.starts_at)}–${formatTime(booking.ends_at)}`
  return `Setup: ${formatMinutesDuration(booking.setup_minutes)} · Event: ${event} · Teardown: ${formatMinutesDuration(booking.teardown_minutes)}`
}

/** Fix f13.2.1.1 (13.2.1 AC7): the booked venue's capacity on the event page's booking cards -
 * "Capacity: 400 people" - with the booked layout's own when the venue gives it one:
 * "Capacity: 400 people · Theatre layout: 350 people". */
export function capacityLine(
  booking: Pick<BookingOutcome, 'venue_capacity' | 'layout_name' | 'layout_capacity'>,
): string {
  const venue = `Capacity: ${booking.venue_capacity} people`
  if (booking.layout_name === null || booking.layout_capacity === null) return venue
  return `${venue} · ${booking.layout_name} layout: ${booking.layout_capacity} people`
}

/** Story 12.7 AC3: an approved booking whose hold lapsed before its event was confirmed. */
export const EXPIRED_BOOKING_STATUS: BookingStatus = 'EXPIRED'

/** Story 12.7 AC1: how every page names an open hold's expiry - the queue card, the request's
 * page, the event page and the calendar's day row - and AC3/AC8: an expired one's. */
export const HOLD_EXPIRES_LABEL = 'Hold expires'
export const HOLD_EXPIRED_LABEL = 'Expired at'

/** Story 12.7 AC1/AC4: when an approved booking's hold expires, while it is open - not yet
 * completed by its event's confirmation, nor a booking approved before holds expired (no expiry).
 * Null for any other booking. */
export function openHoldExpiry(
  booking: Pick<Booking, 'status' | 'hold_expires_at' | 'hold_completed_at'>,
): string | null {
  if (booking.status !== 'APPROVED' || booking.hold_completed_at !== null) return null
  return booking.hold_expires_at
}

/** Statuses nobody on staff decided: the coordinator withdrew the request, or the system
 * cancelled it (migration 010 cancelled overlapping pending requests, stamping `decided_at` and a
 * note of its own). */
const CLOSED_WITHOUT_DECISION: readonly BookingStatus[] = ['WITHDRAWN', 'CANCELLED']

/** Story 13.1.2 AC3: the label of why a booking was decided or closed. Fix f7.1.3 (AC10): also of
 * why the organiser's released or cancelled booking was released. */
export const REASON_LABEL = 'Reason'

/** How to label a finished request's `decided_at` and `decision_reason`. */
export interface BookingOutcomeLabels {
  when: string
  why: string
}

/** Story 13.1.2 AC3: "Decided at" / "Reason" for a staff decision; "Closed at" / "Note" for a
 * request that was withdrawn or cancelled, so it does not read as if staff decided it. Story 12.7
 * AC8: "Approved at" for an expired booking, whose `decided_at` is its approval - it expired at
 * `hold_expires_at`, shown beside it as `HOLD_EXPIRED_LABEL`. Story 6.2 AC16: the same for a
 * booking cancelled since `cancelled_at` was recorded - its `decided_at` is its approval, and
 * `cancelled_at` is shown beside it as `CANCELLED_AT_LABEL`. */
export function bookingOutcomeLabels(
  booking: Pick<Booking, 'status' | 'cancelled_at'>,
): BookingOutcomeLabels {
  if (booking.status === EXPIRED_BOOKING_STATUS) return { when: 'Approved at', why: REASON_LABEL }
  if (booking.status === 'CANCELLED' && booking.cancelled_at !== null) {
    return { when: 'Approved at', why: REASON_LABEL }
  }
  return CLOSED_WITHOUT_DECISION.includes(booking.status)
    ? { when: 'Closed at', why: 'Note' }
    : { when: 'Decided at', why: REASON_LABEL }
}

/** Story 12.6 AC3: when a withdrawn or cancelled request closed - the release, for an original a
 * replacement's approval released, which is later than the approval `decided_at` still holds. For
 * a booking story 19.2 released there is no release time, so this is its `decided_at`, which is
 * its approval. */
export function closedAt(request: { decided_at: string | null; released_at: string | null }) {
  return request.released_at ?? request.decided_at
}

/** Story 13.1.2 AC1: the tab strip for the venue staff booking queue, matching the coordinator's
 * Events inbox tab pattern (story 6.1). WITHDRAWN has no tab of its own and only shows up under
 * "All". Story 12.7 AC3: a booking whose hold expired leaves Approved for a tab of its own. Story
 * 6.2 AC14: so does a cancelled one, read-only. Story 15.2.1 AC2: each tab's hint, the page's
 * subtitle while it is open, saying what it holds. */
export const BOOKING_STATUS_TABS: { key: BookingStatusTabKey; label: string; hint: string }[] = [
  {
    key: 'ALL',
    label: 'All',
    hint: 'Every booking request, including ones the coordinator withdrew, which have no tab of their own.',
  },
  {
    key: 'PENDING',
    label: 'Pending',
    hint: 'Waiting for a decision. A pending request already holds its venue.',
  },
  {
    key: 'APPROVED',
    label: 'Approved',
    hint: 'Approved. The hold keeps the venue until it expires, unless the event is confirmed first.',
  },
  { key: 'REJECTED', label: 'Rejected', hint: 'Rejected, with the reason given.' },
  {
    key: 'EXPIRED',
    label: 'Expired',
    hint: 'Approved, but the hold expired before the event was confirmed, so the venue was released. Read-only.',
  },
  {
    key: 'CANCELLED',
    label: 'Cancelled',
    hint: 'Released because the event was cancelled, a change to it no longer fit, a replacement venue was approved, a safety review released it, the coordinator cancelled it, or the venue closed. Read-only.',
  },
]

/** The status a tab asks the backend for, or `null` for "All". */
export function bookingTabStatus(tab: BookingStatusTabKey): BookingStatus | null {
  return tab === 'ALL' ? null : tab
}

/** How many requests a tab holds, from the backend's per-status counts. */
export function bookingTabCount(tab: BookingStatusTabKey, counts: BookingStatusCounts): number {
  switch (tab) {
    case 'ALL':
      return (
        counts.pending +
        counts.approved +
        counts.rejected +
        counts.withdrawn +
        counts.cancelled +
        counts.expired
      )
    case 'PENDING':
      return counts.pending
    case 'APPROVED':
      return counts.approved
    case 'REJECTED':
      return counts.rejected
    case 'EXPIRED':
      return counts.expired
    case 'CANCELLED':
      return counts.cancelled
  }
}

/** `counts` with one request moved from `from` to `to` - a decision just made on the page. */
export function withBookingMoved(
  counts: BookingStatusCounts,
  from: BookingStatus,
  to: BookingStatus,
): BookingStatusCounts {
  const key = (status: BookingStatus) => status.toLowerCase() as keyof BookingStatusCounts
  const moved = { ...counts, [key(from)]: counts[key(from)] - 1 }
  return { ...moved, [key(to)]: moved[key(to)] + 1 }
}
