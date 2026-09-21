import { useEffect, useState, type FormEvent } from 'react'
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
  const [sent, setSent] = useState<Booking | null>(null)
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
        if (!cancelled) setChosenEvent(detail)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setChosenEvent(null)
          setLoadError(formatApiError(error))
        }
      })
    return () => {
      cancelled = true
    }
  }, [eventId])

  function chooseEvent(nextEventId: string) {
    setEventId(nextEventId)
    setChosenEvent(null)
  }

  async function handleSubmit(submitEvent: FormEvent<HTMLFormElement>) {
    submitEvent.preventDefault()
    const venue = venues.find((candidate) => candidate.id === venueId)
    if (!venue) return
    setSendError(null)
    setIsSending(true)
    try {
      setSent(await createBookingRequest({ event_id: eventId, venue_id: venueId }, venue.name))
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

  const sentVenue = venues.find((candidate) => candidate.id === sent?.venue_id)

  return (
    <div className="stack">
      <PageHeader
        title="Request a venue"
        subtitle="Ask Venue Staff to hold a venue for one of your approved events."
      />

      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}

      {events.length === 0 ? (
        <EmptyState>
          {NO_BOOKABLE_EVENTS} A venue can only be requested once an event request has been approved
          and assigned to you.
        </EmptyState>
      ) : sent && sentVenue ? (
        <section className="card stack" aria-labelledby="booking-sent-heading">
          <h2 id="booking-sent-heading">Request sent</h2>
          <p>
            {sentVenue.name} was requested for {chosenEvent?.name ?? 'your event'}. Venue Staff will
            assess it and you will see their decision here.
          </p>
          <ul className="check-list">
            <li>
              <span className="grow-text">Status</span>
              <StatusBadge status={sent.status} />
            </li>
            <li>
              <span className="grow-text">Period held</span>
              <span>{formatSchedule(sent.held_from, sent.held_until)}</span>
            </li>
            <li>
              <span className="grow-text">Expected attendance</span>
              <span className="mono">{sent.expected_attendance}</span>
            </li>
          </ul>
          <div className="form-actions">
            <button type="button" className="secondary" onClick={requestAnother}>
              Request another venue
            </button>
          </div>
        </section>
      ) : (
        <form className="card stack" onSubmit={handleSubmit}>
          <label>
            Event
            <select value={eventId} onChange={(e) => chooseEvent(e.target.value)} required>
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
            <select value={venueId} onChange={(e) => setVenueId(e.target.value)} required>
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
