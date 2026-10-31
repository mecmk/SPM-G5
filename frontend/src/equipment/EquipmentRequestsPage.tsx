import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router'
import {
  listEquipmentRequests,
  type EquipmentDecisionOutcome,
  type EquipmentQueue,
  type EquipmentQueueCounts,
  type EquipmentQueueEntry,
  type EquipmentQueueOrder,
  type EquipmentQueueStatus,
  type EquipmentShortfall,
} from '../api/equipment'
import { EmptyState } from '../components/EmptyState'
import type { EventCardBackState } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { QueueSearchBar } from '../components/QueueSearchBar'
import { StatusBadge } from '../components/StatusBadge'
import { Tabs } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import { EQUIPMENT_REQUESTS_PATH, equipmentRequestPath, eventPath } from '../routes'
import {
  CANCELLED_AT_LABEL,
  CLEAR_SEARCH,
  NOT_RECORDED,
  WITHDRAWN_AT_LABEL,
  formatDateTime,
  formatSchedule,
  shortReference,
} from '../shared/format'
import {
  COMMON_QUEUE_ORDERS,
  DEFAULT_QUEUE_ORDER,
  queuePath,
  useQueueView,
  type QueueOrderOption,
  type QueueViewOptions,
} from '../shared/queueView'
import { useLoaded } from '../shared/useLoaded'
import { EquipmentDecisionDialog } from './EquipmentDecisionDialog'

const PAGE_TITLE = 'Equipment Requests'

type EquipmentQueueTabKey = 'ALL' | EquipmentQueueStatus

/** Story 15.2 AC3: the queue's tabs, plus All (a team request beyond the AC), in the order of
 * Venue Staff's booking queue. The page opens on Pending so it reads as a queue. Story 6.2 AC15:
 * Cancelled, read-only, for requests whose event was cancelled after they were sent. Story 17.2
 * AC4: Withdrawn, read-only, for requests their coordinator withdrew. */
const EQUIPMENT_QUEUE_TABS: { key: EquipmentQueueTabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'PENDING', label: 'Pending' },
  { key: 'ACCEPTED', label: 'Accepted' },
  { key: 'DECLINED', label: 'Declined' },
  { key: 'CANCELLED', label: 'Cancelled' },
  { key: 'WITHDRAWN', label: 'Withdrawn' },
]

/** Story 13.3 AC3: the equipment queue's orders, as its Order by list offers them. */
const EQUIPMENT_QUEUE_ORDERS: QueueOrderOption<EquipmentQueueOrder>[] = [
  ...COMMON_QUEUE_ORDERS,
  { key: 'equipment_type', label: 'Equipment type: A to Z' },
]

/** Story 13.3 AC7: what the queue's address may name. With none, it opens on Pending, soonest
 * event first. The queue has no pages, so its page stays 1. */
const EQUIPMENT_QUEUE_VIEW: QueueViewOptions<EquipmentQueueTabKey, EquipmentQueueOrder> = {
  tabs: EQUIPMENT_QUEUE_TABS.map((item) => item.key),
  orders: EQUIPMENT_QUEUE_ORDERS.map((option) => option.key),
  defaults: { tab: 'PENDING', search: '', order: DEFAULT_QUEUE_ORDER, page: 1 },
}

