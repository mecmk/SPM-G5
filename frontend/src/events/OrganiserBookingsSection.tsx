import { useCallback } from 'react'
import { listBookingsForOwnEvent } from '../api/bookings'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { ADDITIONAL_VENUE, formatDate, formatTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { BOOKING_OUTCOME, formatMinutesDuration } from './bookingOutcome'

export interface OrganiserBookingsSectionProps {
  eventId: string
}

/**
 * Fix f7.1.2 (story 7.1 AC1): the organiser's read-only view of their event's approved and
 * pending venue bookings, drawn as the coordinator's Venue booking cards are - venue, the
 * requirement it is for, location, dates and times, status - without the coordinator's actions,
 * decisions or hold details. Organisers hold `bookings:read_own`, not `bookings:read`.
 */
export function OrganiserBookingsSection({ eventId }: OrganiserBookingsSectionProps) {
  const loadBookings = useCallback(() => listBookingsForOwnEvent(eventId), [eventId])
  const { data: bookings, error } = useLoaded(loadBookings)

  return (
    <section className="card stack" aria-labelledby="organiser-bookings-heading">
      <h2 id="organiser-bookings-heading" className="cluster">
        <Icon name="building" size={20} />
        Venue bookings
      </h2>
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
                      <span className="booking-outcome-schedule-item">
                        <Icon name="calendar" size={14} />
                        {formatDate(booking.starts_at)}
                      </span>
                      <span className="booking-outcome-schedule-item">
                        <Icon name="calendar-check" size={14} />
                        {formatTime(booking.starts_at)}–{formatTime(booking.ends_at)}
                      </span>
                    </div>
                    <p className="small muted">
                      Setup: {formatMinutesDuration(booking.setup_minutes)} · Event:{' '}
                      {formatTime(booking.starts_at)}–{formatTime(booking.ends_at)} · Teardown:{' '}
                      {formatMinutesDuration(booking.teardown_minutes)}
                    </p>
                  </div>
                </div>

                <div className="booking-outcome-message">
                  <Icon name={bookingOutcome.icon} size={18} />
                  <p>{bookingOutcome.message}</p>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
