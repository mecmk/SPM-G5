import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import {
  approveBooking,
  changeHoldExpiry,
  getBooking,
  rejectBooking,
  type Booking,
} from '../api/bookings'
import { formatApiError } from '../api/client'
import { getEvent, type EventDetail } from '../api/events'
import { getVenue, getVenueCalendar, type Venue } from '../api/venues'
import { Chip } from '../components/Chip'
import { ReplacementNote } from '../components/ReplacementNote'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { VenueAvailabilityCalendar } from '../components/VenueAvailabilityCalendar'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import { BOOKING_REQUESTS_PATH } from '../routes'
import {
  bookingOutcomeLabels,
  closingReason,
  EXPIRED_BOOKING_STATUS,
  HOLD_EXPIRES_LABEL,
  isReleasedBySafetyReview,
  openHoldExpiry,
  PENDING_BOOKING_STATUS,
  RELEASED_BY_SAFETY_REVIEW_LABEL,
  VENUE_UNAVAILABLE_LABEL,
} from '../shared/bookingStatus'
import {
  CANCELLED_AT_LABEL,
  formatDate,
  formatDateTime,
  formatTime,
  inputToInstant,
  instantToInput,
  nowAsInput,
} from '../shared/format'
import { singaporeDateOf, startOfMonthOf, useVenueCalendar } from '../shared/useVenueCalendar'
import { holdExpiryRefusal } from './holdExpiry'
import { venueStaffOutsideHoursNotice } from './turnaround'

const NOT_RECORDED = 'Not recorded'

const DAY_PANEL_ID = 'booking-venue-calendar-day-panel'

function layoutName(venue: Venue, layoutCode: string | null): string {
  if (layoutCode === null) return 'Any'
  return venue.layouts.find((layout) => layout.code === layoutCode)?.name ?? layoutCode
}

/**
 * Story 13.1.3: the requested venue's calendar, so Venue Staff can see what else holds it before
 * deciding. AC2: it opens on the month the request starts in, with that day's list open. Mounted
 * only once the booking has loaded, so the month it opens on is known from the start.
 */
