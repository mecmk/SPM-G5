import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { getBooking, type Booking } from '../api/bookings'
import { formatApiError } from '../api/client'
import { getEvent, type EventDetail } from '../api/events'
import { getVenue, type Venue } from '../api/venues'
import { Chip } from '../components/Chip'
import { Icon } from '../components/Icon'
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
 * out as scannable summary and requirement cards rather than the queue card's summary.
 *
 * Composes three already-existing reads (the booking itself, its venue, its event) rather than
 * a dedicated endpoint: Venue Staff already holds BOOKINGS_READ, VENUES_READ and
 * EVENTS_READ_ALL, so nothing new is needed on the backend for this view.
 *
 * Approve/reject (stories 13.2/13.3) are this page's next addition - this page deliberately
 * renders no action for them yet.
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
        ← Back to Booking Requests
      </Link>

      <div className="item-card-header booking-detail-header">
        <h1>{event.name}</h1>
        <StatusBadge status={booking.status} />
      </div>

      <div className="stack">
        <div className="stat-card-grid">
          <div className="stat-card">
            <Icon name="building" size={20} />
            <p className="stat-card-value">{venue.name}</p>
            <p className="fact-label">Requested venue</p>
          </div>
          <div className="stat-card">
            <Icon name="calendar" size={20} />
            <p className="stat-card-value">{formatDate(booking.starts_at)}</p>
            <p className="fact-label">Date</p>
          </div>
          <div className="stat-card">
            <Icon name="calendar-check" size={20} />
            <p className="stat-card-value">
              {formatTime(booking.starts_at)} – {formatTime(booking.ends_at)}
            </p>
            <p className="fact-label">Time</p>
          </div>
          <div className="stat-card">
            <Icon name="people" size={20} />
            <p className="stat-card-value">{booking.expected_attendance}</p>
            <p className="fact-label">Expected attendance</p>
          </div>
        </div>

        <section className="card stack" aria-labelledby="booking-requirements-heading">
          <h2 id="booking-requirements-heading">Venue requirements</h2>
          <div>
            <p className="fact-label">Room layout</p>
            <p className="fact-value">{layoutName(venue, booking.required_layout_code)}</p>
          </div>
          <div>
            <p className="fact-label">Required facilities</p>
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
          </div>
          <div>
            <p className="fact-label">Accessibility requirements</p>
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
          </div>
          <div>
            <p className="fact-label">Other requirements</p>
            <p>{booking.requirement_notes ?? NOT_RECORDED}</p>
          </div>
        </section>

        <section className="card stack" aria-labelledby="booking-event-heading">
          <h2 id="booking-event-heading">Event details</h2>
          <div>
            <p className="fact-label">Event name</p>
            <p>{event.name}</p>
          </div>
          <div>
            <p className="fact-label">Organiser</p>
            <p>{event.organiser_name}</p>
          </div>
          <div>
            <p className="fact-label">Purpose</p>
            <p>{event.purpose ?? NOT_RECORDED}</p>
          </div>
          <div>
            <p className="fact-label">Description</p>
            <p>{event.description ?? NOT_RECORDED}</p>
          </div>
        </section>
      </div>
    </div>
  )
}
