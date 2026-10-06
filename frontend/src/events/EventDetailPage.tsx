import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import {
  listBookingsForEvent,
  withdrawBooking,
  type BookingOutcome,
  type BookingStatus,
} from '../api/bookings'
import { formatApiError, mediaUrl } from '../api/client'
import { assignCoordinator, listCoordinators, type CoordinatorOption } from '../api/coordination'
import {
  approveEvent,
  CLARIFICATION_MESSAGE_MAX_LENGTH,
  getEvent,
  listClarifications,
  rejectEvent,
  requestClarification,
  type Clarification,
  type EventDetail,
  type RequiredFacility,
  type VenueRequirement,
} from '../api/events'
import { useAuth } from '../auth/authContext'
import { PERMISSIONS } from '../auth/permissions'
import { Chip } from '../components/Chip'
import { ClarificationHistory, type ClarificationEntry } from '../components/ClarificationHistory'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import type { EventCardBackState } from '../components/EventCard'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { Icon, type IconName } from '../components/Icon'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import {
  eventEditRoutinePath,
  HOME_PATH,
  VENUE_CATALOGUE_PATH,
  venueSearchPath,
  type VenueSearch,
} from '../routes'
import { AWAITING_DECISION_STATUSES, TERMINAL_STATUSES } from '../shared/eventStatus'
import {
  formatDate,
  formatDateTime,
  formatSchedule,
  formatTime,
  instantToInput,
} from '../shared/format'
import { canRequestVenueFor, venueRequestTermsFor } from '../shared/venueRequest'

const NOT_RECORDED = 'Not recorded'
const NOT_YET_ASSIGNED = 'Not yet assigned'
const NOT_YET_SCHEDULED = 'Not yet scheduled'
const PENDING_BOOKING_STATUS: BookingStatus = 'PENDING'

/** Story 13.2.1 AC4: how each venue booking outcome reads on the event page - label, colour,
 * icon and the status sentence, matching the wording a Venue Staff decision already produces. */
interface BookingOutcomePresentation {
  label: string
  tone: 'success' | 'warning' | 'danger' | 'neutral'
  icon: IconName
  message: string
}

const BOOKING_OUTCOME: Record<BookingStatus, BookingOutcomePresentation> = {
  APPROVED: {
    label: 'Approved',
    tone: 'success',
    icon: 'check-circle',
    message: 'This venue booking has been approved and the venue is confirmed for this event.',
  },
  PENDING: {
    label: 'Pending',
    tone: 'warning',
    icon: 'clock',
    message: 'Awaiting review by Venue Staff.',
  },
  REJECTED: {
    label: 'Rejected',
    tone: 'danger',
    icon: 'x-circle',
    message: 'This booking request was rejected.',
  },
  WITHDRAWN: {
    label: 'Withdrawn',
    tone: 'neutral',
    icon: 'x-circle',
    message: 'This booking request was withdrawn.',
  },
  CANCELLED: {
    label: 'Cancelled',
    tone: 'neutral',
    icon: 'x-circle',
    message: 'This booking was cancelled.',
  },
}

/** One required facility, as its quantity and notes make it distinct. */
function describeFacility(facility: RequiredFacility): string {
  const quantity = facility.quantity === null ? '' : ` ×${facility.quantity}`
  const notes = facility.notes === null ? '' : ` (${facility.notes})`
  return `${facility.name}${quantity}${notes}`
}

/** "None", "1 hr", "1 hr 30 min" or "45 min" - the setup/teardown line's duration wording. */
function formatMinutesDuration(minutes: number): string {
  if (minutes === 0) return 'None'
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  const parts: string[] = []
  if (hours > 0) parts.push(`${hours} hr${hours > 1 ? 's' : ''}`)
  if (remainder > 0) parts.push(`${remainder} min`)
  return parts.join(' ')
}

/**
 * f12.1.1 (story 12.1 AC15): the catalogue search Find a venue opens, holding only what the event
 * recorded. Story 2.7: for the event's first venue requirement, the one a request carries - its
 * times, number of people as the minimum capacity, layout and facilities - plus the event's
 * accessibility needs. An event with no requirements searches by its own dates and attendance.
 */
