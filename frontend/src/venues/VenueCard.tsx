import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { VenueSummary } from '../api/venues'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'

export interface VenueCardProps {
  venue: VenueSummary
  /** The venue's record. The catalogue passes its own query along, so the record keeps the event
   *  a venue is being found for (f12.1.1). */
  recordPath: string
  /** The foot of the card: Request this venue (f12.1.1), or Venue Staff's Edit and Delete
   *  (story 8.1 AC13). */
  actions?: ReactNode
}

/**
 * Story 8.1: one venue in the catalogue. AC1 name, location and capacity, and the name opens the
 * full record. A withdrawn venue is listed only when Venue Staff ask for it (AC13), and is badged
 * so it cannot pass for one in service (AC1: "excluded or clearly marked").
 */
export function VenueCard({ venue, recordPath, actions }: VenueCardProps) {
  return (
    <article className="item-card">
      <div className="item-card-picture" aria-hidden="true">
        <Icon name="building" size={28} />
      </div>
      <div className="item-card-body">
        <div className="item-card-header">
          <div>
            <h3 className="item-card-title">
              <Link to={recordPath}>{venue.name}</Link>
            </h3>
            <p className="small muted">{venue.location}</p>
          </div>
          <div className="item-card-capacity">
            <div className="item-card-capacity-value">{venue.capacity}</div>
            <div className="item-card-capacity-label">capacity</div>
          </div>
        </div>
        {venue.status === 'WITHDRAWN' && (
          <div className="cluster">
            <StatusBadge status={venue.status} label="Withdrawn" />
          </div>
        )}
        {actions && <div className="item-card-footer">{actions}</div>}
      </div>
    </article>
  )
}
