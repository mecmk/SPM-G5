import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { mediaUrl } from '../api/client'
import type { VenueSummary } from '../api/venues'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'

export interface VenueCardProps {
  venue: VenueSummary
  /** The venue's record. The catalogue passes its own query along, so the record keeps the event
   *  a venue is being found for (f12.1.1). */
  recordPath: string
  /** Lines below the heading: story 8.1 AC3's "Opening hours not recorded" when a period is
   *  searched, and room for 11.1's suitability note. */
  notes?: ReactNode
  /** The foot of the card: Request this venue (f12.1.1), or Venue Staff's Edit and Delete
   *  (story 8.1 AC12). */
  actions?: ReactNode
}

/**
 * Story 8.1: one venue in the catalogue. AC1 name, location and capacity, and the name opens the
 * full record. A withdrawn venue is listed only when Venue Staff ask for it (AC12), and is badged
 * so it cannot pass for one in service (AC2: "excluded or clearly marked"). Story 8.3 AC6: the
 * venue's first picture fills the band at the top; without one, or if it fails to load, the
 * placeholder stays.
 */
export function VenueCard({ venue, recordPath, notes, actions }: VenueCardProps) {
  // The address that failed, not just that one did, so a new cover is tried rather than hidden.
  const [failedCoverUrl, setFailedCoverUrl] = useState<string | null>(null)
  const coverUrl = venue.cover_image_url

  function markCoverFailed() {
    setFailedCoverUrl(coverUrl)
  }

  return (
    <article className="item-card">
      <div className="item-card-picture" aria-hidden="true">
        {coverUrl !== null && coverUrl !== failedCoverUrl ? (
          <img
            className="item-card-image"
            src={mediaUrl(coverUrl) ?? undefined}
            alt=""
            onError={markCoverFailed}
          />
        ) : (
          <Icon name="building" size={28} />
        )}
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
        {notes}
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
