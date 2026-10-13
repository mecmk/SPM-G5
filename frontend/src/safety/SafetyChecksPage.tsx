import { useState, type MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { listSafetyChecks, type SafetyQueueEntry, type SafetyQueueStatus } from '../api/safety'
import { EmptyState } from '../components/EmptyState'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { PageHeader } from '../components/PageHeader'
import { Tabs } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import { safetyCheckPath } from '../routes'
import { formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

type SafetyQueueTabKey = 'ALL' | SafetyQueueStatus

/** Story 21.1 AC2 (team request beyond the AC): All, Pending, Accepted and Declined, in the order
 * of Technical Support's equipment queue. The page opens on Pending so it reads as a queue. */
const SAFETY_QUEUE_TABS: { key: SafetyQueueTabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'PENDING', label: 'Pending' },
  { key: 'ACCEPTED', label: 'Accepted' },
  { key: 'DECLINED', label: 'Declined' },
]

/** Every tab is filtered from the one full list, so each tab label carries its count. */
function inTab(entry: SafetyQueueEntry, tab: SafetyQueueTabKey): boolean {
  return tab === 'ALL' || entry.safety_status === tab
}

function loadAllSafetyChecks() {
  return listSafetyChecks(null)
}

/**
 * Story 21.1 - the Safety Officer's queue, laid out like Technical Support's equipment queue
 * (story 15.2).
 * AC2: each event awaiting the safety check, with its name, dates, expected attendance, approved
 * venues and status, oldest first (the backend's order). Pending lists those; Accepted and
 * Declined list events no longer awaiting the check, by their latest review; All lists the three.
 * The card opens the event's safety details (AC3): the name is the one real link, and a click
 * anywhere else on the card follows it too, as `EventCard` does.
 */
export function SafetyChecksPage() {
  const [tab, setTab] = useState<SafetyQueueTabKey>('PENDING')
  const { data: allEntries, error, isLoading } = useLoaded(loadAllSafetyChecks)
  const navigate = useNavigate()
  const entries = allEntries?.filter((entry) => inTab(entry, tab)) ?? null
  const tabs = SAFETY_QUEUE_TABS.map((item) => ({
    ...item,
    label: `${item.label} (${allEntries?.filter((entry) => inTab(entry, item.key)).length ?? 0})`,
  }))

  function openCard(click: MouseEvent<HTMLLIElement>, eventId: string) {
    if (click.button !== 0 || click.metaKey || click.ctrlKey || click.shiftKey || click.altKey)
      return
    if (click.target instanceof Element && click.target.closest('a')) return
    if (window.getSelection()?.isCollapsed === false) return
    navigate(safetyCheckPath(eventId))
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Safety Checks"
        subtitle="Events awaiting the operational safety check, and those already reviewed."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <div className="stack">
        <Tabs tabs={tabs} activeKey={tab} onChange={setTab} />

        {isLoading && <LoadingState label="Loading safety checks…" />}

        {entries !== null && entries.length === 0 && (
          <EmptyState>
            {tab === 'PENDING'
              ? 'No events are awaiting a safety check.'
              : 'No events in this tab.'}
          </EmptyState>
        )}

        {entries !== null && entries.length > 0 && (
          <ul className="stack">
            {entries.map((entry) => (
              <li
                key={entry.id}
                className="card stack queue-card-linked"
                onClick={(click) => openCard(click, entry.id)}
              >
                <div className="item-card-header">
                  <EventStatusBadge status={entry.status} />
                  <div className="item-card-capacity item-card-period">
                    <div>{formatSchedule(entry.starts_at, entry.ends_at)}</div>
                  </div>
                </div>

                <h3 className="queue-card-title">
                  <Link to={safetyCheckPath(entry.id)}>{entry.name}</Link>
                </h3>

                <div className="fact-grid">
                  <div className="subtle-block">
                    <p className="fact-label">Expected attendance</p>
                    <p className="fact-value">{entry.expected_attendance}</p>
                  </div>
                  <div className="subtle-block">
                    <p className="fact-label">Approved venues</p>
                    <p className="fact-value">
                      {entry.venue_names.length > 0 ? entry.venue_names.join(', ') : 'None'}
                    </p>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
