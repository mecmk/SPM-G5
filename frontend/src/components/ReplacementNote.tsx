import { approvalReleasesLine, replacesLine } from '../shared/bookingStatus'

export interface ReplacementNoteProps {
  /** The venue of the booking this request replaces; null for a request that replaces nothing. */
  replacesVenueName: string | null
  /** The venue approving it will release - only while that booking still holds its venue. */
  approvalReleasesVenueName: string | null
}

/**
 * Story 12.6 AC3/AC6: what Venue Staff read before approving a replacement - which booking it
 * replaces, and that approving it releases that booking's venue, in the queue card and on the
 * request's page. Nothing for any other request, and nothing once the original has closed
 * (story 9.5 AC8): the backend then sends no replaced venue.
 */
export function ReplacementNote({
  replacesVenueName,
  approvalReleasesVenueName,
}: ReplacementNoteProps) {
  if (replacesVenueName === null) return null
  return (
    <div className="info stack">
      <p>
        <strong>{replacesLine(replacesVenueName)}</strong>
      </p>
      {approvalReleasesVenueName !== null && (
        <p>{approvalReleasesLine(approvalReleasesVenueName)}.</p>
      )}
    </div>
  )
}
