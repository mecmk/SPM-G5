import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { listBookingsForEvent, withdrawBooking, type BookingOutcome } from '../api/bookings'
import { cancelEvent } from '../api/cancellations'
import { formatApiError, mediaUrl } from '../api/client'
import { fetchChangeRequestWindow, type ChangeRequestWindow } from '../api/changeRequests'
import {
  approveEvent,
  CLARIFICATION_MESSAGE_MAX_LENGTH,
  fetchEventReferenceData,
  getEvent,
  listClarifications,
  rejectEvent,
  requestClarification,
  respondToClarification,
  type Clarification,
  type EventDetail,
  type RequiredFacility,
  type VenueRequirement,
} from '../api/events'
import { listEventRegistrations, type EventRegistrationList } from '../api/registrations'
import { getEventSafety } from '../api/safety'
import { useAuth } from '../auth/authContext'
import { PERMISSIONS } from '../auth/permissions'
import { Chip } from '../components/Chip'
import { ClarificationHistory, type ClarificationEntry } from '../components/ClarificationHistory'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import type { EventCardBackState } from '../components/EventCard'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { Icon } from '../components/Icon'
import { RegistrationCount } from '../components/RegistrationCount'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import {
  eventCoordinatorEditPath,
  HOME_PATH,
  VENUE_CATALOGUE_PATH,
  registrationsReportPath,
  venueSearchPath,
} from '../routes'
import {
  bookingOutcomeLabels,
  EXPIRED_BOOKING_STATUS,
  closedAt,
  FIND_ANOTHER_LABEL,
  FIND_REPLACEMENT_LABEL,
  HOLD_EXPIRED_LABEL,
  HOLD_EXPIRES_LABEL,
  openHoldExpiry,
  PENDING_BOOKING_STATUS,
  replacedByLine,
  replacementRequestedLine,
  replacesLine,
  VENUE_UNAVAILABLE_LABEL,
} from '../shared/bookingStatus'
import {
  ACTIVE_EVENT_STATUSES,
  AWAITING_DECISION_STATUSES,
  CANCELLABLE_STATUSES,
  CHANGE_DECIDABLE_STATUSES,
  CHANGE_REQUESTABLE_STATUSES,
  CHANGE_REQUESTS_VISIBLE_STATUSES,
  CONTACT_EDITABLE_STATUSES,
  DETAILS_LOCKED_HINT,
  DETAILS_LOCKED_STATUSES,
  EQUIPMENT_OPEN_STATUSES,
  TERMINAL_STATUSES,
} from '../shared/eventStatus'
import {
  CANCELLED_AT_LABEL,
  formatDate,
  formatDateTime,
  formatSchedule,
  formatTime,
  NOT_YET_ASSIGNED,
} from '../shared/format'
import {
  FLAGGED_BY_SAFETY_REVIEW,
  SAFETY_REVIEW_STATUSES,
  flaggedArrangements,
} from '../shared/safetyReview'
import { useLoaded } from '../shared/useLoaded'
import {
  canRequestVenueFor,
  firstRequirementNeedingVenue,
  isMarked,
  offersWayToAnotherVenue,
  isReplaceable,
  replacementSearchFor,
  requirementName,
  unnamedRequirementLabel,
  venueSearchFor,
} from '../shared/venueRequest'
import { ChangeHistorySection } from './ChangeHistorySection'
import { ChangeRequestsSection } from './ChangeRequestsSection'
import { EquipmentRequestsSection } from './EquipmentRequestsSection'
import { BOOKING_OUTCOME, formatMinutesDuration } from './bookingOutcome'
import { OrganiserBookingsSection } from './OrganiserBookingsSection'
import { PointOfContactEditor } from './PointOfContactEditor'
import { ReassignDialog } from './ReassignDialog'
import { SafetyReviewSection } from './SafetyReviewSection'

const NOT_RECORDED = 'Not recorded'
const NOT_YET_SCHEDULED = 'Not yet scheduled'

/** Story 6.2 AC16: the status sentence of a booking, saying a booking cancelled with its event went
 * with it. The cancellation stamps the event and each booking it releases with one time, so a
 * booking an earlier change cancelled (19.2) keeps its own sentence. */
function bookingMessage(event: EventDetail, booking: BookingOutcome): string {
  if (
    booking.status === 'CANCELLED' &&
    event.cancelled_at !== null &&
    booking.cancelled_at === event.cancelled_at
  ) {
    return 'This booking was cancelled with its event.'
  }
  return BOOKING_OUTCOME[booking.status].message
}

/** Story 12.7 AC1 (the customer's hold, 12 Oct 2026): an approved booking whose hold is still
 * open is held for the event only until the event is confirmed or the hold expires, so it does
 * not read as confirmed for good. */