function venueSearchFor(event: EventDetail): VenueSearch {
  const terms = venueRequestTermsFor(event)
  return {
    eventId: event.id,
    capacity: terms.capacity ?? undefined,
    from: terms.startsAt ? instantToInput(terms.startsAt) : undefined,
    to: terms.endsAt ? instantToInput(terms.endsAt) : undefined,
    layout: terms.layoutCode ?? undefined,
    facilities: terms.facilities.map((facility) => facility.code),
    accessibilityFeatures: event.accessibility_needs.map((need) => need.code),
  }
}

/**
 * Story 2.7 AC4: a requirement's times. Both dates when it runs over more than one day (review of
 * PR #84) - `formatSchedule` gives only the first date, which would make a two-day requirement read
 * as one.
 */
function describeVenueRequirementTimes(startsAt: string, endsAt: string): string {
  return formatDate(startsAt) === formatDate(endsAt)
    ? formatSchedule(startsAt, endsAt)
    : `${formatDateTime(startsAt)} – ${formatDateTime(endsAt)}`
}

/** Story 2.7 AC4: one requirement's number of people and times, as one line. */
function describeVenueRequirementFacts(requirement: VenueRequirement): string {
  const facts = [
    requirement.capacity === null ? null : `${requirement.capacity} people`,
    requirement.starts_at && requirement.ends_at
      ? describeVenueRequirementTimes(requirement.starts_at, requirement.ends_at)
      : null,
  ].filter((fact) => fact !== null)
  return facts.length > 0 ? facts.join(' · ') : NOT_RECORDED
}

function formatHeroMeta(event: EventDetail): string {
  const schedule =
    event.starts_at && event.ends_at
      ? formatSchedule(event.starts_at, event.ends_at)
      : NOT_YET_SCHEDULED
  return `${schedule} · Organised by ${event.organiser_name}`
}

/**
 * Story 7.1 - the canonical event details page.
 * AC1: core event details, venue requirements, accessibility requirements, equipment
 * requirements, status and assigned coordinator, all in one place.
 * AC2: which events a signed-in user may open is enforced by the backend (story 2.1 AC8's
 * `GET /events/{id}`) - an event that does not exist, or is not this user's to see, comes back as
 * the same "not found" response, so this page never learns the difference.
 * AC3: this page only ever renders fields, it never edits them, so every field the viewer's role
 * cannot change is simply shown, never hidden.
 *
 * Story 7.2: also renders the contact details and internal notes and, for the assigned Event
 * Coordinator on a non-terminal event, an "Edit routine information" action (internal notes only).
 * Internal notes are coordinator-only (never shown to the organiser), matching the backend.
 *
 * Story 13.2.1 AC4: a "Venue booking" card for whoever holds BOOKINGS_READ (Event Coordinator,
 * Venue Staff, Technical Support - not the organiser, who never held that permission), listing
 * every venue booking ever raised for the event, most recent first, each with its status and,
 * once rejected, its reason.
 *
 * Story 4.4/4.5: also renders Approve and Reject actions for the assigned Event Coordinator
 * while the request awaits a decision. Approving moves it to PLANNING; rejecting requires a
 * reason and moves it to REJECTED. Both are offered from the same set of statuses.
 */
