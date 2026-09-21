import { useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { formatApiError } from '../api/client'
import { getEvent, type EventDetail, type RequiredFacility } from '../api/events'
import { Chip } from '../components/Chip'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { HOME_PATH } from '../routes'
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

function formatHeaderSubtitle(event: EventDetail): string {
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
 */
export function EventDetailPage() {
  const { eventId = '' } = useParams()
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

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

  return (
    <div className="page page-wide">
      <PageHeader
        title={event.name}
        subtitle={formatHeaderSubtitle(event)}
        backTo={HOME_PATH}
        backLabel="Home"
      />

      <div className="stat-grid">
        <div className="stat">
          <p className="eyebrow">Expected attendance</p>
          <p className="stat-value">{event.expected_attendance ?? NOT_RECORDED}</p>
        </div>
        <div className="stat">
          <p className="eyebrow">Event status</p>
          <StatusBadge status={event.status} />
        </div>
        <div className="stat">
          <p className="eyebrow">Assigned coordinator</p>
          <p className="stat-value">{event.assigned_coordinator_name ?? NOT_YET_ASSIGNED}</p>
        </div>
      </div>

      <section className="card stack" aria-labelledby="event-info-heading">
        <h2 id="event-info-heading">Event information</h2>
        <div>
          <p className="eyebrow">Purpose</p>
          <p>{event.purpose ?? NOT_RECORDED}</p>
        </div>
        <div>
          <p className="eyebrow">Description</p>
          <p>{event.description ?? NOT_RECORDED}</p>
        </div>
        <div className="row">
          <div>
            <p className="eyebrow">Date</p>
            <p>{event.starts_at ? formatDate(event.starts_at) : NOT_RECORDED}</p>
          </div>
          <div>
            <p className="eyebrow">Time</p>
            <p>
              {event.starts_at && event.ends_at
                ? `${formatTime(event.starts_at)}–${formatTime(event.ends_at)}`
                : NOT_RECORDED}
            </p>
          </div>
        </div>
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
    </div>
  )
}
