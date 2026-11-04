import { useCallback } from 'react'
import { listBookingsForOwnEvent, type OrganiserBooking } from '../api/bookings'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import {
  CANCELLED_BY_CLOSURE_MESSAGE,
  CANCELLED_BY_COORDINATOR_MESSAGE,
  closureReasonLine,
  HOLD_EXPIRES_LABEL,
  isCancelledByClosure,
  isCancelledByCoordinator,
  isReleasedBySafetyReview,
  openHoldExpiry,
  REASON_LABEL,
  releasedByLabel,
  RELEASED_BY_SAFETY_REVIEW_MESSAGE,
  turnaroundLine,
} from '../shared/bookingStatus'
import {
  ADDITIONAL_VENUE,
  formatDate,
  formatDateTime,
  formatSchedule,
  formatTime,
  isMultiDay,
} from '../shared/format'
import { FLAGGED_BY_SAFETY_REVIEW } from '../shared/safetyReview'
import { useLoaded } from '../shared/useLoaded'
import { BOOKING_OUTCOME, OPEN_HOLD_MESSAGE } from './bookingOutcome'
import { BookingVenueThumb } from './BookingVenueThumb'

export interface OrganiserBookingsSectionProps {
  eventId: string
  /** AC9 (CL-184): the latest safety review flags the event's venue bookings (21.2 AC4). */
  isFlagged: boolean
}

/** Fix f7.1.3 (AC10): a booking the safety review released, the coordinator cancelled or a venue
 * closure cancelled says which, as the coordinator's card does; any other says what its status
 * means. */
function bookingMessage(booking: OrganiserBooking): string {
  if (isReleasedBySafetyReview(booking)) return RELEASED_BY_SAFETY_REVIEW_MESSAGE
  if (isCancelledByCoordinator(booking)) return CANCELLED_BY_COORDINATOR_MESSAGE
  if (isCancelledByClosure(booking)) return CANCELLED_BY_CLOSURE_MESSAGE
  return BOOKING_OUTCOME[booking.status].message
}

/**
 * Fix f7.1.2 (story 7.1 AC1): the organiser's read-only view of their event's approved and
 * pending venue bookings, drawn as the coordinator's Venue booking cards are - venue, the
 * requirement it is for, location, dates and times, status - without the coordinator's actions,
 * decisions or who changed a hold. Organisers hold `bookings:read_own`, not `bookings:read`.
 *
 * CL-184: AC4 a booking over more than one day names both dates, as the event's schedule does
 * (f7.1.1); AC7 an open hold reads as held, not confirmed, with when it expires; AC9 the section
 * is flagged when the safety review flags venue bookings.
 *
 * Fix f7.1.3 (AC10): a booking the safety review released, the coordinator cancelled or a venue
 * closure cancelled stays as a Cancelled card saying which and why - the closure's reason, never
 * its description - but not who.
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
            const isOverOneDay = isMultiDay(booking.starts_at, booking.ends_at)
            return (
              <li
                key={booking.id}
                className={`booking-outcome-card booking-outcome-card-${bookingOutcome.tone}`}
              >
                <div className="booking-outcome-main">
                  <BookingVenueThumb coverUrl={booking.venue_cover_image_url} />

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
                    <p>{openHold ? OPEN_HOLD_MESSAGE : bookingMessage(booking)}</p>
                    {releasedByLabel(booking) !== null && (
                      <p>
                        <strong>{releasedByLabel(booking)}</strong>
                      </p>
                    )}
                    {booking.release_reason !== null && (
                      <p>
                        <span className="fact-label">{REASON_LABEL}</span>
                        <br />
                        {booking.release_reason}
                      </p>
                    )}
                    {closureReasonLine(booking) !== null && <p>{closureReasonLine(booking)}</p>}
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
