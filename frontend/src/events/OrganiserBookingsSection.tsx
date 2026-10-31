import { useCallback } from 'react'
import { listBookingsForOwnEvent } from '../api/bookings'
import { Chip } from '../components/Chip'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import {
  HOLD_EXPIRES_LABEL,
  openHoldExpiry,
  turnaroundLine,
  VENUE_UNAVAILABLE_LABEL,
} from '../shared/bookingStatus'
import {
  ADDITIONAL_VENUE,
  formatDate,
  formatDateTime,
  formatSchedule,
  formatTime,
} from '../shared/format'
import { FLAGGED_BY_SAFETY_REVIEW } from '../shared/safetyReview'
import { useLoaded } from '../shared/useLoaded'
import { BOOKING_OUTCOME, OPEN_HOLD_MESSAGE, VENUE_UNAVAILABLE_NOTE } from './bookingOutcome'

export interface OrganiserBookingsSectionProps {
  eventId: string
  /** AC9 (CL-184): the latest safety review flags the event's venue bookings (21.2 AC4). */
  isFlagged: boolean
}

/**
 * Fix f7.1.2 (story 7.1 AC1): the organiser's read-only view of their event's approved and
 * pending venue bookings, drawn as the coordinator's Venue booking cards are - venue, the
 * requirement it is for, location, dates and times, status - without the coordinator's actions,
 * decisions or who changed a hold. Organisers hold `bookings:read_own`, not `bookings:read`.
 *
 * CL-184: AC4 a booking over more than one day names both dates, as the event's schedule does
 * (f7.1.1); AC7 an open hold reads as held, not confirmed, with when it expires, and a booking
 * marked under 9.4 says so; AC9 the section is flagged when the safety review flags venue bookings.
 */
export function OrganiserBookingsSection({ eventId, isFlagged }: OrganiserBookingsSectionProps) {
  const loadBookings = useCallback(() => listBookingsForOwnEvent(eventId), [eventId])
  const { data: bookings, error } = useLoaded(loadBookings)

  return (
    <section
      className={`card stack${isFlagged ? ' card-flagged' : ''}`}
      aria-labelledby="organiser-bookings-heading"
    >
      <h2 id="organiser-bookings-heading" className="cluster">
        <Icon name="building" size={20} />
        Venue bookings
      </h2>
      {isFlagged && <p className="flag-note">{FLAGGED_BY_SAFETY_REVIEW}</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {bookings !== null && bookings.length === 0 && (
        <EmptyState>No venue has been booked for this event yet.</EmptyState>
      )}
      {bookings !== null && bookings.length > 0 && (
        <ul className="booking-outcome-list">
          {bookings.map((booking) => {
            const bookingOutcome = BOOKING_OUTCOME[booking.status]
            const openHold = openHoldExpiry(booking)
            const isOverOneDay = formatDate(booking.starts_at) !== formatDate(booking.ends_at)
            return (
              <li
                key={booking.id}
                className={`booking-outcome-card booking-outcome-card-${bookingOutcome.tone}`}
              >
                <div className="booking-outcome-main">
                  <div className="booking-outcome-thumb" aria-hidden="true">
                    <Icon name="image" size={28} />
                  </div>

                  <div className="booking-outcome-body">
                    <div className="booking-outcome-heading-row">
                      <p className="stat-card-value">{booking.venue_name}</p>
                      <span
                        className={`booking-status-pill booking-status-pill-${bookingOutcome.tone}`}
                      >
                        <Icon name={bookingOutcome.icon} size={14} />
                        {bookingOutcome.label}
                      </span>
                    </div>
                    <p className="booking-outcome-purpose">
                      {booking.venue_requirement_name === null
                        ? ADDITIONAL_VENUE
                        : `For ${booking.venue_requirement_name}`}
                    </p>
                    <p className="muted">{booking.venue_location}</p>
                    <div className="booking-outcome-schedule small muted">
                      {isOverOneDay ? (
                        <span className="booking-outcome-schedule-item">
                          <Icon name="calendar" size={14} />
                          {formatSchedule(booking.starts_at, booking.ends_at)}
                        </span>
                      ) : (
                        <>
                          <span className="booking-outcome-schedule-item">
                            <Icon name="calendar" size={14} />
                            {formatDate(booking.starts_at)}
                          </span>
                          <span className="booking-outcome-schedule-item">
                            <Icon name="calendar-check" size={14} />
                            {formatTime(booking.starts_at)}–{formatTime(booking.ends_at)}
                          </span>
                        </>
                      )}
                    </div>
                    <p className="small muted">{turnaroundLine(booking)}</p>
                  </div>
                </div>

                <div className="booking-outcome-message">
                  <Icon name={bookingOutcome.icon} size={18} />
                  <div>
                    <p>{openHold ? OPEN_HOLD_MESSAGE : bookingOutcome.message}</p>
                    {booking.venue_unavailable_marked_at !== null && (
                      <p>
                        <Chip tone="warning" label={VENUE_UNAVAILABLE_LABEL} />
                        <br />
                        <span className="small muted">{VENUE_UNAVAILABLE_NOTE}</span>
                      </p>
                    )}
                    {openHold && (
                      <p>
                        <span className="fact-label">{HOLD_EXPIRES_LABEL}</span>
                        <br />
                        {formatDateTime(openHold)}
                      </p>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
