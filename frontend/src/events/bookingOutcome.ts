import type { BookingStatus } from '../api/bookings'
import type { IconName } from '../components/Icon'

/** Story 13.2.1 AC4: how each venue booking outcome reads on the event page - label, colour,
 * icon and the status sentence, matching the wording a Venue Staff decision already produces. */
export interface BookingOutcomePresentation {
  label: string
  tone: 'success' | 'warning' | 'danger' | 'neutral'
  icon: IconName
  message: string
}

export const BOOKING_OUTCOME: Record<BookingStatus, BookingOutcomePresentation> = {
  APPROVED: {
    label: 'Approved',
    tone: 'success',
    icon: 'check-circle',
    message: 'This venue booking has been approved and the venue is confirmed for this event.',
  },
  PENDING: {
    label: 'Pending',
    tone: 'warning',
    icon: 'clock',
    message: 'Awaiting review by Venue Staff.',
  },
  REJECTED: {
    label: 'Rejected',
    tone: 'danger',
    icon: 'x-circle',
    message: 'This booking request was rejected.',
  },
  WITHDRAWN: {
    label: 'Withdrawn',
    tone: 'neutral',
    icon: 'x-circle',
    message: 'This booking request was withdrawn.',
  },
  CANCELLED: {
    label: 'Cancelled',
    tone: 'neutral',
    icon: 'x-circle',
    message: 'This booking was cancelled.',
  },
  // Story 12.7 AC8: kept as history once its hold lapsed.
  EXPIRED: {
    label: 'Expired',
    tone: 'neutral',
    icon: 'clock',
    message:
      "This booking's hold expired before the event was confirmed, so the venue was released.",
  },
}

/** "None", "1 hr", "1 hr 30 min" or "45 min" - the setup/teardown line's duration wording. */
export function formatMinutesDuration(minutes: number): string {
  if (minutes === 0) return 'None'
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  const parts: string[] = []
  if (hours > 0) parts.push(`${hours} hr${hours > 1 ? 's' : ''}`)
  if (remainder > 0) parts.push(`${remainder} min`)
  return parts.join(' ')
}
