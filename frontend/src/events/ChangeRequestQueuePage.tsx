import { useState } from 'react'
import { Link } from 'react-router'
import {
  listPendingChangeRequests,
  type ChangeRequest,
  type ChangeRequestQueueEntry,
} from '../api/changeRequests'
import { fetchEventReferenceData } from '../api/events'
import { EmptyState } from '../components/EmptyState'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import { eventPath } from '../routes'
import { formatDateTime, formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { ChangeRequestDecisionDialog } from './ChangeRequestDecisionDialog'
import {
  canApproveYet,
  describeValue,
  FIELD_LABELS,
  NOT_YET_APPROVABLE_NOTE,
} from './changeRequestValues'

/** The decision dialog open on the queue: which request, and approving or rejecting it. */
interface OpenDecision {
  entry: ChangeRequestQueueEntry
  outcome: 'APPROVED' | 'REJECTED'
}

/**
 * Story 19.2 - the coordinator's queue of change requests waiting for a decision.
 * AC1: every pending request on the coordinator's own events, oldest first (the backend's order),
 * each with its event, the field, its value now and the value asked for, the reason, who asked
 * and when. AC2/AC3: Approve and Reject open the shared decision dialog; a decided request leaves
 * the queue, and one refused because it moved on meanwhile has the queue load again (AC7).
 * Phase 1: Approve is offered only where it can be made yet (`canApproveYet`).
 */
export function ChangeRequestQueuePage() {
  const { data: queue, error, isLoading, setData: setQueue } = useLoaded(listPendingChangeRequests)
  const { data: references } = useLoaded(fetchEventReferenceData)
  const [openDecision, setOpenDecision] = useState<OpenDecision | null>(null)

  function closeDecision() {
    setOpenDecision(null)
  }

  function removeDecided(decided: ChangeRequest) {
    setQueue((current) => current && current.filter((entry) => entry.id !== decided.id))
    setOpenDecision(null)
  }

  /** AC7: a decision refused for the request's state - load the queue again, so it shows what
   *  happened meanwhile. */
  async function reloadQueue() {
    try {
      setQueue(await listPendingChangeRequests())
    } catch {
      // The dialog already shows the refusal; the queue keeps what it last loaded.
    }
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Change requests"
        subtitle="Changes organisers have asked for on your events, waiting for your decision."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {isLoading && <LoadingState label="Loading change requests…" />}

      {queue !== null && queue.length === 0 && (
        <EmptyState>No change requests are waiting for your decision.</EmptyState>
      )}

      {queue !== null && queue.length > 0 && (
        <ul className="stack" aria-label="Pending change requests">
          {queue.map((entry) => (
            <li key={entry.id} className="card stack">
              <div className="item-card-header">
                <EventStatusBadge status={entry.event_status} />
                {entry.event_starts_at !== null && entry.event_ends_at !== null && (
                  <div className="item-card-capacity item-card-period">
                    <div>{formatSchedule(entry.event_starts_at, entry.event_ends_at)}</div>
                  </div>
                )}
              </div>

              <h3 className="queue-card-title">
                <Link to={eventPath(entry.event_id)}>{entry.event_name}</Link>
              </h3>

              <p className="change-request-text">
                <strong>{FIELD_LABELS[entry.field]}</strong>
                <br />
                <span className="small">
                  Now: {describeValue(entry.field, entry.current_value, references)}
                </span>
                <br />
                <span className="small">
                  Requested: {describeValue(entry.field, entry.proposed_value, references)}
                </span>
                <br />
                <span className="small muted wrap-anywhere">
                  “{entry.reason}” · {entry.requested_by_name}, {formatDateTime(entry.created_at)}
                </span>
              </p>

              <div className="page-actions">
                {canApproveYet(entry.field, entry.event_status) ? (
                  <button
                    type="button"
                    onClick={() => setOpenDecision({ entry, outcome: 'APPROVED' })}
                  >
                    Approve
                  </button>
                ) : (
                  <span className="small muted">{NOT_YET_APPROVABLE_NOTE}</span>
                )}
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setOpenDecision({ entry, outcome: 'REJECTED' })}
                >
                  Reject
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {openDecision !== null && (
        <ChangeRequestDecisionDialog
          request={openDecision.entry}
          outcome={openDecision.outcome}
          references={references}
          onCancel={closeDecision}
          onDecided={removeDecided}
          onRefused={reloadQueue}
        />
      )}
    </div>
  )
}
