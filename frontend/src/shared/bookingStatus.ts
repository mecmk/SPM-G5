import type { Booking, BookingStatus, BookingStatusCounts } from '../api/bookings'
import { formatTime, NONE } from './format'

export type BookingStatusTabKey =
  'ALL' | 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED' | 'CANCELLED'

/** The one status Venue Staff can still decide: the queue card and detail page offer Approve /
 * Reject only for it. */
export const PENDING_BOOKING_STATUS: BookingStatus = 'PENDING'
export const APPROVED_BOOKING_STATUS: BookingStatus = 'APPROVED'

/** Story 9.4 AC3: how every page names a booking whose venue was marked unavailable for part of
 * its held period - the event's page, Venue Staff's queue card and the request's own page. */
export const VENUE_UNAVAILABLE_LABEL = 'Venue unavailable – alternative needed'

/** Story 12.6 AC1/AC9: the event page's way to a replacement for an approved marked booking, and
 * for a marked pending one (which is switched to another venue, 12.5) the way to the catalogue. */
export const FIND_REPLACEMENT_LABEL = 'Find a replacement venue'
export const FIND_ANOTHER_LABEL = 'Find another venue'

/** Story 12.6 AC2-AC4: how every page words a replacement - on the replacement ("Replaces"), on
 * the original once an approved replacement released it ("Replaced by"), on the original while one
 * is pending, and in the banner for a marked requirement. AC3: what Venue Staff are told approving
 * will release; AC1: the banner of the catalogue opened to replace a booking. */
export function replacesLine(venueName: string): string {
  return `Replaces ${venueName}`
}
export function replacedByLine(venueName: string): string {
  return `Replaced by ${venueName}`
}
export function replacementRequestedLine(venueName: string): string {
  return `Replacement requested: ${venueName}`
}
export function venueUnavailableLine(venueName: string): string {
  return `Venue unavailable: ${venueName}`
}
export function approvalReleasesLine(venueName: string): string {
  return `Approving this releases ${venueName}`
}
export function replacingLine(venueName: string): string {
  return `Replacing ${venueName}`
}
/** Story 12.6 AC10: what the catalogue says for an address that names a booking which already has
 *  a replacement pending, so no second one is offered. */
export function replacementAlreadyRequestedLine(venueName: string): string {
  return `${replacementRequestedLine(venueName)}. Withdraw it from the event page before asking for another.`
}
/** Story 12.6 AC1/AC9: what the catalogue says for an address that names a booking which is not
 *  an approved, marked booking any more, so it replaces nothing. */
export const NO_LONGER_REPLACEABLE_LINE = 'That booking is no longer waiting for a replacement.'

/** Story 21.3 AC2: how the event page and Venue Staff's pages say a booking the Safety Officer's
 * finding named was released, and what the event page adds to that. */
export const RELEASED_BY_SAFETY_REVIEW_LABEL = 'Released by the safety review'
export const RELEASED_BY_SAFETY_REVIEW_MESSAGE =
  'The Safety Officer released this booking, so the venue is free for other events.'

/** Story 21.3 AC2: whether the safety review released this booking. */
export function isReleasedBySafetyReview(booking: Pick<Booking, 'release_cause'>): boolean {
  return booking.release_cause === 'SAFETY_REVIEW'
}

/** Story 21.3 AC2: why a closed booking was closed, as its page words it - the finding's required
 * change for a booking the safety review released, otherwise the decision's own reason. */
export function closingReason(
  booking: Pick<Booking, 'decision_reason' | 'release_cause' | 'release_reason'>,
): string | null {
  return isReleasedBySafetyReview(booking) ? booking.release_reason : booking.decision_reason
}

/** "None", "1 hr", "1 hr 30 min" or "45 min" - the setup/teardown line's duration wording. */
function formatMinutesDuration(minutes: number): string {
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
  if (booking.status === EXPIRED_BOOKING_STATUS) return { when: 'Approved at', why: 'Reason' }
  if (booking.status === 'CANCELLED' && booking.cancelled_at !== null) {
    return { when: 'Approved at', why: 'Reason' }
  }
  return CLOSED_WITHOUT_DECISION.includes(booking.status)
    ? { when: 'Closed at', why: 'Note' }
    : { when: 'Decided at', why: 'Reason' }
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
 * 6.2 AC14: so does a cancelled one, read-only. */
export const BOOKING_STATUS_TABS: { key: BookingStatusTabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'PENDING', label: 'Pending' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'REJECTED', label: 'Rejected' },
  { key: 'EXPIRED', label: 'Expired' },
  { key: 'CANCELLED', label: 'Cancelled' },
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
