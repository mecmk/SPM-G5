import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import {
  createBookingRequest,
  fetchBookingReferenceData,
  type BookableEvent,
  type Booking,
} from '../api/bookings'
import { formatApiError } from '../api/client'
import { getEvent, type EventDetail } from '../api/events'
import { listVenues, type VenueSummary } from '../api/venues'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { formatSchedule } from '../shared/format'

const NOT_RECORDED = 'Not recorded'
const NO_BOOKABLE_EVENTS = 'No approved events are assigned to you yet.'
const NO_VENUES = 'No venues are in service, so there is nothing to request yet.'

/**
 * What was sent, captured at submission rather than looked up afterwards: the confirmation has to
 * render from this alone, so a name that is no longer in the loaded lists cannot silently hide it.
 */
interface SentRequest {
  booking: Booking
  venueName: string
  eventName: string
}

/**
 * Story 12.1 - the Event Coordinator raises a venue booking request.
 *
 * AC1: the event picker offers only events a booking may be raised from, and the venue field
 * takes one choice, so one request is one venue. AC2: the period, attendance, layout and
 * required facilities are the event's - shown here, never entered, and copied by the backend.
 * AC4: the picker is the coordinator's own assigned events, and the backend refuses anyone else.
 *
 * The event pick-list is `GET /bookings/reference-data`; the chosen event's full record comes
 * from story 2.1's `GET /events/{id}`, which is what makes the "will carry" summary possible
 * without widening the pick-list.
 */
export function BookingRequestFormPage() {
  const [events, setEvents] = useState<BookableEvent[] | null>(null)
  const [venues, setVenues] = useState<VenueSummary[]>([])
  const [eventId, setEventId] = useState('')
  const [venueId, setVenueId] = useState('')
  const [chosenEvent, setChosenEvent] = useState<EventDetail | null>(null)
  const [sent, setSent] = useState<SentRequest | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const [isSending, setIsSending] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchBookingReferenceData(), listVenues(false)])
      .then(([reference, venueList]) => {
        if (cancelled) return
        setEvents(reference.events)
        setVenues(venueList)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setEvents([])
          setLoadError(formatApiError(error))
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (eventId === '') return
    let cancelled = false
    getEvent(eventId)
      .then((detail) => {
        if (cancelled) return
        setChosenEvent(detail)
        // Clear a previous failure, or a transient one would sit on the page for good.
        setLoadError(null)
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(formatApiError(error))
      })
    return () => {
      cancelled = true
    }
  }, [eventId])

  function chooseEvent(change: ChangeEvent<HTMLSelectElement>) {
    setEventId(change.target.value)
    setChosenEvent(null)
  }

  function chooseVenue(change: ChangeEvent<HTMLSelectElement>) {
    setVenueId(change.target.value)
  }

  async function handleSubmit(submitEvent: FormEvent<HTMLFormElement>) {
    submitEvent.preventDefault()
    const venue = venues.find((candidate) => candidate.id === venueId)
    if (!venue || !chosenEvent) return
    setSendError(null)
    setIsSending(true)
    try {
      const booking = await createBookingRequest(
        { event_id: eventId, venue_id: venueId },
        venue.name,
      )
      setSent({ booking, venueName: venue.name, eventName: chosenEvent.name })
    } catch (error: unknown) {
      setSendError(formatApiError(error))
    } finally {
      setIsSending(false)
    }
  }

  function requestAnother() {
    setSent(null)
    setVenueId('')
  }

  if (events === null) return <LoadingState label="Loading your approved events…" />

  const hasNothingToRequest = events.length === 0 || venues.length === 0

  return (
    <div className="stack">
      <PageHeader
        title="Request a venue"
        subtitle="One approved event, one venue. Venue Staff decide whether to hold it."
      />

      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}

      {hasNothingToRequest && (
        <EmptyState>
          {events.length === 0
            ? `${NO_BOOKABLE_EVENTS} A venue can only be requested once an event request has been approved and assigned to you.`
            : NO_VENUES}
        </EmptyState>
      )}

      {!hasNothingToRequest && sent && (
        <section className="card stack" aria-labelledby="booking-sent-heading">
          <h2 id="booking-sent-heading">Request sent</h2>
          <p>
            {sent.venueName} was requested for {sent.eventName}. Venue Staff will assess it and you
            will see their decision here.
          </p>
          <ul className="check-list">
            <li>
              <span className="grow-text">Status</span>
              <StatusBadge status={sent.booking.status} />
            </li>
            <li>
              <span className="grow-text">Period held</span>
              <span>{formatSchedule(sent.booking.held_from, sent.booking.held_until)}</span>
            </li>
            <li>
              <span className="grow-text">Expected attendance</span>
              <span className="mono">{sent.booking.expected_attendance}</span>
            </li>
          </ul>
          <div className="form-actions">
            <button type="button" className="secondary" onClick={requestAnother}>
              Request another venue
            </button>
          </div>
        </section>
      )}

      {!hasNothingToRequest && !sent && (
        <form className="card stack" onSubmit={handleSubmit}>
          <label>
            Event
            <select value={eventId} onChange={chooseEvent} required>
              <option value="">Choose an approved event</option>
              {events.map((event) => (
                <option key={event.id} value={event.id}>
                  {event.name}
                </option>
              ))}
            </select>
          </label>

          <label>
            Venue
            <select value={venueId} onChange={chooseVenue} required>
              <option value="">Choose one venue</option>
              {venues.map((venue) => (
                <option key={venue.id} value={venue.id}>
                  {venue.name}
                </option>
              ))}
            </select>
          </label>

          {chosenEvent && (
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
                    {chosenEvent.starts_at && chosenEvent.ends_at
                      ? formatSchedule(chosenEvent.starts_at, chosenEvent.ends_at)
                      : NOT_RECORDED}
                  </span>
                </li>
                <li>
                  <span className="grow-text">Expected attendance</span>
                  <span className="mono">{chosenEvent.expected_attendance ?? NOT_RECORDED}</span>
                </li>
                <li>
                  <span className="grow-text">Room layout</span>
                  <span>{chosenEvent.required_layout_name ?? NOT_RECORDED}</span>
                </li>
                <li>
                  <span className="grow-text">Required facilities</span>
                  <span>
                    {chosenEvent.required_facilities.length === 0
                      ? NOT_RECORDED
                      : chosenEvent.required_facilities.map((facility) => facility.name).join(', ')}
                  </span>
                </li>
              </ul>
            </section>
          )}

          <div className="form-actions">
            {sendError && (
              <p role="alert" className="error">
                {sendError}
              </p>
            )}
            <button type="submit" disabled={isSending || eventId === '' || venueId === ''}>
              {isSending ? 'Sending…' : 'Send request'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
