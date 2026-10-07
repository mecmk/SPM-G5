import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router'
import {
  listEquipmentRequests,
  type EquipmentQueueCounts,
  type EquipmentQueueStatus,
} from '../api/equipment'
import { EmptyState } from '../components/EmptyState'
import type { EventCardBackState } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { Tabs } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import { EQUIPMENT_REQUESTS_PATH, eventPath } from '../routes'
import { formatDate, formatTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

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

/**
 * Story 15.2 - Technical Support's equipment request queue, laid out like Venue Staff's booking
 * queue (story 13.1).
 * AC1: each request shows its event's name and dates, the item's type, quantity and technical
 * notes, and the coordinator who sent it, soonest event first (the backend's order).
 * AC2: how many of the type the event's period has for it, and any shortfall.
 * AC3: Pending, Accepted and Declined tabs, and All, each labelled with how many requests it
 * holds. View details opens the event (story 7.1), whose back link returns here.
 * AC5: an empty tab says so. AC7: every visit and every tab change loads the figures afresh.
 * Deciding a request is story 16.1, so the cards carry no actions.
 */
export function EquipmentRequestsPage() {
  const [tab, setTab] = useState<EquipmentQueueTabKey>('PENDING')
  const loadTab = useCallback(() => listEquipmentRequests(tab === 'ALL' ? null : tab), [tab])
  const { data: queue, error, isLoading, isStale } = useLoaded(loadTab)

  const tabs = useMemo(
    () =>
      EQUIPMENT_QUEUE_TABS.map((item) => ({
        key: item.key,
        label: `${item.label} (${queue ? tabCount(item.key, queue.counts) : 0})`,
      })),
    [queue],
  )

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
                      <p className="fact-label">Available for this event</p>
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
                      <p className="fact-value">{entry.requested_by_name ?? 'Not recorded'}</p>
                    </div>
                  </div>

                  <div className="subtle-block">
                    <p className="fact-label">Technical notes</p>
                    <p>{notesText(entry.technical_notes)}</p>
                  </div>

                  <div className="item-card-footer item-card-footer-end">
                    <Link to={eventPath(entry.event_id)} state={BACK_TO_QUEUE} className="link">
                      View details →
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
