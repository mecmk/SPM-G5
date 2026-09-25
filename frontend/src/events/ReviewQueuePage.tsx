import { useCallback, useMemo, useState } from 'react'
import { formatApiError, mediaUrl } from '../api/client'
import { listAssignedEvents, type AssignedEventEntry } from '../api/events'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid } from '../components/EventCard'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { PageHeader } from '../components/PageHeader'
import { Tabs } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import { EVENTS_INBOX_PATH, eventPath } from '../routes'
import { eventStatusTab, EVENT_STATUS_TABS, type EventStatusTabKey } from '../shared/eventStatus'
import { formatDateTime, formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

const BACK_TO_INBOX = { from: EVENTS_INBOX_PATH, fromLabel: 'Events inbox' }

type SortKey = 'submitted_at' | 'starts_at'

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'submitted_at', label: 'Submission date' },
  { key: 'starts_at', label: 'Proposed event date' },
]

function byField(field: SortKey) {
  return (a: AssignedEventEntry, b: AssignedEventEntry) =>
    (a[field] ?? '').localeCompare(b[field] ?? '')
}

function matchesSearch(entry: AssignedEventEntry, search: string): boolean {
  const term = search.trim().toLowerCase()
  if (term === '') return true
  return (
    entry.name.toLowerCase().includes(term) || entry.organiser_name.toLowerCase().includes(term)
  )
}

function loadFirstPage() {
  return listAssignedEvents(0)
}

/** AC9-style: a later page can repeat an entry the list already shows, if one was edited
 * meanwhile - same pattern as MyEventsPage's "Load more". */
function withoutRepeats(
  shown: AssignedEventEntry[],
  more: AssignedEventEntry[],
): AssignedEventEntry[] {
  const shownIds = new Set(shown.map((entry) => entry.id))
  return [...shown, ...more.filter((entry) => !shownIds.has(entry.id))]
}

/**
 * Story 4.1 - the coordinator review queue.
 * AC1: requests awaiting a decision, assigned to the signed-in coordinator.
 * AC2: each entry shows the event name, organiser, proposed date and submission date.
 * AC3: the queue can be ordered by submission date or proposed event date.
 * AC4: drafts and already-decided requests never appear — the backend query excludes them.
 *
 * Story 6.1: the tab strip is now the shared All-plus-seven-visible-statuses set, backed by
 * `/events/assigned-to-me` (every event assigned to this coordinator, any status) rather than
 * the old review-only `/events/review-queue`. "Load more" mirrors MyEventsPage's pattern - the
 * backend pages the same way `/mine` does.
 */
export function ReviewQueuePage() {
  const { data: list, error, isLoading, setData: setList } = useLoaded(loadFirstPage)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null)
  const [sort, setSort] = useState<SortKey>('submitted_at')
  const [search, setSearch] = useState('')
  const [tab, setTab] = useState<EventStatusTabKey>('ALL')

  const items = useMemo(() => list?.items ?? [], [list])
  const tabs = useMemo(
    () =>
      EVENT_STATUS_TABS.map((item) => ({
        key: item.key,
        label: `${item.label} (${item.key === 'ALL' ? items.length : items.filter((entry) => eventStatusTab(entry.status) === item.key).length})`,
      })),
    [items],
  )
  const shownEntries = useMemo(() => {
    const byTab =
      tab === 'ALL' ? items : items.filter((entry) => eventStatusTab(entry.status) === tab)
    return byTab.filter((entry) => matchesSearch(entry, search)).sort(byField(sort))
  }, [items, tab, search, sort])

  const handleLoadMore = useCallback(async () => {
    if (list === null) return
    setIsLoadingMore(true)
    setLoadMoreError(null)
    try {
      const next = await listAssignedEvents(list.items.length)
      setList((current) =>
        current === null
          ? current
          : { items: withoutRepeats(current.items, next.items), total: next.total },
      )
    } catch (err) {
      setLoadMoreError(formatApiError(err))
    } finally {
      setIsLoadingMore(false)
    }
  }, [list, setList])

  function clearSearch() {
    setSearch('')
  }

  return (
    <div className="page page-wide">
      <p className="eyebrow">Events</p>
      <PageHeader
        title="Events inbox"
        subtitle="Every event assigned to you, and where it stands."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading your events…" />}

      {list !== null && (
        <div className="stack">
          <Tabs tabs={tabs} activeKey={tab} onChange={setTab} />

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
              <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
                {SORT_OPTIONS.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {items.length === 0 && <EmptyState>No events are assigned to you yet.</EmptyState>}

          {items.length > 0 && shownEntries.length === 0 && (
            <EmptyState>
              No requests match your search.{' '}
              <button type="button" className="link" onClick={clearSearch}>
                Clear search
              </button>
            </EmptyState>
          )}

          {shownEntries.length > 0 && (
            <EventCardGrid>
              {shownEntries.map((entry) => (
                <EventCard
                  key={entry.id}
                  title={entry.name}
                  imageUrl={mediaUrl(entry.cover_image_url)}
                  to={eventPath(entry.id)}
                  state={BACK_TO_INBOX}
                  details={[
                    <EventStatusBadge key="status" status={entry.status} />,
                    formatSchedule(entry.starts_at, entry.ends_at),
                    `Requested by ${entry.organiser_name}`,
                    entry.submitted_at
                      ? `Submitted ${formatDateTime(entry.submitted_at)}`
                      : 'Submission date not recorded',
                  ]}
                />
              ))}
            </EventCardGrid>
          )}

          {loadMoreError && (
            <p role="alert" className="error">
              {loadMoreError}
            </p>
          )}
          {list.items.length < list.total && (
            <div className="load-more">
              <p className="small muted">
                Showing {list.items.length} of {list.total} events
              </p>
              <button
                type="button"
                className="secondary"
                disabled={isLoadingMore}
                onClick={handleLoadMore}
              >
                Load more
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
