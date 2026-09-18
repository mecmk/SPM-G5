import { useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { formatApiError } from '../api/client'
import { getEvent, type EventDetail } from '../api/events'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { HOME_PATH } from '../routes'

function formatSchedule(startsAt: string | null, endsAt: string | null): string {
  if (!startsAt) return 'Not yet scheduled'
  const dateTime: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' }
  const start = new Date(startsAt).toLocaleString(undefined, dateTime)
  if (!endsAt) return start
  return `${start} – ${new Date(endsAt).toLocaleString(undefined, dateTime)}`
}

function textValue(text: string | null | undefined): string {
  return text && text.trim() ? text : 'Not recorded'
}

function formatAccessibility(event: EventDetail): string {
  if (event.accessibility_needs.length > 0) {
    return event.accessibility_needs.map((need) => need.name).join(', ')
  }
  return event.accessibility_none_required ? 'No accessibility needs recorded' : 'Not recorded'
}

/**
 * Story 7.1 - AC1: core details, venue and accessibility requirements, equipment requirements,
 * status and assigned coordinator for one event. AC2 (who may open this event) is enforced by
 * the backend, which answers with a plain 404 for an event that either does not exist or is not
 * the signed-in user's to see. AC3 is satisfied by construction: this page only ever renders
 * fields, it never edits them.
 */
export function EventDetailPage() {
  const { eventId } = useParams<{ eventId: string }>()
  const [event, setEvent] = useState<EventDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!eventId) return
    let cancelled = false
    getEvent(eventId)
      .then((data) => {
        if (!cancelled) setEvent(data)
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [eventId])

  return (
    <div className="page page-wide">
      <PageHeader
        title={event?.name ?? 'Event details'}
        backTo={HOME_PATH}
        backLabel="Back"
        action={event && <StatusBadge status={event.status} />}
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!event && !error && <LoadingState label="Loading event…" />}

      {event && (
        <div className="detail-grid">
          <div className="stack">
            <section className="card">
              <h2>Event</h2>
              <dl className="detail-list">
                <div>
                  <dt>Purpose</dt>
                  <dd>{textValue(event.purpose)}</dd>
                </div>
                <div>
                  <dt>Description</dt>
                  <dd>{textValue(event.description)}</dd>
                </div>
                <div>
                  <dt>Date and time</dt>
                  <dd>{formatSchedule(event.starts_at, event.ends_at)}</dd>
                </div>
                <div>
                  <dt>Expected attendance</dt>
                  <dd>{event.expected_attendance ?? 'Not recorded'}</dd>
                </div>
              </dl>
            </section>

            <section className="card">
              <h2>Requirements</h2>
              <dl className="detail-list">
                <div>
                  <dt>Preferred location</dt>
                  <dd>{textValue(event.preferred_location)}</dd>
                </div>
                <div>
                  <dt>Room layout</dt>
                  <dd>{textValue(event.required_layout_name)}</dd>
                </div>
                <div>
                  <dt>Facilities</dt>
                  <dd>
                    {event.required_facilities.length > 0
                      ? event.required_facilities.map((facility) => facility.name).join(', ')
                      : 'Not recorded'}
                  </dd>
                </div>
                <div>
                  <dt>Venue notes</dt>
                  <dd>{textValue(event.venue_requirement_notes)}</dd>
                </div>
                <div>
                  <dt>Accessibility</dt>
                  <dd>{formatAccessibility(event)}</dd>
                </div>
                <div>
                  <dt>Accessibility notes</dt>
                  <dd>{textValue(event.accessibility_notes)}</dd>
                </div>
              </dl>
            </section>
          </div>

          <aside className="stack">
            <section className="card">
              <h2>Coordinator</h2>
              <p>{event.assigned_coordinator_name ?? 'Not yet assigned'}</p>
            </section>

            <section className="card">
              <h2>Equipment</h2>
              {event.equipment.length === 0 ? (
                <p className="muted">No equipment requested.</p>
              ) : (
                <ul className="stack">
                  {event.equipment.map((item) => (
                    <li key={item.equipment_type_code}>
                      {item.quantity}× {item.equipment_type_name}
                      {item.technical_notes && <p className="muted">{item.technical_notes}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </aside>
        </div>
      )}
    </div>
  )
}
