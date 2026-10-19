import { useEffect, useRef, type ReactNode } from 'react'
import { formatDate, inputToInstant } from '../shared/format'
import { Chip } from './Chip'
import type { DayClosure, DayItem } from './venueCalendarDays'

export interface VenueDayPanelProps {
  /** The id the day's button points at with `aria-controls`. */
  id: string
  /** `YYYY-MM-DD`, Singapore time. */
  date: string
  items: DayItem[]
  /** Whether opening (or switching to) a day brings the list into view. Off for a day open on
   *  arrival, which the user has not asked to see yet. */
  scrollIntoView?: boolean
  /** Story 9.4 AC6: what Venue Staff can do to a closure from its row - edit it, end it or remove
   *  it - given by the page that may offer them. Rows of bookings and holds never take any. */
  renderClosureActions?: (closure: DayClosure) => ReactNode
}

/**
 * Story 9.1 AC5: the list a pressed calendar day opens - every booking, hold and closure that
 * falls on it, in time order. Each row gives the time first, then the event's name, then a text
 * label ("Booked", "Held – pending", "Unavailable – Maintenance", "Ended – Maintenance") so the difference is never carried
 * by colour alone, then, when the venue is blocked for longer than the event runs, the whole
 * blocked stretch. AC7/AC8: rows are separate, so several events on one day, or two that meet at
 * 12:00, are each listed. AC9: a multi-day booking's row holds only the part on this day. Story
 * 12.7 AC1: an approved booking's row also says when its open hold expires.
 *
 * The list sits below the grid and legend, which on a phone is below the fold, so opening (or
 * switching to) a day scrolls it into view - only as far as needed. Focus is left on the day's
 * button, so pressing it again still closes the list.
 */
export function VenueDayPanel({
  id,
  date,
  items,
  scrollIntoView = true,
  renderClosureActions,
}: VenueDayPanelProps) {
  const headingId = `${id}-heading`
  const panelRef = useRef<HTMLElement>(null)
  useEffect(() => {
    if (scrollIntoView) panelRef.current?.scrollIntoView({ block: 'nearest' })
  }, [date, scrollIntoView])
  return (
    <section ref={panelRef} id={id} className="calendar-day-panel" aria-labelledby={headingId}>
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
            {(item.turnaround !== null || item.holdExpiry !== null) && (
              <span className="calendar-day-note small muted">
                {item.turnaround}
                {item.turnaround !== null && item.holdExpiry !== null && <br />}
                {item.holdExpiry}
              </span>
            )}
            {item.closure !== null && renderClosureActions !== undefined && (
              <span className="calendar-day-actions">{renderClosureActions(item.closure)}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