const OPEN_HOLD_MESSAGE =
  'Venue Staff approved this booking. The venue is held for the event until it is confirmed, or until the hold expires.'

/** One required facility, as its quantity and notes make it distinct. */
function describeFacility(facility: RequiredFacility): string {
  const quantity = facility.quantity === null ? '' : ` ×${facility.quantity}`
  const notes = facility.notes === null ? '' : ` (${facility.notes})`
  return `${facility.name}${quantity}${notes}`
}

/**
 * f12.1.1 (story 12.1 AC15) and story 8.4 AC1: the catalogue address Find a venue opens - a venue
 * requirement selected in its banner, with that requirement's filters. Story 12.5 AC2: the first
 * that needs a venue; AC5: none once every one has a request, for an additional venue. An event
 * with no requirements searches by its own dates and attendance (8.4 AC6).
 */
function findVenuePath(event: EventDetail, bookings: readonly BookingOutcome[]): string {
  return venueSearchPath(venueSearchFor(event, firstRequirementNeedingVenue(event, bookings)))
}

/** Story 12.5 AC4: the name of the venue requirement a booking is for, as the catalogue's banner
 *  names it; null for an additional venue (AC5). */
function bookedRequirementName(event: EventDetail, booking: BookingOutcome): string | null {
  const requirement = event.venue_requirements.find(
    (each) => each.id === booking.venue_requirement_id,
  )
  return requirement ? requirementName(event, requirement) : booking.venue_requirement_name
}

