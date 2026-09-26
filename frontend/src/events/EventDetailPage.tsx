import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { listBookingsForEvent, type BookingOutcome, type BookingStatus } from '../api/bookings'
import { formatApiError, mediaUrl } from '../api/client'
import {
  approveEvent,
  getEvent,
  listClarifications,
  rejectEvent,
  type Clarification,
  type EventDetail,
  type RequiredFacility,
} from '../api/events'
import { useAuth } from '../auth/authContext'
import { PERMISSIONS } from '../auth/permissions'
import { Chip } from '../components/Chip'
import { ClarificationHistory, type ClarificationEntry } from '../components/ClarificationHistory'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type { EventCardBackState } from '../components/EventCard'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { Icon, type IconName } from '../components/Icon'
import { ERROR_REGISTRY } from '../errors/registry'
import { AWAITING_DECISION_STATUSES, TERMINAL_STATUSES } from './eventStatus'
import { LoadingState } from '../layout/LoadingState'
import { eventEditRoutinePath, HOME_PATH } from '../routes'
import { formatDate, formatSchedule, formatTime } from '../shared/format'

const NOT_RECORDED = 'Not recorded'
const NOT_YET_ASSIGNED = 'Not yet assigned'
const NOT_YET_SCHEDULED = 'Not yet scheduled'

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
 * while the request awaits a decision. Approving moves it straight to PLANNING; rejecting
 * requires a reason and moves it to REJECTED - both are offered from the same set of statuses
 * (bug b6.1.1's narrower reject rule has been reversed).
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
      {(canEditRoutineInformation || canApprove || canReject) && (
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
          <div className="stat">
            <Icon name="person" />
            <div className="stat-body">
              <p className="stat-value">{event.assigned_coordinator_name ?? NOT_YET_ASSIGNED}</p>
              <p className="eyebrow">Assigned coordinator</p>
            </div>
          </div>
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
          <div>
            <p className="eyebrow">Organiser</p>
            <p>{event.organiser_name}</p>
          </div>
        </section>

        <div className="layout-half">
          <section className="card stack" aria-labelledby="venue-requirements-heading">
            <h2 id="venue-requirements-heading">Venue requirements</h2>
            {event.venue_none_required ? (
              <p className="muted">No venue is required for this event.</p>
            ) : (
              <>
                <div>
                  <p className="eyebrow">Room layout</p>
                  <p>{event.required_layout_name ?? NOT_RECORDED}</p>
                </div>
                <div>
                  <p className="eyebrow">Required facilities</p>
                  {event.required_facilities.length === 0 ? (
                    <p className="muted">{NOT_RECORDED}</p>
                  ) : (
                    <div className="cluster">
                      {event.required_facilities.map((facility) => (
                        <Chip key={facility.code} tone="info" label={describeFacility(facility)} />
                      ))}
                    </div>
                  )}
                </div>
                {event.venue_requirement_notes && (
                  <div>
                    <p className="eyebrow">Other requirements</p>
                    <p>{event.venue_requirement_notes}</p>
                  </div>
                )}
              </>
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
                </div>
              )
            })}
          </section>
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
    </div>
  )
}
