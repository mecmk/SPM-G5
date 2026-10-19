import { useCallback, useEffect, useMemo, useState } from 'react'
import { formatApiError, mediaUrl } from '../api/client'
import { listAssignedEvents, type AssignedEventEntry, type AssignedEventList } from '../api/events'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid } from '../components/EventCard'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { PageHeader } from '../components/PageHeader'
import { Tabs, type TabItem } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import { EVENTS_INBOX_PATH, eventPath } from '../routes'
import { replacementRequestedLine, VENUE_UNAVAILABLE_LABEL } from '../shared/bookingStatus'
import { eventStatusTab, EVENT_STATUS_TABS, type EventStatusTabKey } from '../shared/eventStatus'
import { formatDateTime, formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

const BACK_TO_INBOX = { from: EVENTS_INBOX_PATH, fromLabel: 'Events inbox' }

type SortKey = 'submitted_at' | 'starts_at'

/** Story 12.6 AC11: the tab of the events with a booking marked "Venue unavailable", beside the
 *  statuses'. Its count and its list come from the server, so they are right whichever page is
 *  loaded: the status tabs' own are counted in the browser over the pages loaded so far. */
const VENUE_UNAVAILABLE_TAB = 'VENUE_UNAVAILABLE'
type InboxTabKey = EventStatusTabKey | typeof VENUE_UNAVAILABLE_TAB

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
  // Each list has its own Load more, so each keeps its own failure: one list's is not the other's.
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null)
  const [unavailableLoadMoreError, setUnavailableLoadMoreError] = useState<string | null>(null)
  const [sort, setSort] = useState<SortKey>('submitted_at')
  const [search, setSearch] = useState('')
  const [tab, setTab] = useState<InboxTabKey>('ALL')
  // Story 12.6 AC11: the Venue unavailable tab's own list, asked of the server when it opens.
  const [unavailable, setUnavailable] = useState<AssignedEventList | null>(null)
  const [unavailableError, setUnavailableError] = useState<string | null>(null)
  const isUnavailableTab = tab === VENUE_UNAVAILABLE_TAB

  useEffect(() => {
    if (!isUnavailableTab) return undefined
    let cancelled = false
    listAssignedEvents(0, true)
      .then((first) => {
        if (!cancelled) setUnavailable(first)
      })
      .catch((err: unknown) => {
        if (!cancelled) setUnavailableError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [isUnavailableTab])

  /** Story 12.6 AC11: opening the Venue unavailable tab starts its list afresh - an earlier failed
   *  load's alert is not this load's, and the tab shows its loading state until the list answers. */
  function openTab(next: InboxTabKey) {
    // Pressing the tab that is already open changes nothing, so nothing is fetched again.
    if (next === tab) return
    if (next === VENUE_UNAVAILABLE_TAB) {
      setUnavailableError(null)
      setUnavailableLoadMoreError(null)
      setUnavailable(null)
    }
    setTab(next)
  }

  const shownList = isUnavailableTab ? unavailable : list
  const items = useMemo(() => list?.items ?? [], [list])
  const shownItems = useMemo(() => shownList?.items ?? [], [shownList])
  const unavailableCount =
    unavailable?.venue_unavailable_count ?? list?.venue_unavailable_count ?? 0
  const tabs = useMemo<TabItem<InboxTabKey>[]>(
    () => [
      ...EVENT_STATUS_TABS.map((item) => ({
        key: item.key,
        label: `${item.label} (${item.key === 'ALL' ? items.length : items.filter((entry) => eventStatusTab(entry.status) === item.key).length})`,
      })),
      { key: VENUE_UNAVAILABLE_TAB, label: `Venue unavailable (${unavailableCount})` },
    ],
    [items, unavailableCount],
  )
  const shownEntries = useMemo(() => {
    const byTab =
      tab === 'ALL' || tab === VENUE_UNAVAILABLE_TAB
        ? shownItems
        : shownItems.filter((entry) => eventStatusTab(entry.status) === tab)
    return byTab.filter((entry) => matchesSearch(entry, search)).sort(byField(sort))
  }, [shownItems, tab, search, sort])

  const handleLoadMore = useCallback(async () => {
    if (shownList === null) return
    const setError = isUnavailableTab ? setUnavailableLoadMoreError : setLoadMoreError
    setIsLoadingMore(true)
    setError(null)
    try {
      const next = await listAssignedEvents(shownList.items.length, isUnavailableTab)
      const more = (current: AssignedEventList | null) =>
        current === null
          ? current
          : {
              ...current,
              items: withoutRepeats(current.items, next.items),
              total: next.total,
              venue_unavailable_count: next.venue_unavailable_count,
            }
      if (isUnavailableTab) setUnavailable(more)
      else setList(more)
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setIsLoadingMore(false)
    }
  }, [shownList, isUnavailableTab, setList])

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
          <Tabs tabs={tabs} activeKey={tab} onChange={openTab} />

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

          {isUnavailableTab && unavailableError !== null && (
            <p role="alert" className="error">
              {unavailableError}
            </p>
          )}
          {isUnavailableTab && unavailable === null && unavailableError === null && (
            <LoadingState label="Loading events with an unavailable venue…" />
          )}
          {isUnavailableTab && unavailable !== null && unavailable.items.length === 0 && (
            <EmptyState>No event of yours has a booking marked as unavailable.</EmptyState>
          )}
          {!isUnavailableTab && items.length === 0 && (
            <EmptyState>No events are assigned to you yet.</EmptyState>
          )}

          {shownItems.length > 0 && shownEntries.length === 0 && (
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
                    // Story 12.6 AC11: what a marked event needs, or which venue is asked for.
                    ...(entry.pending_replacement_venue_name !== null
                      ? [replacementRequestedLine(entry.pending_replacement_venue_name)]
                      : entry.is_venue_unavailable
                        ? [VENUE_UNAVAILABLE_LABEL]
                        : []),
                  ]}
                />
              ))}
            </EventCardGrid>
          )}

          {(isUnavailableTab ? unavailableLoadMoreError : loadMoreError) && (
            <p role="alert" className="error">
              {isUnavailableTab ? unavailableLoadMoreError : loadMoreError}
            </p>
          )}
          {shownList !== null && shownList.items.length < shownList.total && (
            <div className="load-more">
              <p className="small muted">
                Showing {shownList.items.length} of {shownList.total} events
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
