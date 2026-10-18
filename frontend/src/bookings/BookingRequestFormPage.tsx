import { useCallback, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import {
  createBookingRequest,
  listBookingsForEvent,
  requestReplacementBooking,
  SUITABILITY_OVERRIDE_REASON_MAX_LENGTH,
  switchBookingRequest,
  type BookingOutcome,
} from '../api/bookings'
import { ApiError, formatApiError } from '../api/client'
import { getEvent, type EventDetail, type RequiredFacility } from '../api/events'
import { getVenue, getVenueSuitability, type Venue, type VenueSuitability } from '../api/venues'
import { useAuth } from '../auth/authContext'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { PageHeader } from '../components/PageHeader'
import { SuitabilityNote } from '../components/SuitabilityNote'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import {
  eventPath,
  VENUE_CATALOGUE_PATH,
  VENUE_REQUEST_REPLACES_PARAM,
  VENUE_SEARCH_PARAMS,
  venueSearchPath,
} from '../routes'
import { replacesLine } from '../shared/bookingStatus'
import { formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import {
  canRequestVenueFor,
  coveringBooking,
  firstRequirementNeedingVenue,
  isBooked,
  isReplaceable,
  requirementName,
  venueRequirementTerms,
  venueSearchFor,
} from '../shared/venueRequest'
import {
  BOOKED_PERIOD_LABEL,
  bookedPeriod,
  durationMinutes,
  isWithinOpeningHours,
  minutesToDuration,
  outsideHoursFact,
  REPLACEMENT_TURNAROUND_HINT,
  TURNAROUND_HINT,
  turnaroundProblem,
  VENUE_STAFF_DECIDE,
  ZERO_DURATION,
  type DurationDraft,
} from './turnaround'

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

/**
 * Story 12.5 AC3/AC4/AC6: where a sent request leads - the catalogue for the event's first venue
 * requirement that still needs a venue, with its filters, or the event's page once every
 * requirement has a request. The request is already sent, so if the bookings cannot be read this
 * goes to the event's page, which lists them, rather than holding the coordinator on the step.
 */
async function destinationAfterSend(event: EventDetail): Promise<string> {
  try {
    const next = firstRequirementNeedingVenue(event, await listBookingsForEvent(event.id))
    return next === null ? eventPath(event.id) : venueSearchPath(venueSearchFor(event, next))
  } catch {
    return eventPath(event.id)
  }
}

/** The event and the venue a request is for. The step can say nothing until it has both. */
interface RequestSubject {
  event: EventDetail
  venue: Venue
}

/** f12.1.2 (story 12.1 AC1): one of the units a setup or a teardown is entered in. */
interface DurationUnit {
  part: keyof DurationDraft
  label: string
}

const DURATION_UNITS: readonly DurationUnit[] = [
  { part: 'days', label: 'Days' },
  { part: 'hours', label: 'Hours' },
  { part: 'minutes', label: 'Minutes' },
]

interface DurationFieldsProps {
  /** "Setup" or "Teardown", which names the group. */
  legend: string
  draft: DurationDraft
  onChange: (draft: DurationDraft) => void
}

/** f12.1.2 (story 12.1 AC1): a setup's or a teardown's days, hours and minutes, as typed. */
function DurationFields({ legend, draft, onChange }: DurationFieldsProps) {
  function handlePartChange(part: keyof DurationDraft, value: string) {
    onChange({ ...draft, [part]: value })
  }

  return (
    <fieldset>
      <legend>{legend}</legend>
      <div className="duration-fields">
        {DURATION_UNITS.map(({ part, label }) => (
          <label key={part}>
            {label}
            <input
              type="text"
              inputMode="numeric"
              autoComplete="off"
              spellCheck={false}
              value={draft[part]}
              onChange={(changeEvent) => handlePartChange(part, changeEvent.target.value)}
            />
          </label>
        ))}
      </div>
    </fieldset>
  )
}

/**
 * Story 12.1 - the Event Coordinator raises a venue booking request, and f12.1.1 (AC15) - for the
 * event and venue in the address, reached with Request this venue from the catalogue in that
 * event's context.
 *
 * AC1: the address fixes one event and one venue, so one request is one venue; the backend refuses
 * an event that cannot take a booking. AC2: the period, attendance, layout and required facilities
 * are the event's - shown here, never entered, and copied by the backend. AC3: once sent, the
 * request reads as pending on the event's page and in the catalogue's banner (story 12.5 AC2, AC4).
 * AC4: the backend refuses anyone but the event's assigned coordinator. Nothing can be sent before
 * both records have arrived.
 *
 * The address can be reached without Request this venue (an old link, an edited one), so the
 * page checks it with the same rule as Find a venue and, for anyone that rule turns away, says why
 * instead of offering a request the backend would refuse.
 *
 * The address also carries the catalogue's own query, so the back link returns to the same search.
 *
 * Story 12.1 AC14: the venue may have stopped being available since the search. The backend
 * re-checks and refuses with its reason, and the step then offers Back to the results: the same
 * search, which runs again, so the venue has gone from it. f12.1.2: that search covers the
 * request's own times only, so after a refusal that only the setup or teardown caused - another
 * hold or a closure in it (AC3, AC14), or a setup starting in the past (AC9) - the venue is still
 * listed, and the setup or teardown is what to change here.
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
 *
 * Story 12.5: the request is for the venue requirement the catalogue's query selects. The step
 * names it and carries its own times, people, layout and facilities (AC1), or, with none selected,
 * says it is an additional venue with the event's own period and attendance (AC5, AC7); the
 * suitability read and the send name it too (AC14). A requirement that is not the event's is
 * refused before anything is sent (AC11). Once sent, a notice names the venue and the requirement,
 * and the step gives way to the next requirement still needing a venue, or to the event's page
 * (AC3, AC4, AC6).
 *
 * Decided 11 Oct 2026: opened with Switch to this venue, the address also names the
 * requirement's pending request, and the step switches it - it says which request it replaces,
 * and the server withdraws that one and requests this venue together. Opened any other way, the
 * step sends a plain request, which the server refuses with its reason while the requirement
 * has one (AC11).
 *
 * f12.1.2, under 12.1's ACs as the backlog numbers them now (the AC1-AC4 above are Sprint 1's):
 * the coordinator enters a setup and a teardown, each in days, hours and minutes and 0 until
 * changed, and sees the booked period they make around the request's own times (AC1). A negative,
 * fractional or over-14-day one is refused under the fields before anything is sent (AC5). The
 * server refuses those too, and a setup that would start in the past (AC9), with a sentence of its
 * own shown like any refusal. A setup or teardown that runs outside the venue's opening hours is
 * said under the booked period, with the hours and that Venue Staff decide whether to allow it,
 * before anything is sent (AC17). Such a request can still be sent, the hours being checked on its
 * own times (AC16).
 */
export function BookingRequestFormPage() {
  const { eventId = '', venueId = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requirementId = searchParams.get(VENUE_SEARCH_PARAMS.requirement)
  const replacesId = searchParams.get(VENUE_REQUEST_REPLACES_PARAM)
  // Story 12.6 AC1/AC2: opened from the catalogue in replacement mode, the address also names the
  // approved booking this request replaces.
  const replacingId = searchParams.get(VENUE_SEARCH_PARAMS.replacing)
  const { user, can } = useAuth()
  const loadSubject = useCallback(
    () =>
      Promise.all([getEvent(eventId), getVenue(venueId)]).then(
        ([event, venue]): RequestSubject => ({ event, venue }),
      ),
    [eventId, venueId],
  )
  const { data: subject, error } = useLoaded(loadSubject)
  const requirement =
    subject === null || requirementId === null
      ? null
      : (subject.event.venue_requirements.find((each) => each.id === requirementId) ?? null)
  /** Story 12.5 AC11: the address names a venue requirement that is not the event's. */
  const isStrayRequirement = subject !== null && requirementId !== null && requirement === null
  const isRequestable =
    subject !== null && canRequestVenueFor(subject.event, user, can) && !isStrayRequirement
  const loadSuitability = useCallback(
    () =>
      isRequestable
        ? getVenueSuitability(venueId, eventId, requirementId)
        : Promise.resolve<VenueSuitability | null>(null),
    [isRequestable, venueId, eventId, requirementId],
  )
  const {
    data: suitability,
    error: suitabilityError,
    setData: setSuitability,
  } = useLoaded(loadSuitability)
  // Story 12.5 (decided 11 Oct 2026): the event's bookings, read to find the request a switch
  // replaces - only when the address names one. Story 12.6: or the booking a replacement replaces.
  const namesAnotherBooking = replacesId !== null || replacingId !== null
  const loadBookings = useCallback(
    () =>
      isRequestable && namesAnotherBooking
        ? listBookingsForEvent(eventId)
        : Promise.resolve<BookingOutcome[] | null>(null),
    [isRequestable, namesAnotherBooking, eventId],
  )
  const { data: bookings, error: bookingsError } = useLoaded(loadBookings)
  const isFindingReplaced =
    isRequestable && namesAnotherBooking && bookings === null && bookingsError === null
  const covering =
    requirement === null || bookings === null ? null : coveringBooking(requirement, bookings)
  /** The request this one replaces: the requirement's own, while it is pending. Anything else
   *  the address names - or bookings that could not be read - sends a plain request. */
  const replaced =
    covering !== null && covering.id === replacesId && !isBooked(covering) ? covering : null
  /** Story 12.6 AC2: the approved booking, still marked, this request replaces. Anything else the
   *  address names sends a plain request, which the server refuses with its reason. */
  const original =
    bookings === null
      ? null
      : (bookings.find((each) => each.id === replacingId && isReplaceable(each)) ?? null)
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
  // f12.1.2 (story 12.1 AC1): the setup and teardown as typed, 0 until the coordinator changes
  // them.
  const [setupDraft, setSetupDraft] = useState(ZERO_DURATION)
  const [teardownDraft, setTeardownDraft] = useState(ZERO_DURATION)
  // Story 12.6 AC2: a replacement starts from the original's setup and teardown, once they are
  // known, and the coordinator may change them. Set once, so what they type is never overwritten.
  const [hasPrefilledTurnaround, setHasPrefilledTurnaround] = useState(false)
  if (original !== null && !hasPrefilledTurnaround) {
    setHasPrefilledTurnaround(true)
    setSetupDraft(minutesToDuration(original.setup_minutes))
    setTeardownDraft(minutesToDuration(original.teardown_minutes))
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
  // Story 12.5: a switch names the request it replaces, so that is found first.
  if (!subject || isFindingReplaced) return <LoadingState label="Loading the request…" />

  const { event, venue } = subject
  // Story 12.5 AC1: what the request carries - its venue requirement's own, or the event's own
  // for an additional venue.
  const { startsAt, endsAt, capacity, layoutName, facilities } = venueRequirementTerms(
    event,
    requirement,
  )
  const forRequirement = requirement === null ? null : requirementName(event, requirement)
  // The catalogue's own query, without the switch's.
  const catalogueQuery = new URLSearchParams(location.search)
  catalogueQuery.delete(VENUE_REQUEST_REPLACES_PARAM)
  const backTo =
    catalogueQuery.toString() === ''
      ? venueSearchPath({ eventId: event.id })
      : `${VENUE_CATALOGUE_PATH}?${catalogueQuery}`
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
  if (isStrayRequirement) {
    return (
      <div className="page stack">
        <Link to={backTo} className="back-link">
          ← Venue catalogue
        </Link>
        <PageHeader title={`Request ${venue.name}`} subtitle={`For ${event.name}.`} />
        <p role="alert" className="error">
          {ERROR_REGISTRY.BOOKING_REQUIREMENT_NOT_FOUND.message}
        </p>
      </div>
    )
  }

  const isChecking = suitability === null && suitabilityError === null
  const isUnsuitable = suitability !== null && !suitability.is_suitable
  const requiresJustification = isUnsuitable || serverAskedForJustification
  const checkError = reread === null ? suitabilityError : reread.error
  // f12.1.2 (story 12.1 AC1/AC5): the setup and teardown in whole minutes, and the booked period
  // they make. While either has a problem, the problem shows in place of the booked period and
  // nothing is sent, so 0 stands in for one that is not a whole number.
  const turnaroundError = turnaroundProblem(setupDraft, teardownDraft)
  const setupMinutes = durationMinutes(setupDraft) ?? 0
  const teardownMinutes = durationMinutes(teardownDraft) ?? 0
  const period =
    turnaroundError === null && startsAt && endsAt
      ? bookedPeriod(startsAt, endsAt, setupMinutes, teardownMinutes)
      : null
  // f12.1.2 (story 12.1 AC17): what of the setup and teardown runs outside the venue's opening
  // hours, said under the booked period, so only while that shows.
  const outsideFact =
    period !== null &&
    startsAt &&
    endsAt &&
    isWithinOpeningHours(startsAt, endsAt, venue.operating_hours_start, venue.operating_hours_end)
      ? outsideHoursFact(
          startsAt,
          endsAt,
          setupMinutes,
          teardownMinutes,
          venue.operating_hours_start,
          venue.operating_hours_end,
        )
      : null

  /** AC7: the backend judged the venue unsuitable on send, so read it again for the warning. */
  async function rereadSuitability() {
    try {
      setSuitability(await getVenueSuitability(venue.id, event.id, requirement?.id ?? null))
      setReread({ error: null })
      // The read is now the latest word on whether the venue suits, so it decides.
      setServerAskedForJustification(false)
    } catch (err: unknown) {
      setReread({ error: formatApiError(err) })
    }
  }

  async function send(reason: string | null) {
    // f12.1.2 (story 12.1 AC5): every way of sending - Send request, or the justification
    // dialog's confirm - sends only a setup and teardown the step accepts.
    if (turnaroundError !== null) {
      setIsConfirming(false)
      return
    }
    setIsSending(true)
    try {
      if (original !== null) {
        await requestReplacementBooking(
          original.id,
          {
            venue_id: venue.id,
            suitability_override_reason: reason ?? undefined,
            setup_minutes: setupMinutes,
            teardown_minutes: teardownMinutes,
          },
          venue.name,
          original.venue_name,
        )
      } else if (replaced !== null) {
        await switchBookingRequest(
          replaced.id,
          {
            venue_id: venue.id,
            suitability_override_reason: reason ?? undefined,
            setup_minutes: setupMinutes,
            teardown_minutes: teardownMinutes,
          },
          venue.name,
          forRequirement,
          replaced.venue_name,
        )
      } else {
        await createBookingRequest(
          {
            event_id: event.id,
            venue_id: venue.id,
            venue_requirement_id: requirement?.id,
            suitability_override_reason: reason ?? undefined,
            setup_minutes: setupMinutes,
            teardown_minutes: teardownMinutes,
          },
          venue.name,
          forRequirement,
        )
      }
      // Replaced, so Back does not return to a step whose request has been sent.
      navigate(await destinationAfterSend(event), { replace: true })
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
    // f12.1.2 (story 12.1 AC5): the setup's or teardown's problem is already said under its fields.
    if (turnaroundError !== null) return
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
            {forRequirement === null
              ? 'Taken from the event’s own dates and attendance: an additional venue, which no venue requirement asks for.'
              : `Taken from the event’s venue requirement, ${forRequirement}, so Venue Staff assess the same requirements it was approved with.`}
          </p>
          {replaced !== null && (
            <p>
              This replaces the request for {replaced.venue_name}, which is withdrawn when you
              switch.
            </p>
          )}
          {original !== null && (
            <p>
              {replacesLine(original.venue_name)}, whose venue is unavailable. It stays booked until
              Venue Staff approve this request, and is released then.
            </p>
          )}
          <ul className="check-list">
            <li>
              <span className="grow-text">Venue requirement</span>
              <span>{forRequirement ?? 'Additional venue'}</span>
            </li>
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

        <section aria-labelledby="booking-turnaround-heading" className="stack">
          <h2 id="booking-turnaround-heading">Setup and teardown</h2>
          <p className="muted">
            {original === null ? TURNAROUND_HINT : REPLACEMENT_TURNAROUND_HINT}
          </p>
          <div className="turnaround-fields">
            <DurationFields legend="Setup" draft={setupDraft} onChange={setSetupDraft} />
            <DurationFields legend="Teardown" draft={teardownDraft} onChange={setTeardownDraft} />
          </div>
          {turnaroundError !== null && (
            <p role="alert" className="error">
              {ERROR_REGISTRY[turnaroundError].message}
            </p>
          )}
          {period !== null && (
            <ul className="check-list">
              <li>
                <span className="grow-text">{BOOKED_PERIOD_LABEL}</span>
                <span>{formatSchedule(period.heldFrom, period.heldUntil)}</span>
              </li>
            </ul>
          )}
          {/* f12.1.2 (story 12.1 AC17): a live region, there from the start, so a screen reader
           *  says the notice as it appears while the setup or teardown is typed. */}
          <div role="status">
            {outsideFact !== null && (
              <p className="warning">
                {outsideFact} {VENUE_STAFF_DECIDE}
              </p>
            )}
          </div>
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
            {replaced === null
              ? isSending
                ? 'Sending…'
                : 'Send request'
              : isSending
                ? 'Switching…'
                : 'Switch request'}
          </button>
        </div>
      </form>

      {isConfirming && (
        <ConfirmDialog
          title={`Request ${venue.name} anyway?`}
          confirmLabel={replaced === null ? 'Send request' : 'Switch request'}
          tone="primary"
          isBusy={isSending}
          error={null}
          onConfirm={confirmSend}
          onCancel={cancelSend}
        >
          <p>
            {venue.name} does not suit {forRequirement ?? 'the event'}. Your justification goes to
            Venue Staff with the request.
          </p>
        </ConfirmDialog>
      )}
    </div>
  )
}