export function EventDetailPage() {
  const { eventId = '' } = useParams()
  const location = useLocation()
  const { user, can } = useAuth()
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [hasImageFailed, setHasImageFailed] = useState(false)
  const [clarifications, setClarifications] = useState<Clarification[] | null>(null)
  const [clarificationsError, setClarificationsError] = useState<string | null>(null)
  const [bookings, setBookings] = useState<BookingOutcome[] | null>(null)
  const [bookingError, setBookingError] = useState<string | null>(null)
  const canReadBooking = can(PERMISSIONS.BOOKINGS_READ)
  const [isConfirmingApprove, setIsConfirmingApprove] = useState(false)
  const [isApproving, setIsApproving] = useState(false)
  const [approveError, setApproveError] = useState<string | null>(null)
  const [isConfirmingReject, setIsConfirmingReject] = useState(false)
  const [isRejecting, setIsRejecting] = useState(false)
  const [rejectError, setRejectError] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [clarificationMessage, setClarificationMessage] = useState('')
  const [isRequestingClarification, setIsRequestingClarification] = useState(false)
  const [clarificationRequestError, setClarificationRequestError] = useState<string | null>(null)
  const [pendingWithdraw, setPendingWithdraw] = useState<BookingOutcome | null>(null)
  const [isWithdrawing, setIsWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<string | null>(null)
  const [isConfirmingReassign, setIsConfirmingReassign] = useState(false)
  const [isReassigning, setIsReassigning] = useState(false)
  const [reassignError, setReassignError] = useState<string | null>(null)
  const [eligibleCoordinators, setEligibleCoordinators] = useState<CoordinatorOption[] | null>(null)
  const [selectedCoordinatorId, setSelectedCoordinatorId] = useState('')

  useEffect(() => {
    let cancelled = false
    getEvent(eventId)
      .then((data) => {
        if (!cancelled) setEvent(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [eventId])

  useEffect(() => {
    if (event === null) return undefined
    const canViewClarifications =
      user !== null && (event.organiser_id === user.id || event.assigned_coordinator_id === user.id)
    if (!canViewClarifications) return undefined
    let cancelled = false
    listClarifications(eventId)
      .then((data) => {
        if (!cancelled) setClarifications(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setClarificationsError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [eventId, event, user])

  useEffect(() => {
    if (!canReadBooking) return undefined
    let cancelled = false
    listBookingsForEvent(eventId)
      .then((data) => {
        if (!cancelled) setBookings(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setBookingError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [eventId, canReadBooking])

  /** Story 5.2 AC4: loaded only once the Reassign dialog opens, leaving the event's current
   *  coordinator out - they are not a valid target for their own event. */
  useEffect(() => {
    if (!isConfirmingReassign) return undefined
    let cancelled = false
    listCoordinators(eventId)
      .then((options) => {
        if (cancelled) return
        setEligibleCoordinators(options)
        setSelectedCoordinatorId(options.length > 0 ? options[0].id : '')
      })
      .catch((err: unknown) => {
        if (!cancelled) setReassignError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [isConfirmingReassign, eventId])

  if (error) {
    return (
      <div className="page">
        <p role="alert" className="error">
          {error}
        </p>
      </div>
    )
  }
  if (!event) return <LoadingState label="Loading the event…" />

  function markImageFailed() {
    setHasImageFailed(true)
  }

  function askToApprove() {
    setApproveError(null)
    setIsConfirmingApprove(true)
  }

  function cancelApprove() {
    setIsConfirmingApprove(false)
  }

  async function confirmApprove() {
    if (!event) return
    setIsApproving(true)
    setApproveError(null)
    try {
      const updated = await approveEvent(event.id, event.name)
      setEvent(updated)
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
    if (!event) return
    if (!rejectReason.trim()) {
      setRejectError(ERROR_REGISTRY.EVENT_REJECTION_REASON_REQUIRED.message)
      return
    }
    setIsRejecting(true)
    setRejectError(null)
    try {
      const updated = await rejectEvent(event.id, rejectReason, event.name)
      setEvent(updated)
      setIsConfirmingReject(false)
    } catch (err) {
      setRejectError(formatApiError(err))
    } finally {
      setIsRejecting(false)
    }
  }

  async function confirmRequestClarification() {
    if (!event) return
    if (!clarificationMessage.trim()) {
      setClarificationRequestError(ERROR_REGISTRY.EVENT_CLARIFICATION_MESSAGE_REQUIRED.message)
      return
    }
    setIsRequestingClarification(true)
    setClarificationRequestError(null)
    try {
      const entry = await requestClarification(event.id, clarificationMessage, event.name)
      setClarifications((current) => (current ?? []).concat(entry))
      setEvent((current) => (current ? { ...current, status: 'CLARIFICATION_REQUESTED' } : current))
      setClarificationMessage('')
    } catch (err) {
      setClarificationRequestError(formatApiError(err))
      // A 403 or 409 means the page is out of date: reload it so the form, Approve and Reject go
      // with the state they belonged to. Ignore a failed reload - it must not lose the message.
      getEvent(event.id).then(setEvent, () => {})
    } finally {
      setIsRequestingClarification(false)
    }
  }

  function askToWithdraw(booking: BookingOutcome) {
    setWithdrawError(null)
    setPendingWithdraw(booking)
  }

  function cancelWithdraw() {
    setPendingWithdraw(null)
  }

  async function confirmWithdraw() {
    if (!pendingWithdraw) return
    setIsWithdrawing(true)
    setWithdrawError(null)
    try {
      const updated = await withdrawBooking(pendingWithdraw.id, pendingWithdraw.venue_name)
      setBookings(
        (current) =>
          current &&
          current.map((booking) =>
            booking.id === updated.id
              ? {
                  ...booking,
                  status: updated.status,
                  decided_at: updated.decided_at,
                  decision_reason: updated.decision_reason,
                }
              : booking,
          ),
      )
      setPendingWithdraw(null)
    } catch (err) {
      setWithdrawError(formatApiError(err))
    } finally {
      setIsWithdrawing(false)
    }
  }

  function askToReassign() {
    setReassignError(null)
    setEligibleCoordinators(null)
    setSelectedCoordinatorId('')
    setIsConfirmingReassign(true)
  }

  function cancelReassign() {
    setIsConfirmingReassign(false)
  }

  async function confirmReassign() {
    if (!event) return
    if (!selectedCoordinatorId) {
      setReassignError('There is no other active Event Coordinator to reassign this to.')
      return
    }
    setIsReassigning(true)
    setReassignError(null)
    try {
      await assignCoordinator(event.id, selectedCoordinatorId)
      const updated = await getEvent(event.id)
      setEvent(updated)
      setIsConfirmingReassign(false)
    } catch (err) {
      setReassignError(formatApiError(err))
    } finally {
      setIsReassigning(false)
    }
  }

  const backState = location.state as EventCardBackState | null
  const backTo = backState?.from ?? HOME_PATH
  const backLabel = backState?.fromLabel ?? 'Home'
  const canSeeInternalNotes = can(PERMISSIONS.EVENTS_REVIEW)
  const isAssignedCoordinator = event.assigned_coordinator_id === user?.id
  const canEditRoutineInformation =
    can(PERMISSIONS.EVENTS_EDIT_ROUTINE) &&
    isAssignedCoordinator &&
    !TERMINAL_STATUSES.includes(event.status)
  /** Story 4.4/4.5: only the assigned coordinator, holding events:review, may decide a request
   *  that is still awaiting one - mirroring the backend's own record-level and status checks. */
  const canApprove =
    can(PERMISSIONS.EVENTS_REVIEW) &&
    isAssignedCoordinator &&
    AWAITING_DECISION_STATUSES.includes(event.status)
  const canReject =
    can(PERMISSIONS.EVENTS_REVIEW) &&
    isAssignedCoordinator &&
    AWAITING_DECISION_STATUSES.includes(event.status)
  /** Story 4.2 AC4/AC5/AC6: only the assigned coordinator, holding events:review, may ask the
   *  organiser a question, while the request is Under Review or already awaits a response to an
   *  earlier round (a follow-up has to work from CLARIFICATION_REQUESTED too, since nothing until
   *  story 4.3 moves the event back to Under Review) - mirroring the backend's own
   *  `_AWAITING_DECISION_STATUSES` gate on `request_clarification`. */
  const canRequestClarification =
    can(PERMISSIONS.EVENTS_REVIEW) &&
    isAssignedCoordinator &&
    AWAITING_DECISION_STATUSES.includes(event.status)
  /** Story 5.2 AC1/AC6: only the currently assigned coordinator may reassign, and only on an
   *  event that is not completed, cancelled or rejected - mirroring the backend's
   *  `ASSIGNABLE_STATUSES` (a draft never reaches this: it has no coordinator to be one of). */
  const canReassign =
    can(PERMISSIONS.EVENTS_REVIEW) &&
    isAssignedCoordinator &&
    !TERMINAL_STATUSES.includes(event.status)
  /** f12.1.1 (story 12.1 AC15): Find a venue, only for whoever may request one for the event -
   *  its assigned coordinator, while it can take a booking. */
  const canFindVenue = canRequestVenueFor(event, user, can)
  /** Story 4.6 AC2: only the organiser and the assigned coordinator may see the clarification
   *  history, mirroring the backend's `_can_view_clarifications`. */
  const canViewClarifications =
    user !== null && (event.organiser_id === user.id || event.assigned_coordinator_id === user.id)

  const clarificationEntries: ClarificationEntry[] | null =
    clarifications === null
      ? null
      : clarifications.map((entry) => ({
          id: entry.id,
          kind: entry.kind,
          authorId: entry.author_id,
          authorName: entry.author_name,
          message: entry.message,
          createdAt: entry.created_at,
        }))

  return (
    <div className="page page-wide event-detail-page">
      <Link to={backTo} className="back-link">
        ← {backLabel}
      </Link>
      {(canEditRoutineInformation || canApprove || canReject || canReassign) && (
        <div className="page-header actions-only">
          <div className="page-actions">
            {canEditRoutineInformation && (
              <Link to={eventEditRoutinePath(event.id)} className="button">
                Edit routine information
              </Link>
            )}
            {canApprove && (
              <button type="button" className="brand" onClick={askToApprove}>
                Approve
              </button>
            )}
            {canReject && (
              <button type="button" className="danger" onClick={askToReject}>
                Reject
              </button>
            )}
            {canReassign && (
              <button type="button" className="secondary" onClick={askToReassign}>
                Reassign
              </button>
            )}
          </div>
        </div>
      )}

      <div className="venue-hero">
        {event.cover_image_url && !hasImageFailed ? (
          <img
            className="venue-hero-picture"
            src={mediaUrl(event.cover_image_url) ?? undefined}
            alt=""
            onError={markImageFailed}
          />
        ) : (
          <span aria-hidden="true">
            <Icon name="image" size={36} />
          </span>
        )}
        <div className="venue-hero-overlay">
          <h1>{event.name}</h1>
          <p className="venue-hero-meta">{formatHeroMeta(event)}</p>
        </div>
      </div>

      <div className="stack">
        <div className="stat">
          <p className="eyebrow">Event status</p>
          <EventStatusBadge status={event.status} />
        </div>

        <div className="stat-grid">
          <div className="stat">
            <Icon name="calendar" />
            <div className="stat-body">
              <p className="stat-value">
                {event.starts_at ? formatDate(event.starts_at) : NOT_RECORDED}
              </p>
              <p className="eyebrow">Date</p>
            </div>
          </div>
          <div className="stat">
            <Icon name="calendar-check" />
            <div className="stat-body">
              <p className="stat-value">
                {event.starts_at && event.ends_at
                  ? `${formatTime(event.starts_at)}–${formatTime(event.ends_at)}`
                  : NOT_RECORDED}
              </p>
              <p className="eyebrow">Time</p>
            </div>
          </div>
          <div className="stat">
            <Icon name="people" />
            <div className="stat-body">
              <p className="stat-value">{event.expected_attendance ?? NOT_RECORDED}</p>
              <p className="eyebrow">Expected attendance</p>
            </div>
          </div>
          {/* Story 2.6 AC12/AC13: a draft has no coordinator to show yet, so the stat is left
              out entirely rather than reading "Not yet assigned" like a submitted request would. */}
          {event.status !== 'DRAFT' && (
            <div className="stat">
              <Icon name="person" />
              <div className="stat-body">
                <p className="stat-value">{event.assigned_coordinator_name ?? NOT_YET_ASSIGNED}</p>
                {event.assigned_coordinator_email && (
                  <p className="small muted wrap-anywhere">{event.assigned_coordinator_email}</p>
                )}
                <p className="eyebrow">Assigned coordinator</p>
              </div>
            </div>
          )}
        </div>

        <section className="card stack" aria-labelledby="event-info-heading">
          <h2 id="event-info-heading">Event information</h2>
          <div className="row">
            <div>
              <p className="eyebrow">Purpose</p>
              <p>{event.purpose ?? NOT_RECORDED}</p>
            </div>
            <div>
              <p className="eyebrow">Description</p>
              <p>{event.description ?? NOT_RECORDED}</p>
            </div>
          </div>
          <hr className="divider" />
          <div className="row">
            <div>
              <p className="eyebrow">Contact name</p>
              <p>{event.contact_name ?? NOT_RECORDED}</p>
            </div>
            <div>
              <p className="eyebrow">Contact email</p>
              <p>{event.contact_email ?? NOT_RECORDED}</p>
            </div>
            <div>
              <p className="eyebrow">Contact phone</p>
              <p>{event.contact_phone ?? NOT_RECORDED}</p>
            </div>
          </div>
          {canSeeInternalNotes && (
            <div>
              <p className="eyebrow">Internal notes</p>
              <p>{event.internal_notes ?? NOT_RECORDED}</p>
            </div>
          )}
          <hr className="divider" />
          <div className="row">
            <div>
              <p className="eyebrow">Visibility</p>
              <p>{event.is_public ? 'Public' : 'Private'}</p>
            </div>
            <div>
              <p className="eyebrow">Organiser</p>
              <p>{event.organiser_name}</p>
            </div>
          </div>
        </section>

        {/* Story 2.1 AC8/AC19: the registration choice, and its dates once required, shown to
            whoever can already reach this page - the owning organiser and internal roles, same
            as everything else here. Opens/closes are left out entirely when not required, since
            the backend never stores them in that case (schemas.py's REGISTRATION_CONTRADICTION). */}
        <section className="card stack" aria-labelledby="registration-heading">
          <h2 id="registration-heading">Registration</h2>
          <div className="row">
            <div>
              <p className="eyebrow">Required</p>
              <p>{event.registration_required ? 'Yes' : 'No'}</p>
            </div>
            {event.registration_required && (
              <>
                <div>
                  <p className="eyebrow">Opens</p>
                  <p>
                    {event.registration_opens_at
                      ? formatDateTime(event.registration_opens_at)
                      : 'Immediately once approved'}
                  </p>
                </div>
                <div>
                  <p className="eyebrow">Closes</p>
                  <p>
                    {event.registration_closes_at
                      ? formatDateTime(event.registration_closes_at)
                      : NOT_RECORDED}
                  </p>
                </div>
              </>
            )}
          </div>
        </section>

        <div className="layout-half">
          <section className="card stack" aria-labelledby="venue-requirements-heading">
            <div className="card-heading">
              <h2 id="venue-requirements-heading">Venue requirements</h2>
              {canFindVenue && (
                <Link to={venueSearchPath(venueSearchFor(event))} className="button button-sm">
                  Find a venue
                </Link>
              )}
            </div>
            {event.venue_none_required && (
              <p className="muted">No venue is required for this event.</p>
            )}
            {!event.venue_none_required && event.venue_requirements.length === 0 && (
              <p className="muted">{NOT_RECORDED}</p>
            )}
            {event.venue_requirements.length > 0 && (
              <ul className="venue-requirement-list">
                {event.venue_requirements.map((requirement, index) => (
                  <li key={requirement.id} className="stack">
                    <div>
                      <p>
                        <strong>{requirement.name ?? `Venue requirement ${index + 1}`}</strong>
                      </p>
                      <p className="small muted">{describeVenueRequirementFacts(requirement)}</p>
                    </div>
                    <div>
                      <p className="eyebrow">Room layout</p>
                      <p>{requirement.layout_name ?? NOT_RECORDED}</p>
                    </div>
                    <div>
                      <p className="eyebrow">Required facilities</p>
                      {requirement.facilities.length === 0 ? (
                        <p className="muted">{NOT_RECORDED}</p>
                      ) : (
                        <div className="cluster">
                          {requirement.facilities.map((facility) => (
                            <Chip
                              key={facility.code}
                              tone="info"
                              label={describeFacility(facility)}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                    {requirement.notes && (
                      <div>
                        <p className="eyebrow">Other requirements</p>
                        <p>{requirement.notes}</p>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card stack" aria-labelledby="accessibility-heading">
            <h2 id="accessibility-heading">Accessibility</h2>
            {event.accessibility_none_required ? (
              <p className="muted">No accessibility needs recorded.</p>
            ) : event.accessibility_needs.length === 0 && !event.accessibility_notes ? (
              <p className="muted">Not yet specified.</p>
            ) : (
              <>
                {event.accessibility_needs.length > 0 && (
                  <div className="cluster">
                    {event.accessibility_needs.map((need) => (
                      <Chip
                        key={need.code}
                        tone="success"
                        label={need.notes ? `${need.name} (${need.notes})` : need.name}
                      />
                    ))}
                  </div>
                )}
                {event.accessibility_notes && (
                  <div>
                    <p className="eyebrow">Additional notes</p>
                    <p>{event.accessibility_notes}</p>
                  </div>
                )}
              </>
            )}
          </section>
        </div>

        {canReadBooking && bookingError && (
          <p role="alert" className="error">
            {bookingError}
          </p>
        )}

        {canReadBooking && bookings && bookings.length > 0 && (
          <section className="card stack" aria-labelledby="venue-booking-heading">
            <h2 id="venue-booking-heading" className="cluster">
              <Icon name="building" size={20} />
              Venue booking
            </h2>

            {bookings.map((booking) => {
              const bookingOutcome = BOOKING_OUTCOME[booking.status]
              return (
                <div
                  key={booking.id}
                  className={`booking-outcome-card booking-outcome-card-${bookingOutcome.tone}`}
                >
                  <div className="booking-outcome-main">
                    <div className="booking-outcome-thumb" aria-hidden="true">
                      <Icon name="image" size={28} />
                    </div>

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
                      <p className="muted">{booking.venue_location}</p>
                      <div className="booking-outcome-schedule small muted">
                        <span className="booking-outcome-schedule-item">
                          <Icon name="calendar" size={14} />
                          {formatDate(booking.starts_at)}
                        </span>
                        <span className="booking-outcome-schedule-item">
                          <Icon name="calendar-check" size={14} />
                          {formatTime(booking.starts_at)}–{formatTime(booking.ends_at)}
                        </span>
                      </div>
                      <p className="small muted">
                        Setup: {formatMinutesDuration(booking.setup_minutes)} · Event:{' '}
                        {formatTime(booking.starts_at)}–{formatTime(booking.ends_at)} · Teardown:{' '}
                        {formatMinutesDuration(booking.teardown_minutes)}
                      </p>
                    </div>
                  </div>

                  <div className="booking-outcome-message">
                    <Icon name={bookingOutcome.icon} size={18} />
                    <div>
                      <p>{bookingOutcome.message}</p>
                      {booking.decision_reason !== null && (
                        <p>
                          <span className="fact-label">Reason</span>
                          <br />
                          {booking.decision_reason}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Story 12.2 AC1/AC6: only the event's own assigned coordinator may withdraw,
                   *  and only while the request is still pending - mirrors the backend's own
                   *  relationship and status checks. */}
                  {booking.status === PENDING_BOOKING_STATUS && isAssignedCoordinator && (
                    <div className="cluster">
                      <button
                        type="button"
                        className="secondary button-sm"
                        onClick={() => askToWithdraw(booking)}
                      >
                        Withdraw
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </section>
        )}

        {/* Story 12.2 AC4: an event with no requests yet, with a way to raise one. */}
        {canReadBooking && bookings !== null && bookings.length === 0 && (
          <EmptyState>
            No venue booking requests yet.{' '}
            <Link to={VENUE_CATALOGUE_PATH}>Browse the venue catalogue</Link> to request one.
          </EmptyState>
        )}

        <section className="card stack" aria-labelledby="equipment-heading">
          <h2 id="equipment-heading">Equipment requirements</h2>
          {event.equipment.length === 0 ? (
            <p className="muted">No equipment requested.</p>
          ) : (
            <ul className="check-list">
              {event.equipment.map((item) => (
                <li key={item.id}>
                  <span className="grow-text">
                    {item.equipment_type_name}
                    {item.technical_notes && (
                      <>
                        <br />
                        <span className="small muted">{item.technical_notes}</span>
                      </>
                    )}
                  </span>
                  <span className="mono">×{item.quantity}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {canViewClarifications && (
          <ClarificationHistory
            status={event.status}
            decidedByName={event.decided_by_name}
            decidedAt={event.decided_at}
            decisionReason={event.decision_reason}
            entries={clarificationEntries}
            error={clarificationsError}
            currentUserId={user?.id ?? null}
          />
        )}

        {canRequestClarification && (
          <section className="card stack" aria-labelledby="post-clarification-heading">
            <p className="eyebrow" id="post-clarification-heading">
              Ask the organiser
            </p>
            <label>
              Message
              <textarea
                rows={3}
                maxLength={CLARIFICATION_MESSAGE_MAX_LENGTH}
                placeholder="What do you need clarified before deciding?"
                value={clarificationMessage}
                onChange={(e) => setClarificationMessage(e.target.value)}
              />
            </label>
            {clarificationRequestError && (
              <p role="alert" className="error">
                {clarificationRequestError}
              </p>
            )}
            <div className="page-actions">
              <button
                type="button"
                className="secondary"
                disabled={isRequestingClarification}
                onClick={confirmRequestClarification}
              >
                {isRequestingClarification ? 'Sending…' : 'Send clarification request'}
              </button>
            </div>
          </section>
        )}
      </div>

      {isConfirmingApprove && (
        <ConfirmDialog
          title="Approve this request?"
          confirmLabel="Approve"
          tone="primary"
          isBusy={isApproving}
          error={approveError}
          onConfirm={confirmApprove}
          onCancel={cancelApprove}
        >
          <p>{event.name} will move into planning.</p>
        </ConfirmDialog>
      )}
      {isConfirmingReject && (
        <ConfirmDialog
          title="Reject this request?"
          confirmLabel="Reject"
          isBusy={isRejecting}
          error={rejectError}
          onConfirm={confirmReject}
          onCancel={cancelReject}
        >
          <p>{event.name} will be rejected. This cannot be undone.</p>
          <label>
            Reason for rejection
            <textarea
              rows={3}
              placeholder="Shown to the organiser."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
            />
          </label>
        </ConfirmDialog>
      )}
      {pendingWithdraw && (
        <ConfirmDialog
          title="Withdraw this booking request?"
          confirmLabel="Withdraw"
          isBusy={isWithdrawing}
          error={withdrawError}
          onConfirm={confirmWithdraw}
          onCancel={cancelWithdraw}
        >
          <p>
            The request for {pendingWithdraw.venue_name} will be withdrawn and its hold on the venue
            released. Venue Staff will be told.
          </p>
        </ConfirmDialog>
      )}
      {isConfirmingReassign && (
        <ConfirmDialog
          title={`Reassign "${event.name}"?`}
          confirmLabel="Confirm reassignment"
          tone="primary"
          isBusy={isReassigning}
          error={reassignError}
          onConfirm={confirmReassign}
          onCancel={cancelReassign}
        >
          <p>Hand this event to a different active Event Coordinator.</p>
          <label>
            New coordinator
            <select
              value={selectedCoordinatorId}
              onChange={(e) => setSelectedCoordinatorId(e.target.value)}
              disabled={eligibleCoordinators === null || eligibleCoordinators.length === 0}
            >
              {eligibleCoordinators === null && <option value="">Loading…</option>}
              {eligibleCoordinators?.length === 0 && (
                <option value="">No other coordinators available</option>
              )}
              {eligibleCoordinators?.map((coordinator) => (
                <option key={coordinator.id} value={coordinator.id}>
                  {coordinator.full_name}
                </option>
              ))}
            </select>
          </label>
        </ConfirmDialog>
      )}
    </div>
  )
}
