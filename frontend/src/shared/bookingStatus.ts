import type { BookingStatus, BookingStatusCounts } from '../api/bookings'

export type BookingStatusTabKey = 'ALL' | 'PENDING' | 'APPROVED' | 'REJECTED'

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
