import { useCallback, useState, type FormEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import {
  createBookingRequest,
  SUITABILITY_OVERRIDE_REASON_MAX_LENGTH,
  type Booking,
} from '../api/bookings'
import { ApiError, formatApiError } from '../api/client'
import { getEvent, type EventDetail, type RequiredFacility } from '../api/events'
import { getVenue, getVenueSuitability, type Venue, type VenueSuitability } from '../api/venues'
import { useAuth } from '../auth/authContext'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { SuitabilityNote } from '../components/SuitabilityNote'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import { eventPath, VENUE_CATALOGUE_PATH, venueSearchPath } from '../routes'
import { formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { canRequestVenueFor, venueRequestTermsFor } from '../shared/venueRequest'

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
 * Nothing can be sent before both records have arrived.
 *
 * The address can be reached without Request this venue (an old link, an edited one), so the
 * page checks it with the same rule as Find a venue and, for anyone that rule turns away, says why
 * instead of offering a request the backend would refuse.
 *
 * The address also carries the catalogue's own query, so the back link returns to the same search.
 *
 * Story 12.1 AC14: the venue may have stopped being available since the search. The backend
 * re-checks and refuses with its reason, and the step then offers Back to the results: the same
 * search, which runs again, so the venue has gone from it.
 *
 * Story 11.1 AC2: once the step knows the coordinator may request the venue, it reads whether the
 * venue suits the event - "Checking…" meanwhile, with Send held back. A venue that suits shows
 * "Suitable". One that does not shows a warning listing every failure and a required
 * justification (AC7: never sent blank), and Send asks for confirmation before sending it. If the
 * read fails the step says so and Send stays open, since the backend judges again on send. AC7:
 * when the backend refuses the send for want of a justification - the venue stopped suiting after
 * the step loaded - the step reads again and shows the warning. That refusal is itself enough to
 * ask for the justification, so a read that fails again still leaves the coordinator able to give
 * one; and only the latest read's failure is shown, never an earlier one beside a read that worked.
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
  const isRequestable = subject !== null && canRequestVenueFor(subject.event, user, can)
  const loadSuitability = useCallback(
    () =>
      isRequestable
        ? getVenueSuitability(venueId, eventId)
        : Promise.resolve<VenueSuitability | null>(null),
    [isRequestable, venueId, eventId],
  )
  const {
    data: suitability,
    error: suitabilityError,
    setData: setSuitability,
  } = useLoaded(loadSuitability)
  const [sent, setSent] = useState<Booking | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const [canReturnToResults, setCanReturnToResults] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [justification, setJustification] = useState('')
  const [isConfirming, setIsConfirming] = useState(false)
  // The latest read after a refused send: null until there is one, then how it ended. It takes
  // over from the first read's failure (suitabilityError), which useLoaded never clears itself.
  const [reread, setReread] = useState<{ error: string | null } | null>(null)
  // The backend refused a send for want of a justification, and no later read has said otherwise.
  const [serverAskedForJustification, setServerAskedForJustification] = useState(false)

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
  // Story 2.7: what the request carries - the event's first venue requirement, or the event's own.
  const { requirement, startsAt, endsAt, capacity, layoutName, facilities } =
    venueRequestTermsFor(event)
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
  const isChecking = suitability === null && suitabilityError === null
  const isUnsuitable = suitability !== null && !suitability.is_suitable
  const requiresJustification = isUnsuitable || serverAskedForJustification
  const checkError = reread === null ? suitabilityError : reread.error

  /** AC7: the backend judged the venue unsuitable on send, so read it again for the warning. */
  async function rereadSuitability() {
    try {
      setSuitability(await getVenueSuitability(venue.id, event.id))
      setReread({ error: null })
      // The read is now the latest word on whether the venue suits, so it decides.
      setServerAskedForJustification(false)
    } catch (err: unknown) {
      setReread({ error: formatApiError(err) })
    }
  }

  async function send(reason: string | null) {
    setIsSending(true)
    try {
      const input = { event_id: event.id, venue_id: venue.id }
      setSent(
        await createBookingRequest(
          reason === null ? input : { ...input, suitability_override_reason: reason },
          venue.name,
        ),
      )
    } catch (err: unknown) {
      setSendError(formatApiError(err))
      setCanReturnToResults(err instanceof ApiError && err.code === 'BOOKING_NOT_ALLOWED')
      if (err instanceof ApiError && err.code === 'BOOKING_JUSTIFICATION_REQUIRED') {
        setServerAskedForJustification(true)
        await rereadSuitability()
      }
    } finally {
      setIsSending(false)
      setIsConfirming(false)
    }
  }

  async function handleSubmit(submitEvent: FormEvent<HTMLFormElement>) {
    submitEvent.preventDefault()
    setSendError(null)
    setCanReturnToResults(false)
    if (!requiresJustification) {
      await send(null)
      return
    }
    if (justification.trim() === '') {
      setSendError(ERROR_REGISTRY.BOOKING_JUSTIFICATION_REQUIRED.message)
      return
    }
    setIsConfirming(true)
  }

  function confirmSend() {
    void send(justification.trim())
  }

  function cancelSend() {
    setIsConfirming(false)
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
            {sent.suitability_override_reason !== null && (
              <li>
                <span className="grow-text">Justification</span>
                <span>{sent.suitability_override_reason}</span>
              </li>
            )}
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
              Taken from the event
              {requirement?.name ? `’s first venue requirement, ${requirement.name},` : ','} so
              Venue Staff assess the same requirements it was approved with.
            </p>
            <ul className="check-list">
              <li>
                <span className="grow-text">Date and time</span>
                <span>{startsAt && endsAt ? formatSchedule(startsAt, endsAt) : NOT_RECORDED}</span>
              </li>
              <li>
                <span className="grow-text">Expected attendance</span>
                <span className="mono">{capacity ?? NOT_RECORDED}</span>
              </li>
              <li>
                <span className="grow-text">Room layout</span>
                <span>{layoutName ?? NOT_RECORDED}</span>
              </li>
              <li>
                <span className="grow-text">Required facilities</span>
                <span>
                  {facilities.length === 0
                    ? NOT_RECORDED
                    : facilities.map(describeFacility).join(', ')}
                </span>
              </li>
            </ul>
          </section>

          <section aria-labelledby="booking-suitability-heading" className="stack">
            <h2 id="booking-suitability-heading">Suitability</h2>
            {isChecking && <p className="muted">Checking whether this venue suits the event…</p>}
            {checkError !== null && (
              <p role="alert" className="error">
                {checkError}
              </p>
            )}
            {suitability !== null && (
              <SuitabilityNote
                suitability={suitability}
                requirementCount={event.venue_requirements.length}
              />
            )}
            {requiresJustification && (
              <label>
                Justification
                <textarea
                  value={justification}
                  onChange={(changeEvent) => setJustification(changeEvent.target.value)}
                  maxLength={SUITABILITY_OVERRIDE_REASON_MAX_LENGTH}
                  rows={4}
                />
                <span className="small muted">
                  Why request it anyway? Venue Staff read this with the request.
                </span>
              </label>
            )}
          </section>

          <div className="form-actions">
            {sendError && (
              <p role="alert" className="error">
                {sendError}
              </p>
            )}
            {canReturnToResults && (
              <Link to={backTo} className="button secondary">
                Back to the results
              </Link>
            )}
            <button type="submit" disabled={isSending || isChecking}>
              {isSending ? 'Sending…' : 'Send request'}
            </button>
          </div>
        </form>
      )}

      {isConfirming && (
        <ConfirmDialog
          title={`Request ${venue.name} anyway?`}
          confirmLabel="Send request"
          tone="primary"
          isBusy={isSending}
          error={null}
          onConfirm={confirmSend}
          onCancel={cancelSend}
        >
          <p>
            {venue.name} does not suit the event&apos;s venue requirement. Your justification goes
            to Venue Staff with the request.
          </p>
        </ConfirmDialog>
      )}
    </div>
  )
}
