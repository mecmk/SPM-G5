import { Chip } from '../components/Chip'
import { formatDate, inputToInstant } from '../shared/format'
import type { DayItem } from './venueCalendarDays'

export interface VenueDayPanelProps {
  /** The id the day's button points at with `aria-controls`. */
  id: string
  /** `YYYY-MM-DD`, Singapore time. */
  date: string
  items: DayItem[]
}

/**
 * Story 9.1 AC5: the list a pressed calendar day opens - every booking, hold and closure that
 * falls on it, in time order. Each row gives the time first, then the event's name, then a text
 * label ("Booked", "Held – pending", "Closed – Maintenance") so the difference is never carried
 * by colour alone, then, when the venue is blocked for longer than the event runs, the whole
 * blocked stretch. AC7/AC8: rows are separate, so several events on one day, or two that meet at
 * 12:00, are each listed. AC9: a multi-day booking's row holds only the part on this day.
 */
export function VenueDayPanel({ id, date, items }: VenueDayPanelProps) {
  const headingId = `${id}-heading`
  return (
    <section id={id} className="calendar-day-panel" aria-labelledby={headingId}>
      <h3 id={headingId} className="calendar-day-panel-title">
        {formatDate(inputToInstant(`${date}T00:00`))}
      </h3>
      <ul className="calendar-day-list">
        {items.map((item) => (
          <li key={item.id} className="calendar-day-item">
            <span className="calendar-day-time">{item.timeRange}</span>
            <span className="calendar-day-name">{item.label}</span>
            <span className="calendar-day-kind">
              <Chip label={item.kindLabel} tone={item.tone} />
            </span>
            {item.turnaround !== null && (
              <span className="calendar-day-note small muted">{item.turnaround}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
