import type { Booking, BookingStatus, BookingStatusCounts } from '../api/bookings'

export type BookingStatusTabKey = 'ALL' | 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED'

/** The one status Venue Staff can still decide: the queue card and detail page offer Approve /
 * Reject only for it. */
export const PENDING_BOOKING_STATUS: BookingStatus = 'PENDING'

/** Story 9.4 AC3: how every page names a booking whose venue was marked unavailable for part of
 * its held period - the event's page, Venue Staff's queue card and the request's own page. */
export const VENUE_UNAVAILABLE_LABEL = 'Venue unavailable – alternative needed'

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
 * `hold_expires_at`, shown beside it as `HOLD_EXPIRED_LABEL`. */
export function bookingOutcomeLabels(status: BookingStatus): BookingOutcomeLabels {
  if (status === EXPIRED_BOOKING_STATUS) return { when: 'Approved at', why: 'Reason' }
  return CLOSED_WITHOUT_DECISION.includes(status)
    ? { when: 'Closed at', why: 'Note' }
    : { when: 'Decided at', why: 'Reason' }
}

/** Story 13.1.2 AC1: the tab strip for the venue staff booking queue, matching the coordinator's
 * Events inbox tab pattern (story 6.1). WITHDRAWN and CANCELLED have no tab of their own and
 * only show up under "All". Story 12.7 AC3: a booking whose hold expired leaves Approved for a
 * tab of its own. */
export const BOOKING_STATUS_TABS: { key: BookingStatusTabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'PENDING', label: 'Pending' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'REJECTED', label: 'Rejected' },
  { key: 'EXPIRED', label: 'Expired' },
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
