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
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { eventPath } from '../routes'
import { formatDate, formatDateTime, formatTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { ChangeRequestDecisionDialog } from './ChangeRequestDecisionDialog'
import { ChangeRequestChanges } from './ChangeRequestChanges'
import { changeTitle, STATUS_LABELS } from './changeRequestValues'

/** The decision dialog open on the queue: which request, and approving or rejecting it. */
interface OpenDecision {
  entry: ChangeRequestQueueEntry
  outcome: 'APPROVED' | 'REJECTED'
}

/**
 * Story 19.2 - the coordinator's queue of change requests waiting for a decision, each card laid
 * out like one in Venue Staff's booking queue (story 13.1).
 * AC1: every pending request on the coordinator's own events, oldest first (the backend's order),
 * each with its event, the field, its value now and the value asked for, the reason, who asked
 * and when. AC2/AC3: Approve and Reject open the shared decision dialog; a decided request leaves
 * the queue, and one refused because it moved on meanwhile has the queue load again (AC7).
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
        title="Change Requests"
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
        <ul className="stack queue-list" aria-label="Pending change requests">
          {queue.map((entry) => (
            <li key={entry.id} className="card stack">
              <div className="item-card-header">
                <div className="cluster">
                  <StatusBadge status={entry.status} label={STATUS_LABELS[entry.status]} />
                  <EventStatusBadge status={entry.event_status} />
                </div>
                {entry.event_starts_at !== null && entry.event_ends_at !== null && (
                  <div className="item-card-capacity">
                    <div>{formatDate(entry.event_starts_at)}</div>
                    <div className="small muted">
                      {formatTime(entry.event_starts_at)}–{formatTime(entry.event_ends_at)}
                    </div>
                  </div>
                )}
              </div>

              <div>
                <h3 className="queue-card-title">
                  <Link to={eventPath(entry.event_id)}>{entry.event_name}</Link>
                </h3>
                <p className="muted">{changeTitle(entry.field)}</p>
              </div>

              <div className="fact-grid">
                <div className="subtle-block">
                  <p className="fact-label">Requested by</p>
                  <p className="fact-value">{entry.requested_by_name}</p>
                </div>
                <div className="subtle-block">
                  <p className="fact-label">Requested at</p>
                  <p className="fact-value">{formatDateTime(entry.created_at)}</p>
                </div>
              </div>

              <ChangeRequestChanges request={entry} references={references} />

              <div className="change-note">
                <span className="change-note-icon">
                  <Icon name="message" />
                </span>
                <div>
                  <p className="change-note-label">Organiser's reason</p>
                  <p className="wrap-anywhere">{entry.reason}</p>
                </div>
              </div>

              <div className="item-card-footer">
                <div className="cluster">
                  <button
                    type="button"
                    className="brand button-sm"
                    onClick={() => setOpenDecision({ entry, outcome: 'APPROVED' })}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="danger-solid button-sm"
                    onClick={() => setOpenDecision({ entry, outcome: 'REJECTED' })}
                  >
                    Reject
                  </button>
                </div>
                <Link to={eventPath(entry.event_id)} className="link">
                  View event →
                </Link>
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
          eventStatus={openDecision.entry.event_status}
          onCancel={closeDecision}
          onDecided={removeDecided}
          onRefused={reloadQueue}
        />
      )}
    </div>
  )
}
