import type { VenueSuitability } from '../api/venues'
import { describeFailure, suitabilityLabel } from '../shared/suitability'
import { StatusBadge } from './StatusBadge'

export interface SuitabilityNoteProps {
  suitability: VenueSuitability
  /** How many venue requirements the event has: the one judged is named only when it has several. */
  requirementCount: number
}

/**
 * Story 11.1 AC1/AC5: whether a venue suits the event's venue requirement, and every criterion it
 * fails. The verdict is a word on the badge, so it never rests on colour alone.
 */
export function SuitabilityNote({ suitability, requirementCount }: SuitabilityNoteProps) {
  return (
    <div className="stack">
      <div className="cluster">
        <StatusBadge
          status={suitability.is_suitable ? 'success' : 'danger'}
          label={suitabilityLabel(suitability, requirementCount)}
        />
      </div>
      {suitability.failures.length > 0 && (
        <ul className="small" aria-label="Why it does not suit">
          {suitability.failures.map((failure) => (
            <li key={`${failure.criterion}-${failure.code ?? ''}`}>{describeFailure(failure)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
