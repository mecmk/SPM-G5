import type { BookingStatus } from '../api/bookings'

export type BookingStatusTabKey = 'ALL' | 'PENDING' | 'APPROVED' | 'REJECTED'

const VISIBLE_BOOKING_STATUS_TABS: readonly BookingStatus[] = ['PENDING', 'APPROVED', 'REJECTED']

/**
 * The tab a booking falls under, or `null` when it has no tab of its own (WITHDRAWN, CANCELLED)
 * and only shows up under "All" - mirrors `eventStatusTab`, but unlike events not every status
 * gets a dedicated tab here.
 */
export function bookingStatusTab(status: BookingStatus): BookingStatusTabKey | null {
  return VISIBLE_BOOKING_STATUS_TABS.includes(status) ? (status as BookingStatusTabKey) : null
}

/** Story 13.1: the tab strip for the venue staff booking queue, matching the coordinator's
 * Events inbox tab pattern (story 6.1). */
export const BOOKING_STATUS_TABS: { key: BookingStatusTabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'PENDING', label: 'Pending' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'REJECTED', label: 'Rejected' },
]