/** Story 2.7 AC4: one requirement's number of people and times, as one line. */
function describeVenueRequirementFacts(requirement: VenueRequirement): string {
  const facts = [
    requirement.capacity === null ? null : `${requirement.capacity} people`,
    requirement.starts_at && requirement.ends_at
      ? formatSchedule(requirement.starts_at, requirement.ends_at)
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
 * Story 7.2: also renders the contact details and internal notes, which are coordinator-only
 * (never shown to the organiser), matching the backend. The assigned Event Coordinator of an event
 * that is not closed gets one "Edit event" action, opening the 2.1 request form: internal notes
 * always, the organiser's details until the event is confirmed (AC4, AC10). AC12:
 * once confirmed, that coordinator is also told here that further changes go through the change
 * request process.
 *
 * Story 13.2.1 AC4: a "Venue booking" card for whoever holds BOOKINGS_READ (Event Coordinator,
 * Venue Staff, Technical Support - not the organiser, who never held that permission), listing
 * every venue booking ever raised for the event, most recent first, each with its status and,
 * once rejected, its reason.
 *
 * Story 13.2.2 AC1: once Venue Staff approve or reject a booking, its card also shows when they
 * decided. A withdrawn or cancelled booking shows when it was closed instead, worded as the
 * booking queue words it.
 *
 * Story 12.7 AC1 (the customer's hold, 12 Oct 2026): an approved booking's card shows when its
 * open hold expires - and, once Venue Staff have changed it, who did, when and why (decided 12 Oct
 * 2026). AC8: one whose hold expired stays on the list as Expired, with when it was approved and
 * when it expired.
 *
 * Story 4.4/4.5: also renders Approve and Reject actions for the assigned Event Coordinator
 * while the request awaits a decision. Approving moves it to PLANNING; rejecting requires a
 * reason and moves it to REJECTED. Both are offered from the same set of statuses.
 *
 * Story 15.1: the Equipment requirements section is where the assigned coordinator records the
 * event's equipment and submits it to Technical Support (`EquipmentRequestsSection`).
 *
 * Story 18.3: for the organiser and assigned coordinator of an event past draft that takes or holds
 * registrations, the Registration card shows only the count, with a link to the registrations
 * report for who registered.
 */
export function EventDetailPage() {
  const { eventId = '' } = useParams()
  const location = useLocation()
  const { user, can } = useAuth()
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Story 21.2: the safety review, loaded here so the sections it flags can say so (AC4).
  const loadSafety = useCallback(() => getEventSafety(eventId), [eventId])
  const { data: safety, error: safetyError, setData: setSafety } = useLoaded(loadSafety)
  // The pick-lists that name codes, read once for the change requests and the change history.
  const { data: references, error: referencesError } = useLoaded(fetchEventReferenceData)
  /** Story 7.4: bumped by every `reloadEvent`, so the change history is read again even when the
   *  reload leaves `updated_at` as it was (an approved equipment change writes no event row). */
  const [reloadCount, setReloadCount] = useState(0)
  const [hasImageFailed, setHasImageFailed] = useState(false)
  const [clarifications, setClarifications] = useState<Clarification[] | null>(null)
  const [clarificationsError, setClarificationsError] = useState<string | null>(null)
  const [bookings, setBookings] = useState<BookingOutcome[] | null>(null)
  /** Story 19.1 AC12: when change requests close - or why that couldn't be read - with the event
   *  it was read for, so another event's answer is never shown on this one. */
  const [requestWindow, setRequestWindow] = useState<{
    eventId: string
    window: ChangeRequestWindow | null
    error: string | null
  } | null>(null)
  const [bookingError, setBookingError] = useState<string | null>(null)
  const canReadBooking = can(PERMISSIONS.BOOKINGS_READ)
  /** Fix f7.1.2: the organiser reads their own event's bookings through `bookings:read_own`. */
  const canReadOwnBookings =
    event !== null &&
    user !== null &&
    event.organiser_id === user.id &&
    can(PERMISSIONS.BOOKINGS_READ_OWN)
  const [isConfirmingApprove, setIsConfirmingApprove] = useState(false)
  const [isApproving, setIsApproving] = useState(false)
  const [approveError, setApproveError] = useState<string | null>(null)
  const [isConfirmingReject, setIsConfirmingReject] = useState(false)
  const [isRejecting, setIsRejecting] = useState(false)
  const [rejectError, setRejectError] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [isConfirmingCancel, setIsConfirmingCancel] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const [cancelReason, setCancelReason] = useState('')
  const [clarificationMessage, setClarificationMessage] = useState('')
  const [isRequestingClarification, setIsRequestingClarification] = useState(false)
  const [clarificationRequestError, setClarificationRequestError] = useState<string | null>(null)
  const [responseMessage, setResponseMessage] = useState('')
  const [isResponding, setIsResponding] = useState(false)
  const [responseError, setResponseError] = useState<string | null>(null)
  const [pendingWithdraw, setPendingWithdraw] = useState<BookingOutcome | null>(null)
  const [isWithdrawing, setIsWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<string | null>(null)
  const [isConfirmingReassign, setIsConfirmingReassign] = useState(false)
  const [registrations, setRegistrations] = useState<EventRegistrationList | null>(null)
  const [registrationsError, setRegistrationsError] = useState<string | null>(null)
  /** Story 18.3 AC5: only the organiser and the assigned coordinator of an event past draft see
   *  who registered - the backend's `_registration_list_viewable_by`. */
  const canSeeRegistrations =
    event !== null &&
    event.status !== 'DRAFT' &&
    user !== null &&
    (event.organiser_id === user.id || event.assigned_coordinator_id === user.id)
  /** Story 18.3 AC1: the count is shown for an event taking registrations, or still holding some
   *  after Registration required was turned off (9.4 then 7.2). */
  const showsRegistrations =
    canSeeRegistrations &&
    (event.registration_required || (registrations !== null && registrations.total > 0))

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
    const isRelatedParty =
      user !== null && (event.organiser_id === user.id || event.assigned_coordinator_id === user.id)
    if (!isRelatedParty) return undefined
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

  /** Story 19.1 AC12: when change requests close, read for the organiser of a Planning or
   *  Confirmed event, and again whenever the event is - its bookings, and so its set-up time, may
   *  have changed. */
  useEffect(() => {
    if (event === null || user === null) return undefined
    const mayRequestChanges =
      can(PERMISSIONS.EVENT_CHANGE_REQUESTS_CREATE) &&
      event.organiser_id === user.id &&
      CHANGE_REQUESTABLE_STATUSES.includes(event.status)
    if (!mayRequestChanges) return undefined
    let cancelled = false
    fetchChangeRequestWindow(eventId)
      .then((window) => {
        if (!cancelled) setRequestWindow({ eventId, window, error: null })
      })
      .catch((err: unknown) => {
        if (!cancelled) setRequestWindow({ eventId, window: null, error: formatApiError(err) })
      })
    return () => {
      cancelled = true
    }
  }, [eventId, event, user, can])

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

  /** Story 18.3 AC1: the count, for the Registration card. */
  useEffect(() => {
    if (!canSeeRegistrations) return undefined
    let cancelled = false
    // One row is enough: the counts come with every page.
    listEventRegistrations(eventId, 0, 1)
      .then((data) => {
        if (!cancelled) setRegistrations(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setRegistrationsError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [eventId, canSeeRegistrations])

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

  /** Story 15.1: after an equipment change, show every item's new status. Story 21.2: with the
   *  safety review's blockers as they now stand. A failed reload keeps the page as it was rather
   *  than replacing it with an error. */
  async function reloadEvent(): Promise<void> {
    setReloadCount((count) => count + 1)
    await Promise.all([
      getEvent(eventId).then(setEvent, () => {}),
      getEventSafety(eventId).then(setSafety, () => {}),
    ])
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

  function askToCancel() {
    setCancelError(null)
    setCancelReason('')
    setIsConfirmingCancel(true)
  }

  /** Story 6.2 AC7: closing the dialog leaves the event as it was. */
  function keepEvent() {
    setIsConfirmingCancel(false)
  }

  async function confirmCancel() {
    if (!event) return
    if (!cancelReason.trim()) {
      setCancelError(ERROR_REGISTRY.EVENT_CANCELLATION_REASON_REQUIRED.message)
      return
    }
    setIsCancelling(true)
    setCancelError(null)
    try {
      const updated = await cancelEvent(event.id, cancelReason, event.name)
      setEvent(updated)
      setIsConfirmingCancel(false)
    } catch (err) {
      setCancelError(formatApiError(err))
    } finally {
      setIsCancelling(false)
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

  async function confirmRespondToClarification() {
    if (!event) return
    if (!responseMessage.trim()) {
      setResponseError(ERROR_REGISTRY.EVENT_CLARIFICATION_MESSAGE_REQUIRED.message)
      return
    }
    setIsResponding(true)
    setResponseError(null)
    try {
      const entry = await respondToClarification(event.id, responseMessage, event.name)
      setClarifications((current) => (current ?? []).concat(entry))
      setResponseMessage('')
    } catch (err) {
      setResponseError(formatApiError(err))
      // A 409 means the request moved on (story 4.3 AC11): reload it so the form goes away with
      // the state it belonged to. Ignore a failed reload - it must not lose the message.
      getEvent(event.id).then(setEvent, () => {})
    } finally {
      setIsResponding(false)
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
          current.map((booking) => {
            if (booking.id === updated.id) {
              return {
                ...booking,
                status: updated.status,
                decided_at: updated.decided_at,
                decision_reason: updated.decision_reason,
                // A closed booking holds nothing, so nothing marks it any more (9.4 AC3).
                venue_unavailable_marked_at: null,
              }
            }
            // Story 12.6 AC5: withdrawing a replacement ends the original's "Replacement
            // requested", which brings its Find a replacement venue back.
            return booking.id === pendingWithdraw.replaces_booking_id
              ? { ...booking, pending_replacement_venue_name: null }
              : booking
          }),
      )
      setPendingWithdraw(null)
      // Story 12.6 AC12: a withdrawn replacement, or a withdrawn marked booking, may have been what
      // stopped the safety review, so its blockers are read again.
      getEventSafety(eventId).then(setSafety, () => {})
    } catch (err) {
      setWithdrawError(formatApiError(err))
    } finally {
      setIsWithdrawing(false)
    }
  }

  function askToReassign() {
    setIsConfirmingReassign(true)
  }

  function cancelReassign() {
    setIsConfirmingReassign(false)
  }

  /** Story 5.6 AC1: the page shows the new coordinator straight away, read again as the page's
   *  other changes are (`reloadEvent`). */
  function handleReassigned() {
    setIsConfirmingReassign(false)
    void reloadEvent()
  }

  const backState = location.state as EventCardBackState | null
  const backTo = backState?.from ?? HOME_PATH
  const backLabel = backState?.fromLabel ?? 'Home'
  const canSeeInternalNotes = can(PERMISSIONS.EVENTS_REVIEW)
  const isAssignedCoordinator = event.assigned_coordinator_id === user?.id
  /** Story 7.2 AC1/AC3/AC8: the assigned coordinator edits the event until it is closed - its
   *  internal notes always, the organiser's details only until it is confirmed. */
  const canEditEvent =
    can(PERMISSIONS.EVENTS_EDIT_ROUTINE) &&
    isAssignedCoordinator &&
    !TERMINAL_STATUSES.includes(event.status)
  /** Story 7.2 AC12: the details are locked, which the assigned coordinator is told. */
  const isDetailsLockHintShown =
    can(PERMISSIONS.EVENTS_EDIT_ROUTINE) &&
    isAssignedCoordinator &&
    DETAILS_LOCKED_STATUSES.includes(event.status)
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
   *  earlier round (a follow-up has to work from CLARIFICATION_REQUESTED too, since nothing -
   *  not even story 4.3's response - moves the event back to Under Review) - mirroring the
   *  backend's own `_AWAITING_DECISION_STATUSES` gate on `request_clarification`. */
  const canRequestClarification =
    can(PERMISSIONS.EVENTS_REVIEW) &&
    isAssignedCoordinator &&
    AWAITING_DECISION_STATUSES.includes(event.status)
  /** Story 4.3 AC1/AC10: only the organiser who owns the request may respond, and only while it
   *  awaits a response - mirroring the backend's `respond_to_clarification`. */
  const canRespondToClarification =
    user !== null && event.organiser_id === user.id && event.status === 'CLARIFICATION_REQUESTED'
  /** Story 5.6 AC1/AC5: the Lead reassigns an event that has a coordinator and is still active
   *  (not a draft, nor completed, cancelled or rejected) - mirroring the backend's
   *  `ASSIGNABLE_STATUSES`. Coordinators no longer reassign their own events (Q16, replacing 5.2
   *  AC1/AC6); an event with none is assigned from 5.4's queue instead. */
  const canReassign =
    can(PERMISSIONS.EVENTS_ASSIGN) &&
    event.assigned_coordinator_id !== null &&
    ACTIVE_EVENT_STATUSES.includes(event.status)

  /** Story 15.1 AC9: only the assigned coordinator, holding equipment:request, may change the
   *  event's equipment, and only while it is Under Review, Clarification Requested or Planning -
   *  mirroring the backend's own checks. Everyone else sees the list alone. */
  // Story 21.2 AC4: the sections the latest review says must change.
  const flagged = flaggedArrangements(safety)
  const isVenueFlagged = flagged.includes('VENUE_BOOKINGS')
  const canChangeEquipment =
    can(PERMISSIONS.EQUIPMENT_REQUEST) &&
    isAssignedCoordinator &&
    EQUIPMENT_OPEN_STATUSES.includes(event.status)
  /** f12.1.1 (story 12.1 AC15): Find a venue, only for whoever may request one for the event -
   *  its assigned coordinator, while it can take a booking. Story 12.5: once its bookings are
   *  known, so it opens on a requirement that needs a venue. */
  const canFindVenue =
    canRequestVenueFor(event, user, can) &&
    (!canReadBooking || bookings !== null || bookingError !== null)
  /** Story 12.5 AC5: every venue requirement has a pending or approved request. Never for an
   *  event with none (AC7), and back to the normal look once one needs a venue again (AC8). */
  const isEveryRequirementCovered =
    bookings !== null &&
    event.venue_requirements.length > 0 &&
    firstRequirementNeedingVenue(event, bookings) === null
  /** Story 12.6 AC4: while a booking is marked "Venue unavailable" the event is not all booked, and
   *  no venue is left to find for a requirement that needs none: the way on is the marked booking's
   *  own Find a replacement venue (or Find another venue), so the header offers neither. */
  const hasMarkedBooking = bookings !== null && bookings.some(isMarked)
  const isHeaderFindHidden = isEveryRequirementCovered && hasMarkedBooking
  /** Fix f2.7.4 (story 2.7 AC17, AC19): "No venue requirements", saved before the fix, still
   *  stands once a request is past its decision - an event approved with it keeps the paths for
   *  none (AC19). Before then it no longer does: such a request cannot be submitted or approved
   *  until it has a venue requirement, so it shows as nothing recorded. */
  const isNoVenueAnswerKept =
    event.venue_none_required &&
    event.status !== 'DRAFT' &&
    !AWAITING_DECISION_STATUSES.includes(event.status)
  /** Story 4.6 AC2, story 7.4 AC5: only the event's related parties - its organiser and its
   *  assigned coordinator - may see the clarification history and the change history, mirroring
   *  the backend's `_is_related_party`. */
  const isRelatedParty =
    user !== null && (event.organiser_id === user.id || event.assigned_coordinator_id === user.id)
  const isOrganiser = user !== null && event.organiser_id === user.id
  /** Story 19.1 AC1/AC5/AC7/AC11/AC12: only the owning organiser, holding
   *  event_change_requests:create, asks for a change, and only while the event is in Planning or
   *  Confirmed - never before approval, while awaiting the safety check, or once completed,
   *  cancelled or rejected - mirroring the backend's checks. */
  const mayRequestChanges =
    can(PERMISSIONS.EVENT_CHANGE_REQUESTS_CREATE) &&
    isOrganiser &&
    CHANGE_REQUESTABLE_STATUSES.includes(event.status)
  /** AC12: and only until 24 hours before its set-up time, as the server says. */
  const readRequestWindow =
    mayRequestChanges && requestWindow?.eventId === eventId ? requestWindow : null
  const shownRequestWindow = readRequestWindow?.window ?? null
  const canRequestChanges = shownRequestWindow?.is_open === true
  /** Story 19.1 AC1: the organiser and the assigned coordinator read the change requests of an
   *  approved event, mirroring the backend's `list_change_requests`. */
  const canViewChangeRequests =
    (isOrganiser || isAssignedCoordinator) &&
    CHANGE_REQUESTS_VISIBLE_STATUSES.includes(event.status)
  /** Story 19.2 AC6/AC7: the assigned coordinator decides the pending change requests while the
   *  event is still going ahead, mirroring the backend's assigned-coordinator and status checks. */
  const canDecideChangeRequests =
    can(PERMISSIONS.EVENT_CHANGE_REQUESTS_DECIDE) &&
    isAssignedCoordinator &&
    CHANGE_DECIDABLE_STATUSES.includes(event.status)
  /** Story 19.1 AC2: the owning organiser updates the point of contact directly while the event
   *  is Planning or Confirmed, mirroring the backend's `update_point_of_contact`. */
  const canUpdatePointOfContact =
    can(PERMISSIONS.EVENTS_CREATE) &&
    isOrganiser &&
    CONTACT_EDITABLE_STATUSES.includes(event.status)
  /** Story 6.2 AC1/AC6/AC11: only the owning organiser cancels, and only while the event is
   *  still going ahead, mirroring the backend's permission, owner and status checks. */
  const canCancelEvent =
    can(PERMISSIONS.EVENTS_CANCEL) && isOrganiser && CANCELLABLE_STATUSES.includes(event.status)

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
      {(canEditEvent || canApprove || canReject || canReassign || canCancelEvent) && (
        <div className="page-header actions-only">
          {/* Story 7.2: editing sits apart, on the left; the decisions stay on the right. */}
          {canEditEvent && (
            <Link
              to={eventCoordinatorEditPath(event.id)}
              className="button button-with-icon page-header-lead"
            >
              <Icon name="pencil" size={20} /> Edit event
            </Link>
          )}
          <div className="page-actions">
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
              <button type="button" className="secondary reassign-action" onClick={askToReassign}>
                Reassign
              </button>
            )}
            {canCancelEvent && (
              <button type="button" className="danger" onClick={askToCancel}>
                Cancel event
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

        {/* Story 6.2 AC5/AC9: who cancelled the event, when and why, kept as its record. An event
            cancelled before these were recorded shows its status alone. */}
        {event.cancelled_at !== null && (
          <section className="card stack" aria-labelledby="event-cancellation-heading">
            <p className="eyebrow" id="event-cancellation-heading">
              Cancellation
            </p>
            <div className="fact-grid">
              <div className="subtle-block">
                <p className="fact-label">Cancelled by</p>
                <p className="fact-value">{event.cancelled_by_name ?? NOT_RECORDED}</p>
              </div>
              <div className="subtle-block">
                <p className="fact-label">Cancelled on</p>
                <p className="fact-value">{formatDateTime(event.cancelled_at)}</p>
              </div>
            </div>
            <div className="subtle-block">
              <p className="fact-label">Reason</p>
              <p>{event.cancellation_reason}</p>
            </div>
          </section>
        )}

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
          {isDetailsLockHintShown && <p className="form-hint">{DETAILS_LOCKED_HINT}</p>}
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
          {canUpdatePointOfContact && <PointOfContactEditor event={event} onSaved={setEvent} />}
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
            {/* Story 18.3 AC1: the count here; who registered is on the registrations report. */}
            {showsRegistrations && registrations !== null && (
              <RegistrationCount
                activeCount={registrations.active_count}
                capacity={registrations.capacity}
                isFull={registrations.is_full}
              />
            )}
          </div>
          {canSeeRegistrations && event.registration_required && registrationsError && (
            <p role="alert" className="error">
              {registrationsError}
            </p>
          )}
          {showsRegistrations && (
            <div className="cluster">
              <Link to={registrationsReportPath(event.id)} className="button secondary button-sm">
                View registrations
              </Link>
            </div>
          )}
        </section>

        <div className="layout-half">
          <section className="card stack" aria-labelledby="venue-requirements-heading">
            <div className="card-heading">
              <h2 id="venue-requirements-heading">Venue requirements</h2>
              {canFindVenue && !isHeaderFindHidden && (
                <Link
                  to={findVenuePath(event, bookings ?? [])}
                  className={
                    isEveryRequirementCovered ? 'button button-sm button-muted' : 'button button-sm'
                  }
                >
                  {isEveryRequirementCovered ? 'All required venues booked' : 'Find a venue'}
                </Link>
              )}
            </div>
            {isNoVenueAnswerKept && <p className="muted">No venue is required for this event.</p>}
            {!isNoVenueAnswerKept && event.venue_requirements.length === 0 && (
              <p className="muted">{NOT_RECORDED}</p>
            )}
            {event.venue_requirements.length > 0 && (
              <ul className="venue-requirement-list">
                {event.venue_requirements.map((requirement, index) => (
                  <li key={requirement.id} className="stack">
                    <div>
                      <p>
                        <strong>{requirement.name ?? unnamedRequirementLabel(index + 1)}</strong>
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
          <section
            className={`card stack${isVenueFlagged ? ' card-flagged' : ''}`}
            aria-labelledby="venue-booking-heading"
          >
            <h2 id="venue-booking-heading" className="cluster">
              <Icon name="building" size={20} />
              Venue booking
            </h2>
            {isVenueFlagged && <p className="flag-note">{FLAGGED_BY_SAFETY_REVIEW}</p>}

            {bookings.map((booking) => {
              const bookingOutcome = BOOKING_OUTCOME[booking.status]
              const outcomeLabels = bookingOutcomeLabels(booking)
              const openHold = openHoldExpiry(booking)
              const forRequirement = bookedRequirementName(event, booking)
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
                      {/* Story 12.5 AC4/AC5: the requirement the venue is for. */}
                      <p className="booking-outcome-purpose">
                        {forRequirement === null ? 'Additional venue' : `For ${forRequirement}`}
                      </p>
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
                      <p>{openHold ? OPEN_HOLD_MESSAGE : bookingMessage(event, booking)}</p>
                      {/* Story 12.6 AC2-AC4: which booking this replaces, which replaced it - only
                          once its replacement was approved - or which venue is asked for. */}
                      {booking.replaces_venue_name !== null && (
                        <p>
                          <strong>{replacesLine(booking.replaces_venue_name)}</strong>
                        </p>
                      )}
                      {booking.replaced_by_venue_name !== null && (
                        <p>
                          <strong>{replacedByLine(booking.replaced_by_venue_name)}</strong>
                        </p>
                      )}
                      {booking.pending_replacement_venue_name !== null && (
                        <p>
                          <strong>
                            {replacementRequestedLine(booking.pending_replacement_venue_name)}
                          </strong>
                        </p>
                      )}
                      {/* Story 9.4 AC3: its venue was marked unavailable for part of this booking;
                          the booking stays here for reference and the event needs another venue. */}
                      {booking.venue_unavailable_marked_at !== null && (
                        <p>
                          <Chip tone="warning" label={VENUE_UNAVAILABLE_LABEL} />
                          <br />
                          <span className="small muted">
                            Venue Staff marked this venue unavailable for part of the booked period.
                            The booking is kept for reference.
                          </span>
                        </p>
                      )}
                      {/* Story 12.7 AC1: when an approved booking's open hold expires. */}
                      {openHold && (
                        <p>
                          <span className="fact-label">{HOLD_EXPIRES_LABEL}</span>
                          <br />
                          {formatDateTime(openHold)}
                        </p>
                      )}
                      {/* Decided 12 Oct 2026: the latest change to that expiry - who, when, why. */}
                      {openHold &&
                        booking.hold_expiry_changed_by !== null &&
                        booking.hold_expiry_changed_at !== null && (
                          <p>
                            <span className="small muted">
                              Changed by {booking.hold_expiry_changed_by.full_name} on{' '}
                              {formatDateTime(booking.hold_expiry_changed_at)}
                            </span>
                            <br />
                            <span className="fact-label">Reason</span>
                            <br />
                            {booking.hold_expiry_change_reason}
                          </p>
                        )}
                      {booking.decided_at !== null && (
                        <p>
                          <span className="fact-label">{outcomeLabels.when}</span>
                          <br />
                          {formatDateTime(closedAt(booking) ?? booking.decided_at)}
                        </p>
                      )}
                      {/* Story 6.2 AC16: when the booking was cancelled. */}
                      {booking.cancelled_at !== null && (
                        <p>
                          <span className="fact-label">{CANCELLED_AT_LABEL}</span>
                          <br />
                          {formatDateTime(booking.cancelled_at)}
                        </p>
                      )}
                      {/* Story 12.7 AC8: when an expired booking's hold lapsed. */}
                      {booking.status === EXPIRED_BOOKING_STATUS && booking.hold_expires_at && (
                        <p>
                          <span className="fact-label">{HOLD_EXPIRED_LABEL}</span>
                          <br />
                          {formatDateTime(booking.hold_expires_at)}
                        </p>
                      )}
                      {/* Story 12.6 AC3: an original released by its replacement is told "Replaced by
                          <venue>" above, which is also its reason, so it is not said twice. */}
                      {booking.decision_reason !== null &&
                        booking.replaced_by_venue_name === null && (
                          <p>
                            <span className="fact-label">{outcomeLabels.why}</span>
                            <br />
                            {booking.decision_reason}
                          </p>
                        )}
                      {/* Story 11.1 AC6: why a venue that did not suit was requested. */}
                      {booking.suitability_override_reason !== null && (
                        <p>
                          <span className="fact-label">Justification</span>
                          <br />
                          {booking.suitability_override_reason}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Story 12.2 AC1/AC6: only the event's own assigned coordinator may withdraw,
                   *  and only while the request is still pending - mirrors the backend's own
                   *  relationship and status checks. */}
                  {booking.status === PENDING_BOOKING_STATUS && isAssignedCoordinator && (
                    <div className="cluster">
                      {/* Story 12.5 AC8: named for its venue and requirement, since an event
                       *  can have several pending at once. */}
                      <button
                        type="button"
                        className="secondary button-sm"
                        aria-label={
                          forRequirement === null
                            ? `Withdraw ${booking.venue_name}`
                            : `Withdraw ${booking.venue_name} for ${forRequirement}`
                        }
                        onClick={() => askToWithdraw(booking)}
                      >
                        Withdraw
                      </button>
                    </div>
                  )}
                  {/* Story 12.6 AC1/AC9: a marked booking offers the way to another venue, to the
                   *  event's assigned coordinator while it can take a booking (AC8): a replacement
                   *  for an approved one, the catalogue's Switch for a pending one. */}
                  {offersWayToAnotherVenue(booking) && canFindVenue && isAssignedCoordinator && (
                    <div className="cluster">
                      <Link
                        to={venueSearchPath(replacementSearchFor(event, booking))}
                        className="button button-sm"
                      >
                        {isReplaceable(booking) ? FIND_REPLACEMENT_LABEL : FIND_ANOTHER_LABEL}
                      </Link>
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

        {canReadOwnBookings && <OrganiserBookingsSection eventId={event.id} />}

        <EquipmentRequestsSection
          eventId={event.id}
          equipment={event.equipment}
          canChange={canChangeEquipment}
          isFlagged={flagged.includes('EQUIPMENT')}
          onChanged={reloadEvent}
        />

        {SAFETY_REVIEW_STATUSES.includes(event.status) && (
          <SafetyReviewSection
            eventId={event.id}
            eventName={event.name}
            safety={safety}
            loadError={safetyError}
            onChanged={reloadEvent}
          />
        )}

        {canViewChangeRequests && (
          <ChangeRequestsSection
            event={event}
            canRaise={canRequestChanges}
            requestWindow={shownRequestWindow}
            requestWindowError={readRequestWindow?.error ?? null}
            canWithdraw={isOrganiser}
            canDecide={canDecideChangeRequests}
            onDecided={reloadEvent}
            references={references}
            referencesError={referencesError}
          />
        )}

        {isRelatedParty && (
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

        {/* Story 7.4 AC5: the change history, for the same two people as the clarifications. */}
        {isRelatedParty && (
          <ChangeHistorySection
            eventId={event.id}
            version={`${event.updated_at}#${reloadCount}`}
            references={references}
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

        {canRespondToClarification && (
          <section className="card stack" aria-labelledby="respond-clarification-heading">
            <p className="eyebrow" id="respond-clarification-heading">
              Respond to the coordinator
            </p>
            <label>
              Message
              <textarea
                rows={3}
                maxLength={CLARIFICATION_MESSAGE_MAX_LENGTH}
                placeholder="Answer the coordinator's question."
                value={responseMessage}
                onChange={(e) => setResponseMessage(e.target.value)}
              />
            </label>
            {responseError && (
              <p role="alert" className="error">
                {responseError}
              </p>
            )}
            <div className="page-actions">
              <button
                type="button"
                className="secondary"
                disabled={isResponding}
                onClick={confirmRespondToClarification}
              >
                {isResponding ? 'Sending…' : 'Send response'}
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
      {isConfirmingCancel && (
        <ConfirmDialog
          title="Cancel this event?"
          confirmLabel="Cancel event"
          cancelLabel="Keep event"
          isBusy={isCancelling}
          error={cancelError}
          errorId="cancel-event-error"
          onConfirm={confirmCancel}
          onCancel={keepEvent}
        >
          <p>
            {event.name} will be cancelled. Its venue bookings, equipment and attendee registrations
            are released, and its coordinator and attendees are told. This cannot be undone.
          </p>
          <label>
            Reason for cancelling
            <textarea
              rows={3}
              placeholder="Shown to the coordinator and attendees."
              value={cancelReason}
              aria-describedby={cancelError ? 'cancel-event-error' : undefined}
              onChange={(e) => setCancelReason(e.target.value)}
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
      {isConfirmingReassign && event.assigned_coordinator_id !== null && (
        <ReassignDialog
          eventId={event.id}
          eventName={event.name}
          currentCoordinatorId={event.assigned_coordinator_id}
          onReassigned={handleReassigned}
          onCancel={cancelReassign}
        />
      )}
    </div>
  )
}
