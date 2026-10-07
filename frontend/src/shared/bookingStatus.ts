import type { BookingStatus, BookingStatusCounts } from '../api/bookings'

export type BookingStatusTabKey = 'ALL' | 'PENDING' | 'APPROVED' | 'REJECTED'

/** The one status Venue Staff can still decide: the queue card and detail page offer Approve /
 * Reject only for it. */
export const PENDING_BOOKING_STATUS: BookingStatus = 'PENDING'

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
 * request that was withdrawn or cancelled, so it does not read as if staff decided it. */
export function bookingOutcomeLabels(status: BookingStatus): BookingOutcomeLabels {
  return CLOSED_WITHOUT_DECISION.includes(status)
    ? { when: 'Closed at', why: 'Note' }
    : { when: 'Decided at', why: 'Reason' }
}

/** Story 13.1.2 AC1: the tab strip for the venue staff booking queue, matching the coordinator's
 * Events inbox tab pattern (story 6.1). WITHDRAWN and CANCELLED have no tab of their own and
 * only show up under "All". */
export const BOOKING_STATUS_TABS: { key: BookingStatusTabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'PENDING', label: 'Pending' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'REJECTED', label: 'Rejected' },
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
        counts.pending + counts.approved + counts.rejected + counts.withdrawn + counts.cancelled
      )
    case 'PENDING':
      return counts.pending
    case 'APPROVED':
      return counts.approved
    case 'REJECTED':
      return counts.rejected
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
