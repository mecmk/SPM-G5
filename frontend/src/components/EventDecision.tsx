import { formatDateTime } from '../shared/format'
import { StatusBadge } from './StatusBadge'

export interface EventDecisionProps {
  status: string
  decidedByName: string | null
  decidedAt: string | null
  decisionReason: string | null
}

/**
 * Story 4.6 AC1 - the event's current decision state and any decision reason. Shown on the
 * read-only request page once it has left DRAFT; `decidedAt === null` means no decision has
 * been made yet, which is distinct from an approval that carries no reason.
 */
export function EventDecision({
  status,
  decidedByName,
  decidedAt,
  decisionReason,
}: EventDecisionProps) {
  return (
    <section className="card stack" aria-labelledby="event-decision-heading">
      <p className="eyebrow" id="event-decision-heading">
        Decision
      </p>
      {decidedAt === null ? (
        <p className="muted">
          A decision has not been made yet.
          {status === 'CLARIFICATION_REQUESTED' &&
            ' The coordinator has asked for clarification - see the messages below.'}
        </p>
      ) : (
        <dl className="detail-list">
          <div>
            <dt>Outcome</dt>
            <dd>
              <StatusBadge status={status} />
            </dd>
          </div>
          <div>
            <dt>Decided by</dt>
            <dd>{decidedByName ?? 'Not recorded'}</dd>
          </div>
          <div>
            <dt>Decided on</dt>
            <dd>{formatDateTime(decidedAt)}</dd>
          </div>
          {decisionReason !== null && (
            <div>
              <dt>Reason</dt>
              <dd>{decisionReason}</dd>
            </div>
          )}
        </dl>
      )}
    </section>
  )
}
