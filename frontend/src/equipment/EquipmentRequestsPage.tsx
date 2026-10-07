import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router'
import {
  listEquipmentRequests,
  type EquipmentDecisionOutcome,
  type EquipmentQueue,
  type EquipmentQueueCounts,
  type EquipmentQueueEntry,
  type EquipmentQueueStatus,
  type EquipmentShortfall,
} from '../api/equipment'
import { EmptyState } from '../components/EmptyState'
import type { EventCardBackState } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { Tabs } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import { EQUIPMENT_REQUESTS_PATH, equipmentRequestPath, eventPath } from '../routes'
import { NOT_RECORDED, formatDate, formatDateTime, formatTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { EquipmentDecisionDialog } from './EquipmentDecisionDialog'

const SHORT_ID_LENGTH = 8

type EquipmentQueueTabKey = 'ALL' | EquipmentQueueStatus

/** Story 15.2 AC3: the queue's tabs, plus All (a team request beyond the AC), in the order of
 * Venue Staff's booking queue. The page opens on Pending so it reads as a queue. */
const EQUIPMENT_QUEUE_TABS: { key: EquipmentQueueTabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'PENDING', label: 'Pending' },
  { key: 'ACCEPTED', label: 'Accepted' },
  { key: 'DECLINED', label: 'Declined' },
]

/** The event page's back link returns here (story 7.1's back state). */
const BACK_TO_QUEUE: EventCardBackState = {
  from: EQUIPMENT_REQUESTS_PATH,
  fromLabel: 'Equipment Requests',
}

/** How many requests a tab holds, from the backend's per-status counts. */
function tabCount(tab: EquipmentQueueTabKey, counts: EquipmentQueueCounts): number {
  switch (tab) {
    case 'ALL':
      return counts.pending + counts.accepted + counts.declined
    case 'PENDING':
      return counts.pending
    case 'ACCEPTED':
      return counts.accepted
    case 'DECLINED':
      return counts.declined
  }
}

function notesText(notes: string | null): string {
  return notes && notes.trim() !== '' ? notes : 'No technical notes.'
}

/** Story 16.1: the queue after a decision, without loading it again. Under All the request stays,
 * showing its outcome; under Pending it no longer belongs, so it leaves. Pending loses one and the
 * outcome's tab gains one. */
function withDecision(
  queue: EquipmentQueue,
  decided: EquipmentQueueEntry,
  tab: EquipmentQueueTabKey,
): EquipmentQueue {
  const isKept = tab === 'ALL' || tab === decided.status
  const items = isKept
    ? queue.items.map((entry) => (entry.id === decided.id ? decided : entry))
    : queue.items.filter((entry) => entry.id !== decided.id)
  const counts = { ...queue.counts, pending: queue.counts.pending - 1 }
  if (decided.status === 'ACCEPTED') counts.accepted += 1
  if (decided.status === 'DECLINED') counts.declined += 1
  return { items, counts }
}

/** Story 16.1 AC6: the request's figures as an accept refused for a shortfall reported them, so
 * its card shows the shortfall at once. */
function withFigures(
  queue: EquipmentQueue,
  entryId: string,
  figures: EquipmentShortfall,
): EquipmentQueue {
  return {
    ...queue,
    items: queue.items.map((entry) => (entry.id === entryId ? { ...entry, ...figures } : entry)),
  }
}

/** Story 16.1: the request whose Accept or Decline dialog is open. */
interface OpenDecision {
  entry: EquipmentQueueEntry
  outcome: EquipmentDecisionOutcome
}

/**
 * Story 15.2 - Technical Support's equipment request queue, laid out like Venue Staff's booking
 * queue (story 13.1).
 * AC1: each request shows its event's name and dates, the item's type, quantity and technical
 * notes, and the coordinator who sent it and when, soonest event first (the backend's order).
 * AC2: how many of the type the event's period has for it, and any shortfall.
 * AC3: Pending, Accepted and Declined tabs, and All, each labelled with how many requests it
 * holds. The event's name opens the event (story 7.1), whose back link returns here.
 * AC5: an empty tab says so. AC7: every visit and every tab change loads the figures afresh.
 *
 * Story 16.1 - Accept and Decline on each pending request, as Approve and Reject are on Venue
 * Staff's booking cards (story 13.2), through the dialogs a request's own page uses too; View
 * details opens that page. AC1/AC2: a decided request moves to its outcome's tab, with the reason
 * if declined. AC3: a decided card says when, and by whom, as Venue Staff's booking cards say
 * when they were decided. View details stays on the right of every card. AC6: a refused accept
 * leaves the card showing the shortfall it reported. AC7/AC9: any other refusal loads the tab
 * again, so a decision made elsewhere meanwhile shows.
 */