/** How many requests a tab holds, from the backend's per-status counts. */
function tabCount(tab: EquipmentQueueTabKey, counts: EquipmentQueueCounts): number {
  switch (tab) {
    case 'ALL':
      return (
        counts.pending + counts.accepted + counts.declined + counts.cancelled + counts.withdrawn
      )
    case 'PENDING':
      return counts.pending
    case 'ACCEPTED':
      return counts.accepted
    case 'DECLINED':
      return counts.declined
    case 'CANCELLED':
      return counts.cancelled
    case 'WITHDRAWN':
      return counts.withdrawn
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
 *
 * Story 6.2 AC15: a Cancelled tab lists, read-only, the requests closed when their event was
 * cancelled; their cards leave out what is available, since nothing is held for them any more.
 * AC16: such a card says when it was cancelled.
 *
 * Story 17.2 AC4: a Withdrawn tab lists, read-only, the requests their coordinator withdrew, each
 * saying when and by whom, with no figures, since nothing is held for them any more.
 *
 * Story 13.3 AC1-AC3: a search box and an Order by list beside the tabs; the server searches the
 * event name, equipment type and Requested by, orders the tab and counts each tab's matches. AC6:
 * a search nothing matches says so, with Clear search. AC7: the tab, search and order live in the
 * page address, and the request's page and its event's page lead back to the same list; a
 * decision updates the list in place, so the search and order stay.
 */
export function EquipmentRequestsPage() {
  const { view, query, changeView } = useQueueView(EQUIPMENT_QUEUE_VIEW)
  const { tab } = view
  const loadTab = useCallback(
    () =>
      listEquipmentRequests({
        status: view.tab === 'ALL' ? null : view.tab,
        search: view.search,
        order: view.order,
      }),
    [view],
  )
  const { data: queue, error, isLoading, isStale, setData: setQueue } = useLoaded(loadTab)
  const [openDecision, setOpenDecision] = useState<OpenDecision | null>(null)
  // Story 13.3 AC7: the request's page and its event's page lead back to this list as it stands.
  const backToQueue: EventCardBackState = {
    from: queuePath(EQUIPMENT_REQUESTS_PATH, query),
    fromLabel: PAGE_TITLE,
  }
  const isSearched = view.search.trim() !== ''

  const tabs = useMemo(
    () =>
      EQUIPMENT_QUEUE_TABS.map((item) => ({
        key: item.key,
        label: `${item.label} (${queue ? tabCount(item.key, queue.counts) : 0})`,
      })),
    [queue],
  )

  function changeTab(next: EquipmentQueueTabKey) {
    changeView({ tab: next })
  }

  const changeSearch = useCallback((search: string) => changeView({ search }), [changeView])

  function changeOrder(order: EquipmentQueueOrder) {
    changeView({ order })
  }

  function clearSearch() {
    changeView({ search: '' })
  }

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
        title={PAGE_TITLE}
        subtitle="Equipment requests sent to Technical Support, with what is available for each."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading equipment requests…" />}

      {queue !== null && (
        <div className="stack">
          <Tabs tabs={tabs} activeKey={tab} onChange={changeTab} />

          <QueueSearchBar
            search={view.search}
            placeholder="Event, equipment or who requested it"
            onSearch={changeSearch}
            order={view.order}
            orders={EQUIPMENT_QUEUE_ORDERS}
            onOrder={changeOrder}
          />

          {/* Below the search box, so the box stays where it is while the list loads. */}
          {isStale && error === null && <LoadingState label="Loading equipment requests…" />}

          {!isStale && queue.items.length === 0 && isSearched && (
            <EmptyState>
              No equipment requests match your search.{' '}
              <button type="button" className="link" onClick={clearSearch}>
                {CLEAR_SEARCH}
              </button>
            </EmptyState>
          )}

          {!isStale && queue.items.length === 0 && !isSearched && (
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
                      <span className="small muted mono">{shortReference(entry.id)}</span>
                    </div>
                    <div className="item-card-capacity item-card-period">
                      <div>{formatSchedule(entry.starts_at, entry.ends_at)}</div>
                    </div>
                  </div>

                  <div>
                    <h3 className="queue-card-title">
                      <Link to={eventPath(entry.event_id)} state={backToQueue}>
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
                    {entry.available !== null && (
                      <>
                        <div className="subtle-block">
                          <p className="fact-label">Available</p>
                          <p className="fact-value">{entry.available}</p>
                        </div>
                        <div className="subtle-block">
                          <p className="fact-label">Shortfall</p>
                          <p className="fact-value">
                            {entry.shortfall !== null && entry.shortfall > 0 ? (
                              <span className="badge badge-warning">
                                Short by {entry.shortfall}
                              </span>
                            ) : (
                              'None'
                            )}
                          </p>
                        </div>
                      </>
                    )}
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

                  {entry.status === 'CANCELLED' && (
                    <div className="subtle-block">
                      <p className="fact-label">{CANCELLED_AT_LABEL}</p>
                      <p>
                        {entry.cancelled_at === null
                          ? NOT_RECORDED
                          : formatDateTime(entry.cancelled_at)}
                      </p>
                    </div>
                  )}

                  {entry.status === 'WITHDRAWN' && (
                    <div className="subtle-block">
                      <p className="fact-label">{WITHDRAWN_AT_LABEL}</p>
                      <p>
                        {entry.withdrawn_at === null
                          ? NOT_RECORDED
                          : formatDateTime(entry.withdrawn_at)}
                        {entry.withdrawn_by_name !== null && ` by ${entry.withdrawn_by_name}`}
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
                    <Link to={equipmentRequestPath(entry.id)} state={backToQueue} className="link">
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
