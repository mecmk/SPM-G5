import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { approveBooking, getBooking, rejectBooking, type Booking } from '../api/bookings'
import { formatApiError } from '../api/client'
import { getEvent, type EventDetail } from '../api/events'
import { getVenue, type Venue } from '../api/venues'
import { useAuth } from '../auth/authContext'
import { PERMISSIONS } from '../auth/permissions'
import { Chip } from '../components/Chip'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { BOOKING_REQUESTS_PATH, eventPath } from '../routes'
import { formatDate, formatTime } from '../shared/format'

const NOT_RECORDED = 'Not recorded'
const PENDING_STATUS = 'PENDING'
const EMPTY_REASON_MESSAGE = 'Enter a reason for rejecting this request.'

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
 * Story 13.2 AC1: an Approve action next to the status badge, shown only while the request is
 * still PENDING.
 *
 * Story 13.2.1: a Reject action alongside it, requiring a reason. AC4: this page is also
 * reachable by anyone who can read the booking (not only Venue Staff, who can decide it) - see
 * BOOKING_DETAIL_PATH in App.tsx - so the decide actions are hidden here, inline, for a viewer
 * without BOOKINGS_DECIDE.
 */
export function BookingRequestDetailPage() {
  const { bookingId = '' } = useParams()
  const { can } = useAuth()
  const canDecide = can(PERMISSIONS.BOOKINGS_DECIDE)
  const [booking, setBooking] = useState<Booking | null>(null)
  const [venue, setVenue] = useState<Venue | null>(null)
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isConfirmingApprove, setIsConfirmingApprove] = useState(false)
  const [isApproving, setIsApproving] = useState(false)
  const [approveError, setApproveError] = useState<string | null>(null)
  const [isConfirmingReject, setIsConfirmingReject] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [isRejecting, setIsRejecting] = useState(false)
  const [rejectError, setRejectError] = useState<string | null>(null)

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

  function askToApprove() {
    setApproveError(null)
    setIsConfirmingApprove(true)
  }

  function cancelApprove() {
    setIsConfirmingApprove(false)
  }

  async function confirmApprove() {
    if (!booking || !event) return
    setIsApproving(true)
    setApproveError(null)
    try {
      const updated = await approveBooking(booking.id, event.name)
      setBooking(updated)
      setIsConfirmingApprove(false)
    } catch (err) {
      setApproveError(formatApiError(err))
    } finally {
      setIsApproving(false)
    }
  }

  function askToReject() {
    setRejectError(null)
    setRejectReason('')
    setIsConfirmingReject(true)
  }

  function cancelReject() {
    setIsConfirmingReject(false)
  }

  async function confirmReject() {
    if (!booking || !event) return
    const reason = rejectReason.trim()
    if (reason === '') {
      setRejectError(EMPTY_REASON_MESSAGE)
      return
    }
    setIsRejecting(true)
    setRejectError(null)
    try {
      const updated = await rejectBooking(booking.id, event.name, reason)
      setBooking(updated)
      setIsConfirmingReject(false)
    } catch (err) {
      setRejectError(formatApiError(err))
    } finally {
      setIsRejecting(false)
    }
  }

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
      {canDecide ? (
        <Link to={BOOKING_REQUESTS_PATH} className="back-link">
          ← Back to Booking Requests
        </Link>
      ) : (
        <Link to={eventPath(event.id)} className="back-link">
          ← Back to {event.name}
        </Link>
      )}

      <div className="item-card-header booking-detail-header">
        <div className="cluster">
          <h1>{event.name}</h1>
          <StatusBadge status={booking.status} />
        </div>
        {canDecide && booking.status === PENDING_STATUS && (
          <div className="cluster">
            <button type="button" className="brand button-sm" onClick={askToApprove}>
              Approve
            </button>
            <button type="button" className="danger-solid button-sm" onClick={askToReject}>
              Reject
            </button>
          </div>
        )}
      </div>

      {booking.decision_reason !== null && (
        <p className="subtle-block">
          <span className="fact-label">Reason</span>
          <br />
          {booking.decision_reason}
        </p>
      )}

      <div className="stack">
        <section className="stat-card-grid" aria-labelledby="booking-summary-heading">
          <h2 id="booking-summary-heading" className="visually-hidden">
            Booking summary
          </h2>
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
        </section>

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

      {isConfirmingApprove && (
        <ConfirmDialog
          title="Approve this booking?"
          confirmLabel="Approve"
          tone="primary"
          isBusy={isApproving}
          error={approveError}
          onConfirm={confirmApprove}
          onCancel={cancelApprove}
        >
          <p>
            {venue.name} will be booked for {event.name} from {formatDate(booking.starts_at)},{' '}
            {formatTime(booking.starts_at)}–{formatTime(booking.ends_at)}.
          </p>
        </ConfirmDialog>
      )}

      {isConfirmingReject && (
        <ConfirmDialog
          title="Reject this booking?"
          confirmLabel="Reject"
          isBusy={isRejecting}
          error={rejectError}
          onConfirm={confirmReject}
          onCancel={cancelReject}
        >
          <p>
            {event.name}'s request for {venue.name} will be rejected.
          </p>
          <label>
            Reason for rejecting
            <textarea
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              rows={3}
              disabled={isRejecting}
            />
          </label>
        </ConfirmDialog>
      )}
    </div>
  )
}