export function EquipmentRequestsPage() {
  const [tab, setTab] = useState<EquipmentQueueTabKey>('PENDING')
  const loadTab = useCallback(() => listEquipmentRequests(tab === 'ALL' ? null : tab), [tab])
  const { data: queue, error, isLoading, isStale, setData: setQueue } = useLoaded(loadTab)
  const [openDecision, setOpenDecision] = useState<OpenDecision | null>(null)

  const tabs = useMemo(
    () =>
      EQUIPMENT_QUEUE_TABS.map((item) => ({
        key: item.key,
        label: `${item.label} (${queue ? tabCount(item.key, queue.counts) : 0})`,
      })),
    [queue],
  )

  function closeDecision() {
    setOpenDecision(null)
  }

  function recordDecision(decided: EquipmentQueueEntry) {
    setOpenDecision(null)
    setQueue((current) => current && withDecision(current, decided, tab))
  }

  function recordShortfall(figures: EquipmentShortfall) {
    if (openDecision === null) return
    const { id } = openDecision.entry
    setQueue((current) => current && withFigures(current, id, figures))
  }

  /** Story 16.1 AC7/AC9: a decision refused for the request's state - load the tab again, so its
   * cards and counts show what happened meanwhile. */
  async function reloadQueue() {
    try {
      setQueue(await loadTab())
    } catch {
      // The dialog already shows the refusal; the tab keeps what it last loaded.
    }
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Equipment Requests"
        subtitle="Equipment requests sent to Technical Support, with what is available for each."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {(isLoading || (isStale && error === null)) && (
        <LoadingState label="Loading equipment requests…" />
      )}

      {queue !== null && (
        <div className="stack">
          <Tabs tabs={tabs} activeKey={tab} onChange={setTab} />

          {!isStale && queue.items.length === 0 && (
            <EmptyState>
              {tab === 'PENDING'
                ? 'No equipment requests waiting. You are up to date.'
                : 'No equipment requests in this tab.'}
            </EmptyState>
          )}

          {!isStale && queue.items.length > 0 && (
            <ul className="stack">
              {queue.items.map((entry) => (
                <li key={entry.id} className="card stack">
                  <div className="item-card-header">
                    <div className="cluster">
                      <StatusBadge status={entry.status} />
                      <span className="small muted mono">
                        #{entry.id.slice(-SHORT_ID_LENGTH).toUpperCase()}
                      </span>
                    </div>
                    <div className="item-card-capacity">
                      <div>{formatDate(entry.starts_at)}</div>
                      <div className="small muted">
                        {formatTime(entry.starts_at)}–{formatTime(entry.ends_at)}
                      </div>
                    </div>
                  </div>

                  <div>
                    <h3 className="queue-card-title">
                      <Link to={eventPath(entry.event_id)} state={BACK_TO_QUEUE}>
                        {entry.event_name}
                      </Link>
                    </h3>
                    <p className="muted">{entry.equipment_type_name}</p>
                  </div>

                  <div className="fact-grid">
                    <div className="subtle-block">
                      <p className="fact-label">Requested</p>
                      <p className="fact-value">{entry.quantity}</p>
                    </div>
                    <div className="subtle-block">
                      <p className="fact-label">Available</p>
                      <p className="fact-value">{entry.available}</p>
                    </div>
                    <div className="subtle-block">
                      <p className="fact-label">Shortfall</p>
                      <p className="fact-value">
                        {entry.shortfall > 0 ? (
                          <span className="badge badge-warning">Short by {entry.shortfall}</span>
                        ) : (
                          'None'
                        )}
                      </p>
                    </div>
                    <div className="subtle-block">
                      <p className="fact-label">Requested by</p>
                      <p className="fact-value">{entry.requested_by_name ?? NOT_RECORDED}</p>
                    </div>
                    <div className="subtle-block">
                      <p className="fact-label">Requested at</p>
                      <p className="fact-value">
                        {entry.submitted_at === null
                          ? NOT_RECORDED
                          : formatDateTime(entry.submitted_at)}
                      </p>
                    </div>
                  </div>

                  <div className="subtle-block">
                    <p className="fact-label">Technical notes</p>
                    <p>{notesText(entry.technical_notes)}</p>
                  </div>

                  {entry.decided_at !== null && (
                    <div className="subtle-block">
                      <p className="fact-label">Decided at</p>
                      <p>
                        {formatDateTime(entry.decided_at)}
                        {entry.decided_by_name !== null && ` by ${entry.decided_by_name}`}
                      </p>
                    </div>
                  )}

                  {entry.status === 'DECLINED' && (
                    <div className="subtle-block">
                      <p className="fact-label">Reason</p>
                      <p>{entry.decision_reason ?? NOT_RECORDED}</p>
                    </div>
                  )}

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
                          onClick={() => setOpenDecision({ entry, outcome: 'ACCEPTED' })}
                        >
                          Accept
                        </button>
                        <button
                          type="button"
                          className="danger-solid button-sm"
                          onClick={() => setOpenDecision({ entry, outcome: 'DECLINED' })}
                        >
                          Decline
                        </button>
                      </div>
                    )}
                    <Link to={equipmentRequestPath(entry.id)} className="link">
                      View details →
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {openDecision && (
        <EquipmentDecisionDialog
          key={`${openDecision.entry.id}-${openDecision.outcome}`}
          entry={openDecision.entry}
          outcome={openDecision.outcome}
          onCancel={closeDecision}
          onDecided={recordDecision}
          onShortfall={recordShortfall}
          onRefused={reloadQueue}
        />
      )}
    </div>
  )
}
