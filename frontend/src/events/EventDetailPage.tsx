import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { formatApiError } from '../api/client'
import {
  getEvent,
  listClarifications,
  type Clarification,
  type EventDetail,
  type RequiredFacility,
} from '../api/events'
import { useAuth } from '../auth/authContext'
import { PERMISSIONS } from '../auth/permissions'
import { Chip } from '../components/Chip'
import { ClarificationHistory, type ClarificationEntry } from '../components/ClarificationHistory'
import type { EventCardBackState } from '../components/EventCard'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { Icon } from '../components/Icon'
import { TERMINAL_STATUSES } from './eventStatus'
import { LoadingState } from '../layout/LoadingState'
import { eventEditRoutinePath, HOME_PATH } from '../routes'
import { formatDate, formatSchedule, formatTime } from '../shared/format'

const NOT_RECORDED = 'Not recorded'
const NOT_YET_ASSIGNED = 'Not yet assigned'
const NOT_YET_SCHEDULED = 'Not yet scheduled'

/** One required facility, as its quantity and notes make it distinct. */
function describeFacility(facility: RequiredFacility): string {
  const quantity = facility.quantity === null ? '' : ` ×${facility.quantity}`
  const notes = facility.notes === null ? '' : ` (${facility.notes})`
  return `${facility.name}${quantity}${notes}`
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

  const backState = location.state as EventCardBackState | null
  const backTo = backState?.from ?? HOME_PATH
  const backLabel = backState?.fromLabel ?? 'Home'
  const canSeeInternalNotes = can(PERMISSIONS.EVENTS_REVIEW)
  const canEditRoutineInformation =
    can(PERMISSIONS.EVENTS_EDIT_ROUTINE) &&
    event.assigned_coordinator_id === user?.id &&
    !TERMINAL_STATUSES.includes(event.status)
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
      {canEditRoutineInformation && (
        <div className="page-header actions-only">
          <div className="page-actions">
            <Link to={eventEditRoutinePath(event.id)} className="button">
              Edit routine information
            </Link>
          </div>
        </div>
      )}

      <div className="venue-hero">
        {event.cover_image_url && !hasImageFailed ? (
          <img
            className="venue-hero-picture"
            src={event.cover_image_url}
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
    </div>
  )
}
