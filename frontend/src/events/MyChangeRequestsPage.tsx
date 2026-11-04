import { useState, type MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import {
  listMyChangeRequests,
  type ChangeRequestQueueEntry,
  type ChangeRequestStatus,
} from '../api/changeRequests'
import { fetchEventReferenceData } from '../api/events'
import { EmptyState } from '../components/EmptyState'
import type { EventCardBackState } from '../components/EventCard'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { Tabs } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import {
  CHANGE_REQUESTS_HEADING,
  CHANGE_REQUESTS_TITLE,
  EVENTS_MINE_PATH,
  eventPath,
  MY_CHANGE_REQUESTS_PATH,
} from '../routes'
import {
  formatDateTime,
  formatSchedule,
  REQUESTED_AT_LABEL,
  shortReference,
} from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { ChangeRequestChanges } from './ChangeRequestChanges'
import { ChangeRequestDecision } from './ChangeRequestDecision'
import { changeTitle, STATUS_LABELS, VIEW_EVENT, YOUR_REASON } from './changeRequestValues'
import { ErrorToast } from '../components/ErrorToast'

type TabKey = 'ALL' | ChangeRequestStatus

/** The tabs of the coordinator's queue (story 19.2), opening on All so the backend's order -
 *  pending first, newest first (AC2) - reads as one list. */
const TABS: { key: TabKey; label: string }[] = [
  { key: 'ALL', label: 'All' },
  ...(['PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'CANCELLED'] as const).map((key) => ({
    key,
    label: STATUS_LABELS[key],
  })),
]

/** What a status tab says when it has nothing in it; All with nothing is AC5's empty state. */
const EMPTY_TAB_MESSAGES: Record<ChangeRequestStatus, string> = {
  PENDING: 'None of your change requests are waiting for a decision.',
  APPROVED: 'None of your change requests have been approved yet.',
  REJECTED: 'None of your change requests have been rejected.',
  WITHDRAWN: 'You have not withdrawn any change requests.',
  CANCELLED: 'None of your change requests were cancelled with their event.',
}

/** An event opened from a row here leads back to this page, not to Home (story 7.1's back link). */
const BACK_TO_MY_CHANGE_REQUESTS: EventCardBackState = {
  from: MY_CHANGE_REQUESTS_PATH,
  fromLabel: CHANGE_REQUESTS_TITLE,
}

function inTab(entry: ChangeRequestQueueEntry, tab: TabKey): boolean {
  return tab === 'ALL' || entry.status === tab
}

/**
 * Story 19.4 - the organiser's change requests across all their events, each card laid out like
 * one in the coordinator's queue (story 19.2), without its decision buttons.
 * AC1: each card names the event, what it changes, when it was raised and its status.
 * AC2: pending first, newest first within each status - the backend's order, kept as sent.
 * AC3: a click anywhere on a card opens its event's page, as the safety queue's cards do (21.1).
 * AC4: only the organiser's own requests come back (the backend scopes them); other roles see
 *      "not permitted" at this address (RequirePermission in App.tsx).
 * AC5: with none, the page says so and points to My events.
 */
export function MyChangeRequestsPage() {
  const { data: requests, error, isLoading } = useLoaded(listMyChangeRequests)
  const { data: references, error: referencesError } = useLoaded(fetchEventReferenceData)
  const [tab, setTab] = useState<TabKey>('ALL')
  const navigate = useNavigate()
  const entries = requests?.filter((entry) => inTab(entry, tab)) ?? null
  const tabs = TABS.map((item) => ({
    ...item,
    label: `${item.label} (${requests?.filter((entry) => inTab(entry, item.key)).length ?? 0})`,
  }))
  const tabLabel = TABS.find((item) => item.key === tab)?.label ?? ''

  /** AC3: a plain left click on the card, outside its links and not ending a text selection. */
  function openRow(click: MouseEvent<HTMLLIElement>, eventId: string) {
    if (click.button !== 0 || click.metaKey || click.ctrlKey || click.shiftKey || click.altKey)
      return
    if (click.target instanceof Element && click.target.closest('a, button')) return
    if (window.getSelection()?.isCollapsed === false) return
    navigate(eventPath(eventId), { state: BACK_TO_MY_CHANGE_REQUESTS })
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title={CHANGE_REQUESTS_HEADING}
        subtitle="The changes you have asked for on your events, and where each one stands."
      />

      {error && <ErrorToast message={error} />}
      {referencesError && <ErrorToast message={referencesError} />}

      <div className="stack">
        <Tabs tabs={tabs} activeKey={tab} onChange={setTab} />

        {isLoading && <LoadingState label="Loading your change requests…" />}

        {entries !== null && entries.length === 0 && (
          <EmptyState>
            {tab === 'ALL' ? (
              <>
                You have not raised any change requests yet. Ask for one from an approved event in{' '}
                <Link to={EVENTS_MINE_PATH}>My events</Link>.
              </>
            ) : (
              EMPTY_TAB_MESSAGES[tab]
            )}
          </EmptyState>
        )}

        {entries !== null && entries.length > 0 && (
          <ul className="stack queue-list" aria-label={`${tabLabel} change requests`}>
            {entries.map((entry) => (
              <li
                key={entry.id}
                className="card stack queue-card-linked"
                onClick={(click) => openRow(click, entry.event_id)}
              >
                <div className="item-card-header">
                  <StatusBadge status={entry.status} label={STATUS_LABELS[entry.status]} />
                  {entry.event_starts_at !== null && entry.event_ends_at !== null && (
                    <div className="item-card-capacity item-card-period">
                      <div>{formatSchedule(entry.event_starts_at, entry.event_ends_at)}</div>
                    </div>
                  )}
                </div>

                <div>
                  <div className="cluster">
                    <h3 className="queue-card-title">
                      <Link to={eventPath(entry.event_id)} state={BACK_TO_MY_CHANGE_REQUESTS}>
                        {entry.event_name}
                      </Link>
                    </h3>
                    <EventStatusBadge status={entry.event_status} />
                  </div>
                  <p className="muted">
                    {changeTitle(entry.field)}{' '}
                    <span className="small mono">{shortReference(entry.id)}</span>
                  </p>
                </div>

                <div className="fact-grid">
                  <div className="subtle-block">
                    <p className="fact-label">{REQUESTED_AT_LABEL}</p>
                    <p className="fact-value">{formatDateTime(entry.created_at)}</p>
                  </div>
                </div>

                <ChangeRequestChanges request={entry} references={references} />

                <div className="change-note">
                  <span className="change-note-icon">
                    <Icon name="message" />
                  </span>
                  <div>
                    <p className="change-note-label">{YOUR_REASON}</p>
                    <p className="wrap-anywhere">{entry.reason}</p>
                  </div>
                </div>

                <ChangeRequestDecision request={entry} />

                <div className="item-card-footer item-card-footer-end">
                  <Link
                    to={eventPath(entry.event_id)}
                    state={BACK_TO_MY_CHANGE_REQUESTS}
                    className="link"
                  >
                    {VIEW_EVENT}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
