import { useCallback, useMemo, useState } from 'react'
import { listReviewQueue, type ReviewQueueEntry, type ReviewQueueSort } from '../api/events'
import { useAuth } from '../auth/authContext'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { Tabs } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import { EVENTS_INBOX_PATH, eventPath } from '../routes'
import { formatDateTime, formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

const BACK_TO_INBOX = { from: EVENTS_INBOX_PATH, fromLabel: 'Events inbox' }

const SORT_OPTIONS: { key: ReviewQueueSort; label: string }[] = [
  { key: 'submitted_at', label: 'Submission date' },
  { key: 'starts_at', label: 'Proposed event date' },
]

/**
 * The coordinator dashboard's tab strip (finalised prototype, `App.tsx`'s `CoordinatorDashboard`).
 * Only `review` is wired to real data; the rest are placeholders until a later story adds an
 * events listing that carries a lifecycle stage.
 */
type InboxTab = 'review' | 'planning' | 'confirmed' | 'completed'

const INBOX_TABS: { key: InboxTab; label: string }[] = [
  { key: 'review', label: 'Under Review' },
  { key: 'planning', label: 'Planning' },
  { key: 'confirmed', label: 'Confirmed' },
  { key: 'completed', label: 'Completed' },
]

const UNWIRED_TAB_MESSAGES: Record<Exclude<InboxTab, 'review'>, string> = {
  planning: 'Events in planning will appear here in a later story.',
  confirmed: 'Confirmed events will appear here in a later story.',
  completed: 'Completed events will appear here in a later story.',
}

function matchesSearch(entry: ReviewQueueEntry, search: string): boolean {
  const term = search.trim().toLowerCase()
  if (term === '') return true
  return (
    entry.name.toLowerCase().includes(term) || entry.organiser_name.toLowerCase().includes(term)
  )
}

/**
 * Story 4.1 - the coordinator review queue.
 * AC1: requests awaiting a decision, assigned to the signed-in coordinator.
 * AC2: each entry shows the event name, organiser, proposed date and submission date.
 * AC3: the queue can be ordered by submission date or proposed event date.
 * AC4: drafts and already-decided requests never appear — the backend query excludes them.
 *
 * The tab strip mirrors the coordinator dashboard shape from the finalised prototype. Only
 * "Under Review" is wired to real data; "Planning", "Confirmed" and "Completed" are placeholders
 * until a later story adds an events listing that carries a lifecycle stage.
 */
export function ReviewQueuePage() {
  const { user } = useAuth()
  const [sort, setSort] = useState<ReviewQueueSort>('submitted_at')
  const [search, setSearch] = useState('')
  const [tab, setTab] = useState<InboxTab>('review')

  const coordinatorId = user?.id ?? null

  const load = useCallback(() => listReviewQueue({ sort, coordinatorId }), [sort, coordinatorId])
  const { data: entries, error } = useLoaded(load)

  const shownEntries = useMemo(
    () => (entries ?? []).filter((entry) => matchesSearch(entry, search)),
    [entries, search],
  )

  function clearSearch() {
    setSearch('')
  }

  if (!user) return null

  return (
    <div className="page page-wide">
      <p className="eyebrow">Events</p>
      <PageHeader
        title="Events inbox"
        subtitle="Requests waiting for your decision. The other tabs fill in as later stories land."
      />

      <Tabs
        tabs={INBOX_TABS.map((item) => ({
          key: item.key,
          label:
            item.key === 'review' && entries !== null
              ? `${item.label} (${entries.length})`
              : item.label,
        }))}
        activeKey={tab}
        onChange={setTab}
      />

      {tab !== 'review' && <EmptyState>{UNWIRED_TAB_MESSAGES[tab]}</EmptyState>}

      {tab === 'review' && (
        <div className="stack">
          <div className="filter-bar">
            <label className="filter-grow">
              Search requests
              <input
                type="search"
                placeholder="Event or organiser"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <label>
              Order by
              <select value={sort} onChange={(e) => setSort(e.target.value as ReviewQueueSort)}>
                {SORT_OPTIONS.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {entries === null && !error && <LoadingState label="Loading the review queue…" />}

          {entries !== null && entries.length === 0 && (
            <EmptyState>Nothing is waiting for your decision.</EmptyState>
          )}

          {entries !== null && entries.length > 0 && shownEntries.length === 0 && (
            <EmptyState>
              No requests match your search.{' '}
              <button type="button" className="link" onClick={clearSearch}>
                Clear search
              </button>
            </EmptyState>
          )}

          {shownEntries.length > 0 && (
            <>
              <p className="small muted">
                Showing {shownEntries.length} of {entries?.length ?? 0} requests
              </p>
              <EventCardGrid>
                {shownEntries.map((entry) => (
                  <EventCard
                    key={entry.id}
                    title={entry.name}
                    imageUrl={entry.cover_image_url}
                    to={eventPath(entry.id)}
                    state={BACK_TO_INBOX}
                    details={[
                      formatSchedule(entry.starts_at, entry.ends_at),
                      `Requested by ${entry.organiser_name}`,
                      entry.submitted_at
                        ? `Submitted ${formatDateTime(entry.submitted_at)}`
                        : 'Submission date not recorded',
                    ]}
                  />
                ))}
              </EventCardGrid>
            </>
          )}
        </div>
      )}
    </div>
  )
}
