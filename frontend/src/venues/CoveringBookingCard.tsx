import { useId } from 'react'
import { Link } from 'react-router'
import type { BookingOutcome } from '../api/bookings'
import { StatusBadge } from '../components/StatusBadge'
import { venuePath } from '../routes'
import { formatSchedule } from '../shared/format'
import { isBooked } from '../shared/venueRequest'

export interface CoveringBookingCardProps {
  /** The pending or approved request of the selected venue requirement. */
  booking: BookingOutcome
  /** That requirement's name, as the banner shows it. */
  requirementName: string
  /** The catalogue's own query, kept on the venue's link as the result cards keep it (f12.1.1). */
  search: string
}

/**
 * Story 12.5 (decided 10 Oct 2026): with a venue requirement that already has a venue selected in
 * the banner, the catalogue shows that venue first - its location, booked period and the status
 * of its request - above the other venues that fit the requirement, none of which offers a
 * request (AC11: a requirement takes one pending or approved request at a time).
 */
export function CoveringBookingCard({
  booking,
  requirementName,
  search,
}: CoveringBookingCardProps) {
  const headingId = useId()
  return (
    <section className="card stack" aria-labelledby={headingId}>
      <h2 id={headingId}>
        {isBooked(booking) ? 'Booked' : 'Requested'} for {requirementName}
      </h2>
      <div className="cluster">
        <Link to={`${venuePath(booking.venue_id)}${search}`} className="covering-venue-name">
          {booking.venue_name}
        </Link>
        <StatusBadge status={booking.status} />
      </div>
      <p className="small muted">
        {booking.venue_location} · {formatSchedule(booking.starts_at, booking.ends_at)}
      </p>
      {!isBooked(booking) && (
        <p className="small muted">
          To request a different venue for {requirementName}, withdraw this request on the
          event&apos;s page first.
        </p>
      )}
    </section>
  )
}
