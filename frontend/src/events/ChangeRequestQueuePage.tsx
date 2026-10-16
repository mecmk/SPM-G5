import { useState } from 'react'
import { Link } from 'react-router'
import {
  listCoordinatorChangeRequests,
  type ChangeRequest,
  type ChangeRequestQueueEntry,
  type ChangeRequestStatus,
} from '../api/changeRequests'
import { fetchEventReferenceData } from '../api/events'
import { EmptyState } from '../components/EmptyState'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { Tabs } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import { eventPath } from '../routes'
import { formatDate, formatDateTime, formatTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { ChangeRequestChanges } from './ChangeRequestChanges'
import { ChangeRequestDecision } from './ChangeRequestDecision'
import { ChangeRequestDecisionDialog } from './ChangeRequestDecisionDialog'
import { changeTitle, STATUS_LABELS } from './changeRequestValues'

type QueueTabKey = 'ALL' | ChangeRequestStatus

/** Story 19.2 AC1 (team request, 16 Oct 2026): All first, then Pending and the record of
 *  decisions, in the order of the Safety Officer's queue (story 21.1). The page opens on Pending,
 *  so it reads as a queue. */
const QUEUE_TABS: { key: QueueTabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'PENDING', label: 'Pending' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'REJECTED', label: 'Rejected' },
  { key: 'WITHDRAWN', label: 'Withdrawn' },
]

/** What each tab says when it has nothing in it. */
const EMPTY_TAB_MESSAGES: Record<QueueTabKey, string> = {
  PENDING: 'No change requests are waiting for your decision.',
  APPROVED: 'You have not approved any change requests yet.',
  REJECTED: 'You have not rejected any change requests yet.',
  WITHDRAWN: 'No change requests on your events have been withdrawn.',
  ALL: 'No change requests have been made on your events yet.',
}

/** Every tab is filtered from the one list, in the backend's order, so each label can carry its
 *  count. */
function inTab(entry: ChangeRequestQueueEntry, tab: QueueTabKey): boolean {
  return tab === 'ALL' || entry.status === tab
}

/** The decision dialog open on the queue: which request, and approving or rejecting it. */
interface OpenDecision {
  entry: ChangeRequestQueueEntry
  outcome: 'APPROVED' | 'REJECTED'
}

/**
 * Story 19.2 - the coordinator's queue of change requests, and their record of decisions, each
 * card laid out like one in Venue Staff's booking queue (story 13.1).
 * AC1: every request on the coordinator's own events, each with its event, the field, its value
 * now and the value asked for, the reason, who asked and when; pending ones first, oldest first,
 * then decided or withdrawn ones, latest first (the backend's order), a tab per status.
 * AC2/AC3: Approve and Reject open the shared decision dialog; a decided request moves to its
 * tab, showing who decided, when and why, and one refused because it moved on meanwhile has the
 * queue load again (AC7).
 */
export function ChangeRequestQueuePage() {
  const {
    data: queue,
    error,
    isLoading,
    setData: setQueue,
  } = useLoaded(listCoordinatorChangeRequests)
  const { data: references, error: referencesError } = useLoaded(fetchEventReferenceData)
  const [tab, setTab] = useState<QueueTabKey>('PENDING')
  const [openDecision, setOpenDecision] = useState<OpenDecision | null>(null)
  const entries = queue?.filter((entry) => inTab(entry, tab)) ?? null
  const tabs = QUEUE_TABS.map((item) => ({
    ...item,
    label: `${item.label} (${queue?.filter((entry) => inTab(entry, item.key)).length ?? 0})`,
  }))
  const tabLabel = QUEUE_TABS.find((item) => item.key === tab)?.label ?? ''

  function closeDecision() {
    setOpenDecision(null)
  }

  /** AC2/AC3: the decided request takes its new status in place, so it leaves Pending for its
   *  own tab, with who decided, when and why. An approval may also have changed the event - its
   *  dates, or its status back to Planning (AC8) - which every card for it shows, so the queue
   *  loads again. */
  function recordDecision(decided: ChangeRequest) {
    setQueue(
      (current) =>
        current &&
        current.map((entry) => (entry.id === decided.id ? { ...entry, ...decided } : entry)),
    )
    setOpenDecision(null)
    if (decided.status === 'APPROVED') void reloadQueue()
  }

  /** AC7: a decision refused for the request's state - load the queue again, so it shows what
   *  happened meanwhile. */
  async function reloadQueue() {
    try {
      setQueue(await listCoordinatorChangeRequests())
    } catch {
      // The dialog already shows the refusal; the queue keeps what it last loaded.
    }
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Change Requests"
        subtitle="Changes organisers have asked for on your events: those waiting for your decision, and those already decided."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {referencesError && (
        <p role="alert" className="error">
          {referencesError}
        </p>
      )}

      <div className="stack">
        <Tabs tabs={tabs} activeKey={tab} onChange={setTab} />

        {isLoading && <LoadingState label="Loading change requests…" />}

        {entries !== null && entries.length === 0 && (
          <EmptyState>{EMPTY_TAB_MESSAGES[tab]}</EmptyState>
        )}

        {entries !== null && entries.length > 0 && (
          <ul className="stack queue-list" aria-label={`${tabLabel} change requests`}>
            {entries.map((entry) => (
              <li key={entry.id} className="card stack">
                <div className="item-card-header">
                  <StatusBadge status={entry.status} label={STATUS_LABELS[entry.status]} />
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
                  {/* The event's status sits with its name, apart from the request's own. */}
                  <div className="cluster">
                    <h3 className="queue-card-title">
                      <Link to={eventPath(entry.event_id)}>{entry.event_name}</Link>
                    </h3>
                    <EventStatusBadge status={entry.event_status} />
                  </div>
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

                <ChangeRequestDecision request={entry} />

                <div
                  className={
                    entry.status === 'PENDING'
                      ? 'item-card-footer'
                      : 'item-card-footer item-card-footer-end'
                  }
                >
                  {entry.status === 'PENDING' && (
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
                  )}
                  <Link to={eventPath(entry.event_id)} className="link">
                    View event →
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {openDecision !== null && (
        <ChangeRequestDecisionDialog
          request={openDecision.entry}
          outcome={openDecision.outcome}
          references={references}
          eventStatus={openDecision.entry.event_status}
          onCancel={closeDecision}
          onDecided={recordDecision}
          onRefused={reloadQueue}
        />
      )}
    </div>
  )
}
