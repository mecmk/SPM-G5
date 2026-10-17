import type { SafetyFinding } from '../api/safety'
import { ARRANGEMENT_LABELS } from '../shared/safetyReview'

/**
 * Story 21.2 AC4: a review's findings in order - each factor, the arrangement it says must change
 * if any, and exactly what must change. On the event page and the officer's previous reviews.
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
        </li>
      ))}
    </ol>
  )
}
