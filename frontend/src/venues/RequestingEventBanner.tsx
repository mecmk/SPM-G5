import { Link } from 'react-router'
import type { EventDetail } from '../api/events'
import { eventPath } from '../routes'
import { formatSchedule } from '../shared/format'

/**
 * f12.1.1 (story 12.1 AC15): on the catalogue opened from an event's Find a venue, names the event
 * the venues are being found for, and leads back to it.
 */
export function RequestingEventBanner({ event }: { event: EventDetail }) {
  const facts = [
    event.starts_at && event.ends_at ? formatSchedule(event.starts_at, event.ends_at) : null,
    event.expected_attendance === null ? null : `${event.expected_attendance} attendees expected`,
  ].filter((fact) => fact !== null)

  return (
    <section className="card stack requesting-event" aria-labelledby="requesting-event-heading">
      <div className="card-heading">
        <h2 id="requesting-event-heading">Finding a venue for {event.name}</h2>
        <Link to={eventPath(event.id)} className="button secondary button-sm">
          Back to the event
        </Link>
      </div>
      {facts.length > 0 && <p className="small muted">{facts.join(' · ')}</p>}
    </section>
  )
}
