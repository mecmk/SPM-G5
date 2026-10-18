import type { ChangeRequest } from '../api/changeRequests'
import type { EventReferenceData } from '../api/events'
import { Icon } from '../components/Icon'
import { describeChanges } from './changeRequestValues'

export interface ChangeRequestChangesProps {
  request: ChangeRequest
  /** For names in place of codes - layouts, facilities and equipment types. */
  references: EventReferenceData | null
}

/**
 * Story 19.1 AC1, story 19.2 AC1/AC2: what a change request would change - one row per
 * difference, the value now, an arrow, and the value asked for. The column names show once, on
 * the first row, and are read out on every row. Shared by the event page, the coordinator's queue
 * and the Approve dialog, so all three explain a request the same way.
 */
export function ChangeRequestChanges({ request, references }: ChangeRequestChangesProps) {
  const lines = describeChanges(
    request.field,
    request.current_value,
    request.proposed_value,
    references,
  )
  return (
    <div className="change-diff" role="group" aria-label="What changes">
      {lines.map((line, index) => {
        const labelClass = index === 0 ? 'change-diff-label' : 'visually-hidden'
        return (
          // Two rows can share a label (two unnamed rooms, or one removed and one added under the
          // same name), and the list is never reordered, so the index keeps each key apart.
          <div key={`${index}-${line.what}`} className="change-diff-row">
            <span className="change-diff-icon">
              <Icon name={line.icon} />
            </span>
            <span className="change-diff-what">{line.what}</span>
            <span className="change-diff-value">
              <span className={labelClass}>Current</span>
              <span>{line.now}</span>
            </span>
            <span className="change-diff-arrow" aria-hidden="true">
              <Icon name="arrow-right" size={16} />
            </span>
            <span className="change-diff-value change-diff-requested">
              <span className={labelClass}>Requested</span>
              <span>{line.requested}</span>
            </span>
          </div>
        )
      })}
    </div>
  )
}
