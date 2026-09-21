import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { getBooking, type Booking } from '../api/bookings'
import { formatApiError } from '../api/client'
import { getEvent, type EventDetail } from '../api/events'
import { getVenue, type Venue } from '../api/venues'
import { Chip } from '../components/Chip'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { BOOKING_REQUESTS_PATH } from '../routes'
import { formatDate, formatTime } from '../shared/format'

const NOT_RECORDED = 'Not recorded'

function layoutName(venue: Venue, layoutCode: string | null): string {
  if (layoutCode === null) return 'Any'
  return venue.layouts.find((layout) => layout.code === layoutCode)?.name ?? layoutCode
}

/**
 * Story 13.1 - a pending booking request's full detail, read-only.
 * AC2: event name, requested venue, period, expected attendance and stated requirements, laid
 * out in full rather than the queue card's summary.
 *
 * Composes three already-existing reads (the booking itself, its venue, its event) rather than
 * a dedicated endpoint: Venue Staff already holds BOOKINGS_READ, VENUES_READ and
 * EVENTS_READ_ALL, so nothing new is needed on the backend for this view.
 *
 * Approve/reject (stories 13.2/13.3) are this page's next addition, sitting below the
 * Requirements section - this page deliberately renders no action for them yet.
 */
export function BookingRequestDetailPage() {
  const { bookingId = '' } = useParams()
  const [booking, setBooking] = useState<Booking | null>(null)
  const [venue, setVenue] = useState<Venue | null>(null)
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getBooking(bookingId)
      .then((bookingData) =>
        Promise.all([getVenue(bookingData.venue_id), getEvent(bookingData.event_id)]).then(
          ([venueData, eventData]) => {
            if (cancelled) return
            setBooking(bookingData)
            setVenue(venueData)
            setEvent(eventData)
          },
        ),
      )
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [bookingId])

  if (error) {
    return (
      <div className="page">
        <p role="alert" className="error">
          {error}
        </p>
      </div>
    )
  }
  if (!booking || !venue || !event) return <LoadingState label="Loading the booking request…" />

  return (
    <div className="page page-wide">
      <Link to={BOOKING_REQUESTS_PATH} className="back-link">
        ← Booking Requests
      </Link>

      <div className="item-card-header">
        <h1>{event.name}</h1>
        <StatusBadge status={booking.status} />
      </div>

      <div className="stack">
        <section className="card stack" aria-labelledby="booking-event-heading">
          <p className="eyebrow" id="booking-event-heading">
            Event information
          </p>
          <ul className="check-list">
            <li>
              <span className="grow-text">Event name</span>
              <span>{event.name}</span>
            </li>
            <li>
              <span className="grow-text">Organiser</span>
              <span>{event.organiser_name}</span>
            </li>
            <li>
              <span className="grow-text">Purpose</span>
              <span>{event.purpose ?? NOT_RECORDED}</span>
            </li>
            <li>
              <span className="grow-text">Description</span>
              <span>{event.description ?? NOT_RECORDED}</span>
            </li>
            <li>
              <span className="grow-text">Expected attendance</span>
              <span className="mono">{booking.expected_attendance}</span>
            </li>
          </ul>
        </section>

        <section className="card stack" aria-labelledby="booking-request-heading">
          <p className="eyebrow" id="booking-request-heading">
            Requested booking
          </p>
          <ul className="check-list">
            <li>
              <span className="grow-text">Venue</span>
              <span>{venue.name}</span>
            </li>
            <li>
              <span className="grow-text">Date</span>
              <span>{formatDate(booking.starts_at)}</span>
            </li>
            <li>
              <span className="grow-text">Start time</span>
              <span>{formatTime(booking.starts_at)}</span>
            </li>
            <li>
              <span className="grow-text">End time</span>
              <span>{formatTime(booking.ends_at)}</span>
            </li>
          </ul>
        </section>

        <section className="card stack" aria-labelledby="booking-requirements-heading">
          <p className="eyebrow" id="booking-requirements-heading">
            Requirements
          </p>
          <ul className="check-list">
            <li>
              <span className="grow-text">Room layout</span>
              <span>{layoutName(venue, booking.required_layout_code)}</span>
            </li>
            <li>
              <span className="grow-text">Other requirements</span>
              <span>{booking.requirement_notes ?? NOT_RECORDED}</span>
            </li>
          </ul>
          <p className="eyebrow">Required facilities</p>
          <div className="cluster">
            {event.required_facilities.length === 0 && <p className="muted">{NOT_RECORDED}</p>}
            {event.required_facilities.map((item) => (
              <Chip
                key={item.code}
                tone="info"
                label={`${item.name}${item.quantity ? ` × ${item.quantity}` : ''}`}
              />
            ))}
          </div>
          <p className="eyebrow">Accessibility requirements</p>
          <div className="cluster">
            {event.accessibility_needs.length === 0 && (
              <p className="muted">
                {event.accessibility_none_required ? 'None required.' : NOT_RECORDED}
              </p>
            )}
            {event.accessibility_needs.map((item) => (
              <Chip key={item.code} tone="success" label={item.name} />
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
