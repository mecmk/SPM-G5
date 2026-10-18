import { approvalReleasesLine, replacesLine } from '../shared/bookingStatus'

export interface ReplacementNoteProps {
  /** The venue of the booking this request replaces; null for a request that replaces nothing. */
  replacesVenueName: string | null
  /** The venue approving it will release - only while that booking still holds its venue. */
  approvalReleasesVenueName: string | null
  /** Whether that booking is still marked "Venue unavailable"; null for a request that replaces
   *  nothing. */
  originalIsMarked: boolean | null
}

/**
 * Story 12.6 AC3/AC6: what Venue Staff read before approving a replacement - which booking it
 * replaces, and that approving it releases that booking's venue, in the queue card and on the
 * request's page. Said even when the unavailability has ended since (the original is then no
 * longer marked), since the approval still releases it. Nothing for any other request.
 */
export function ReplacementNote({
  replacesVenueName,
  approvalReleasesVenueName,
  originalIsMarked,
}: ReplacementNoteProps) {
  if (replacesVenueName === null) return null
  return (
    <div className="stack">
      <p>
        <strong>{replacesLine(replacesVenueName)}</strong>
      </p>
      {approvalReleasesVenueName !== null && (
        <p>
          {approvalReleasesLine(approvalReleasesVenueName)}
          {originalIsMarked === false && ' (its venue is no longer marked unavailable)'}.
        </p>
      )}
    </div>
  )
}
