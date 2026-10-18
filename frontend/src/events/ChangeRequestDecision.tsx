import type { ChangeRequest } from '../api/changeRequests'
import { Icon } from '../components/Icon'
import { formatDateTime } from '../shared/format'
import { STATUS_LABELS } from './changeRequestValues'

/**
 * Story 19.2 AC2/AC3: who decided a change request and when, with a rejection's reason - on the
 * event page and in the coordinator's queue. Nothing shows while it waits or once withdrawn.
 */
export function ChangeRequestDecision({ request }: { request: ChangeRequest }) {
  if (request.decided_by_name === null || request.decided_at === null) return null
  const isRejected = request.status === 'REJECTED'
  return (
    <div className={isRejected ? 'change-note change-note-rejected' : 'change-note'}>
      <span className="change-note-icon">
        <Icon name={isRejected ? 'x-circle' : 'check-circle'} />
      </span>
      <div>
        <p className="change-note-label">
          {STATUS_LABELS[request.status]} by {request.decided_by_name} on{' '}
          {formatDateTime(request.decided_at)}
        </p>
        {request.decision_reason !== null && (
          <p className="wrap-anywhere">{request.decision_reason}</p>
        )}
      </div>
    </div>
  )
}
