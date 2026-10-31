import type { SafetyFinding } from '../api/safety'
import { ARRANGEMENT_LABELS, releasedLine } from '../shared/safetyReview'

/**
 * Story 21.2 AC4: a review's findings in order - each factor, the arrangement it says must change
 * if any, and exactly what must change. On the event page and the officer's previous reviews.
 * Story 21.3 AC9: and the bookings that finding released.
 */
export function SafetyFindingsList({ findings }: { findings: SafetyFinding[] }) {
  if (findings.length === 0) return null
  return (
    <ol className="stack">
      {findings.map((finding, index) => (
        <li key={index}>
          <p className="fact-label">
            {finding.factor_name}
            {finding.arrangement && ` · ${ARRANGEMENT_LABELS[finding.arrangement]} must change`}
          </p>
          <p>{finding.required_change}</p>
          {finding.released_bookings.map((booking) => (
            <p key={booking.booking_id}>{releasedLine(booking)}</p>
          ))}
        </li>
      ))}
    </ol>
  )
}
