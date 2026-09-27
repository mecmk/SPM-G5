import { useCallback, useState, type FormEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { createBookingRequest, type Booking } from '../api/bookings'
import { formatApiError } from '../api/client'
import { getEvent, type EventDetail, type RequiredFacility } from '../api/events'
import { getVenue, type Venue } from '../api/venues'
import { useAuth } from '../auth/authContext'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import { eventPath, VENUE_CATALOGUE_PATH, venueSearchPath } from '../routes'
import { formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { canRequestVenueFor } from '../shared/venueRequest'

const NOT_RECORDED = 'Not recorded'

/**
 * One required facility as the request will state it - the same shape
 * `_describe_facility` writes into `requirement_notes` backend-side, so the preview and what
 * Venue Staff end up reading do not drift.
 */
function describeFacility(facility: RequiredFacility): string {
  const quantity = facility.quantity === null ? '' : ` ×${facility.quantity}`
  const notes = facility.notes === null ? '' : ` (${facility.notes})`
  return `${facility.name}${quantity}${notes}`
}

/** The event and the venue a request is for. The step can say nothing until it has both. */
interface RequestSubject {
  event: EventDetail
  venue: Venue
}

/**
 * Story 12.1 - the Event Coordinator raises a venue booking request, and f12.1.1 (AC15) - for the
 * event and venue in the address, reached with Request this venue from the catalogue in that
 * event's context.
 *
 * AC1: the address fixes one event and one venue, so one request is one venue; the backend refuses
 * an event that cannot take a booking. AC2: the period, attendance, layout and required facilities
 * are the event's - shown here, never entered, and copied by the backend. AC3: the outcome shows
 * the request pending. AC4: the backend refuses anyone but the event's assigned coordinator.
 * Nothing can be sent before both records have arrived (review of PR #42).
 *
 * The address can be reached without Request this venue (an old link, an edited one), so the
 * page checks it with the same rule as Find a venue and, for anyone that rule turns away, says why
 * instead of offering a request the backend would refuse (review of PR #67).
 *
 * The address also carries the catalogue's own query, so the back link returns to the same search.
 */
export function BookingRequestFormPage() {
  const { eventId = '', venueId = '' } = useParams()
  const location = useLocation()
  const { user, can } = useAuth()
  const loadSubject = useCallback(
    () =>
      Promise.all([getEvent(eventId), getVenue(venueId)]).then(
        ([event, venue]): RequestSubject => ({ event, venue }),
      ),
    [eventId, venueId],
  )
  const { data: subject, error } = useLoaded(loadSubject)
  const [sent, setSent] = useState<Booking | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const [isSending, setIsSending] = useState(false)

  if (error) {
    return (
      <div className="page">
        <p role="alert" className="error">
          {error}
        </p>
      </div>
    )
  }
  if (!subject) return <LoadingState label="Loading the request…" />

  const { event, venue } = subject
  if (!canRequestVenueFor(event, user, can)) {
    return (
      <div className="page stack">
        <Link to={eventPath(event.id)} className="back-link">
          ← {event.name}
        </Link>
        <PageHeader title={`Request ${venue.name}`} subtitle={`For ${event.name}.`} />
        <p role="alert" className="error">
          {ERROR_REGISTRY.BOOKING_NOT_REQUESTABLE.message}
        </p>
      </div>
    )
  }

  const backTo = location.search
    ? `${VENUE_CATALOGUE_PATH}${location.search}`
    : venueSearchPath({ eventId: event.id })

  async function handleSubmit(submitEvent: FormEvent<HTMLFormElement>) {
    submitEvent.preventDefault()
    setSendError(null)
    setIsSending(true)
    try {
      setSent(await createBookingRequest({ event_id: event.id, venue_id: venue.id }, venue.name))
    } catch (err: unknown) {
      setSendError(formatApiError(err))
    } finally {
      setIsSending(false)
    }
  }

  return (
    <div className="page stack">
      <Link to={backTo} className="back-link">
        ← Venue catalogue
      </Link>
      <PageHeader
        title={`Request ${venue.name}`}
        subtitle={`For ${event.name}. Venue Staff decide whether to hold it.`}
      />

      {sent ? (
        <section className="card stack" aria-labelledby="booking-sent-heading">
          <h2 id="booking-sent-heading">Request sent</h2>
          <p>
            {venue.name} was requested for {event.name}. The request is with Venue Staff for review.
          </p>
          <ul className="check-list">
            <li>
              <span className="grow-text">Status</span>
              <StatusBadge status={sent.status} />
            </li>
            <li>
              <span className="grow-text">Requested period</span>
              <span>{formatSchedule(sent.held_from, sent.held_until)}</span>
            </li>
            <li>
              <span className="grow-text">Expected attendance</span>
              <span className="mono">{sent.expected_attendance}</span>
            </li>
          </ul>
          <div className="form-actions">
            <Link to={eventPath(event.id)} className="button secondary">
              Back to the event
            </Link>
          </div>
        </section>
      ) : (
        <form className="card stack" onSubmit={handleSubmit}>
          <section aria-labelledby="booking-venue-heading" className="stack">
            <h2 id="booking-venue-heading">Venue</h2>
            <ul className="check-list">
              <li>
                <span className="grow-text">Location</span>
                <span>{venue.location}</span>
              </li>
              <li>
                <span className="grow-text">Capacity</span>
                <span className="mono">{venue.capacity}</span>
              </li>
            </ul>
          </section>

          <section aria-labelledby="booking-carries-heading" className="stack">
            <h2 id="booking-carries-heading">What this request will carry</h2>
            <p className="muted">
              Taken from the event, so Venue Staff assess the same requirements it was approved
              with.
            </p>
            <ul className="check-list">
              <li>
                <span className="grow-text">Date and time</span>
                <span>
                  {event.starts_at && event.ends_at
                    ? formatSchedule(event.starts_at, event.ends_at)
                    : NOT_RECORDED}
                </span>
              </li>
              <li>
                <span className="grow-text">Expected attendance</span>
                <span className="mono">{event.expected_attendance ?? NOT_RECORDED}</span>
              </li>
              <li>
                <span className="grow-text">Room layout</span>
                <span>{event.required_layout_name ?? NOT_RECORDED}</span>
              </li>
              <li>
                <span className="grow-text">Required facilities</span>
                <span>
                  {event.required_facilities.length === 0
                    ? NOT_RECORDED
                    : event.required_facilities.map(describeFacility).join(', ')}
                </span>
              </li>
            </ul>
          </section>

          <div className="form-actions">
            {sendError && (
              <p role="alert" className="error">
                {sendError}
              </p>
            )}
            <button type="submit" disabled={isSending}>
              {isSending ? 'Sending…' : 'Send request'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