function BookingVenueAvailability({ booking }: { booking: Booking }) {
  const loadWindows = useCallback(
    (startsAt: string, endsAt: string) => getVenueCalendar(booking.venue_id, startsAt, endsAt),
    [booking.venue_id],
  )
  // AC4: a decision made on the page changes the status, which loads the month on screen again,
  // so the request's day shows it booked, or no longer there once rejected. Story 12.7 AC1: so
  // does a new expiry, which the request's day shows.
  const calendar = useVenueCalendar(
    loadWindows,
    startOfMonthOf(booking.starts_at),
    `${booking.status} ${booking.hold_expires_at}`,
  )
  return (
    <section className="card stack" aria-labelledby="booking-availability-heading">
      <h2 id="booking-availability-heading">Venue availability</h2>
      <VenueAvailabilityCalendar
        month={calendar.month}
        onMonthChange={calendar.setMonth}
        windows={calendar.windows}
        now={calendar.now}
        error={calendar.error}
        isLoading={calendar.isLoading}
        dayPanelId={DAY_PANEL_ID}
        initialOpenDay={singaporeDateOf(booking.starts_at)}
      />
    </section>
  )
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
 * Story 13.2.1: a Reject action alongside it, requiring a reason.
 *
 * Story 13.1.3: the requested venue's calendar beside the details, so on a wide screen it sits
 * just under Approve and Reject and the decision does not mean scrolling back up; on a narrow one
 * it stacks below the details.
 *
 * Story 11.1 AC3: a request for a venue that did not suit the event shows the coordinator's
 * justification, from the booking already loaded here.
 *
 * Story 12.7 (the customer's hold, 12 Oct 2026): approving starts the booking's tentative hold,
 * so the Approve dialog asks when it expires, with no default (AC1). An approved booking whose
 * hold is open shows its expiry, and Change expiry gives it a new one, which the request's day in
 * the calendar shows once saved (AC7). AC5: both dialogs refuse no expiry, a time that is not in
 * the future, or one after the booked period starts, before sending it. An expired booking shows
 * when its hold expired instead (AC3). Decided 12 Oct 2026: every change needs a reason, refused
 * blank before sending, and the latest change - who made it, when and why - shows beside the
 * expiry.
 *
 * f12.1.2 (story 12.1 AC17): a request whose setup or teardown runs outside the venue's opening
 * hours says so under its title, with the booked period, so Venue Staff weigh it as they decide.
 */
export function BookingRequestDetailPage() {
  const { bookingId = '' } = useParams()
  const [booking, setBooking] = useState<Booking | null>(null)
  const [venue, setVenue] = useState<Venue | null>(null)
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isConfirmingApprove, setIsConfirmingApprove] = useState(false)
  const [approveExpiry, setApproveExpiry] = useState('')
  const [isApproving, setIsApproving] = useState(false)
  const [approveError, setApproveError] = useState<string | null>(null)
  const [isConfirmingReject, setIsConfirmingReject] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [isRejecting, setIsRejecting] = useState(false)
  const [rejectError, setRejectError] = useState<string | null>(null)
  const [isChangingExpiry, setIsChangingExpiry] = useState(false)
  const [newExpiry, setNewExpiry] = useState('')
  const [expiryReason, setExpiryReason] = useState('')
  const [isSavingExpiry, setIsSavingExpiry] = useState(false)
  const [expiryError, setExpiryError] = useState<string | null>(null)

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
    setApproveExpiry('')
    setIsConfirmingApprove(true)
  }

  function cancelApprove() {
    setIsConfirmingApprove(false)
  }

  /** Story 12.7 AC1/AC5: the hold's expiry is checked before the approval is sent. */
  async function confirmApprove() {
    if (!booking || !event) return
    const refusal = holdExpiryRefusal(approveExpiry, booking.held_from)
    if (refusal !== null) {
      setApproveError(refusal)
      return
    }
    setIsApproving(true)
    setApproveError(null)
    try {
      const updated = await approveBooking(
        booking.id,
        { hold_expires_at: inputToInstant(approveExpiry) },
        event.name,
      )
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
      setRejectError(ERROR_REGISTRY.BOOKING_REASON_REQUIRED.message)
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

  /** Story 12.7 AC7: the dialog opens on the current expiry, to move from. */
  function askToChangeExpiry() {
    const openHold = booking && openHoldExpiry(booking)
    if (!openHold) return
    setExpiryError(null)
    setNewExpiry(instantToInput(openHold))
    setExpiryReason('')
    setIsChangingExpiry(true)
  }

  function cancelChangeExpiry() {
    setIsChangingExpiry(false)
  }

  /** Story 12.7 AC5: what the server would refuse is refused here first, with nothing sent -
   * the reason too (decided 12 Oct 2026). */
  function expiryRefusal(heldFrom: string): string | null {
    const refusal = holdExpiryRefusal(newExpiry, heldFrom)
    if (refusal !== null) return refusal
    if (expiryReason.trim() === '') {
      return ERROR_REGISTRY.BOOKING_HOLD_EXPIRY_REASON_REQUIRED.message
    }
    return null
  }

  async function confirmChangeExpiry() {
    if (!booking || !event) return
    const refusal = expiryRefusal(booking.held_from)
    if (refusal !== null) {
      setExpiryError(refusal)
      return
    }
    setIsSavingExpiry(true)
    setExpiryError(null)
    try {
      const updated = await changeHoldExpiry(
        booking.id,
        {
          hold_expires_at: inputToInstant(newExpiry),
          hold_expiry_change_reason: expiryReason.trim(),
        },
        event.name,
      )
      setBooking(updated)
      setIsChangingExpiry(false)
    } catch (err) {
      setExpiryError(formatApiError(err))
    } finally {
      setIsSavingExpiry(false)
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
  // Story 2.7: the facilities of the venue requirement a request carries - story 12.5 AC1: the
  // one it names; none for an additional venue.
  const requiredFacilities =
    event.venue_requirements.find((requirement) => requirement.id === booking.venue_requirement_id)
      ?.facilities ?? []
  const isPending = booking.status === PENDING_BOOKING_STATUS
  const isVenueUnavailable = booking.venue_unavailable_marked_at !== null
  // Story 12.7 AC1/AC3: an approved booking's open hold, or the one an expired booking lost.
  const openHold = openHoldExpiry(booking)
  const shownHold =
    openHold ?? (booking.status === EXPIRED_BOOKING_STATUS ? booking.hold_expires_at : null)
  // f12.1.2 (story 12.1 AC17): a setup or teardown outside the venue's opening hours, if any.
  const outsideHoursNotice = venueStaffOutsideHoursNotice(
    booking,
    venue.operating_hours_start,
    venue.operating_hours_end,
  )

  return (
    <div className="page page-wide">
      <Link to={BOOKING_REQUESTS_PATH} className="back-link">
        ← Back to Booking Requests
      </Link>

      <div className="item-card-header booking-detail-header">
        <div className="cluster">
          <h1>{event.name}</h1>
          <StatusBadge status={booking.status} />
        </div>
        {isPending && (
          <div className="cluster">
            <button
              type="button"
              className="brand button-sm"
              disabled={isVenueUnavailable}
              aria-describedby={isVenueUnavailable ? 'booking-unavailable-notice' : undefined}
              onClick={askToApprove}
            >
              Approve
            </button>
            <button type="button" className="danger-solid button-sm" onClick={askToReject}>
              Reject
            </button>
          </div>
        )}
      </div>

      {outsideHoursNotice !== null && <p className="warning">{outsideHoursNotice}</p>}
      {/* Story 12.6 AC3/AC6: a replacement says what it replaces and what approving it releases. */}
      <ReplacementNote
        replacesVenueName={booking.replaces_venue_name}
        approvalReleasesVenueName={booking.approval_releases_venue_name}
        originalIsMarked={booking.original_is_marked}
      />
      {/* Story 9.4 AC3: the venue is unavailable for part of this request's held period, pending or
          approved alike. AC7: a pending request cannot be approved while the closure stands; it can
          still be rejected. */}
      {booking.venue_unavailable_marked_at !== null && (
        <section
          id="booking-unavailable-notice"
          className="subtle-block booking-hold"
          role="status"
        >
          <div>
            <Chip tone="warning" label={VENUE_UNAVAILABLE_LABEL} />
            <p>
              This venue is unavailable for part of this request&apos;s held period (flagged{' '}
              {formatDateTime(booking.venue_unavailable_marked_at)}).
              {isPending && ' It cannot be approved while the closure stands.'}
            </p>
          </div>
        </section>
      )}

      {shownHold && (
        <section className="subtle-block booking-hold" aria-labelledby="booking-hold-heading">
          <div>
            <h2 id="booking-hold-heading" className="fact-label">
              {openHold ? HOLD_EXPIRES_LABEL : 'Hold expired'}
            </h2>
            <p>{formatDateTime(shownHold)}</p>
            {/* Decided 12 Oct 2026: the latest change to the expiry - who, when and why. */}
            {booking.hold_expiry_changed_by !== null && booking.hold_expiry_changed_at !== null && (
              <>
                <p className="small muted">
                  Changed by {booking.hold_expiry_changed_by.full_name} on{' '}
                  {formatDateTime(booking.hold_expiry_changed_at)}
                </p>
                <p>
                  <span className="fact-label">Reason</span>
                  <br />
                  {booking.hold_expiry_change_reason}
                </p>
              </>
            )}
          </div>
          {openHold && (
            <button type="button" className="secondary button-sm" onClick={askToChangeExpiry}>
              Change expiry
            </button>
          )}
        </section>
      )}

      {/* Story 6.2 AC16: when a cancelled booking was approved, if it was, beside when it was
          cancelled. */}
      {booking.cancelled_at !== null && booking.decided_at !== null && (
        <p className="subtle-block">
          <span className="fact-label">{bookingOutcomeLabels(booking).when}</span>
          <br />
          {formatDateTime(booking.decided_at)}
        </p>
      )}

      {/* Story 6.2 AC16: when the booking was cancelled. */}
      {booking.cancelled_at !== null && (
        <p className="subtle-block">
          <span className="fact-label">{CANCELLED_AT_LABEL}</span>
          <br />
          {formatDateTime(booking.cancelled_at)}
        </p>
      )}

      {closingReason(booking) !== null && (
        <p className="subtle-block">
          {isReleasedBySafetyReview(booking) && (
            <>
              <strong>{RELEASED_BY_SAFETY_REVIEW_LABEL}</strong>
              <br />
            </>
          )}
          <span className="fact-label">{bookingOutcomeLabels(booking).why}</span>
          <br />
          {closingReason(booking)}
        </p>
      )}

      {/* Story 11.1 AC3: the coordinator's justification for requesting a venue that does not
       *  suit the event, for Venue Staff to weigh. Only a request that overrode the check has one. */}
      {booking.suitability_override_reason !== null && (
        <section className="subtle-block" aria-labelledby="booking-override-heading">
          <h2 id="booking-override-heading" className="fact-label">
            Why this venue was requested
          </h2>
          <p>{booking.suitability_override_reason}</p>
        </section>
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

        <div className="booking-detail-split">
          <div className="stack">
            <section className="card stack" aria-labelledby="booking-requirements-heading">
              <h2 id="booking-requirements-heading">Venue requirements</h2>
              <div>
                <p className="fact-label">Room layout</p>
                <p className="fact-value">{layoutName(venue, booking.required_layout_code)}</p>
              </div>
              <div>
                <p className="fact-label">Required facilities</p>
                <div className="cluster">
                  {requiredFacilities.length === 0 && <p className="muted">{NOT_RECORDED}</p>}
                  {requiredFacilities.map((item) => (
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

          <BookingVenueAvailability booking={booking} />
        </div>
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
          {/* Story 12.7 AC1/AC5: the hold this approval starts, and when it expires. */}
          <p>
            It is held until the event is confirmed. Choose when the hold expires if it is not, no
            later than the start of the booked period, {formatDateTime(booking.held_from)}.
          </p>
          <label>
            {HOLD_EXPIRES_LABEL}
            <input
              type="datetime-local"
              value={approveExpiry}
              min={nowAsInput()}
              max={instantToInput(booking.held_from)}
              onChange={(event) => setApproveExpiry(event.target.value)}
              disabled={isApproving}
            />
          </label>
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

      {isChangingExpiry && (
        <ConfirmDialog
          title="Change when this hold expires"
          confirmLabel="Save expiry"
          tone="primary"
          isBusy={isSavingExpiry}
          error={expiryError}
          onConfirm={confirmChangeExpiry}
          onCancel={cancelChangeExpiry}
        >
          <p>
            {venue.name} is held for {event.name} until the event is confirmed or its hold expires.
            The hold can expire no later than the start of its booked period,{' '}
            {formatDateTime(booking.held_from)}.
          </p>
          <label>
            New expiry
            <input
              type="datetime-local"
              value={newExpiry}
              min={nowAsInput()}
              max={instantToInput(booking.held_from)}
              onChange={(event) => setNewExpiry(event.target.value)}
              disabled={isSavingExpiry}
            />
          </label>
          <label>
            Reason
            <textarea
              value={expiryReason}
              onChange={(event) => setExpiryReason(event.target.value)}
              rows={3}
              disabled={isSavingExpiry}
            />
          </label>
        </ConfirmDialog>
      )}
    </div>
  )
}
