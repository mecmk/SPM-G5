import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { formatApiError } from '../api/client'
import { listMyEvents, type MyEventEntry } from '../api/events'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid, type EventCardBackState } from '../components/EventCard'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { PageHeader } from '../components/PageHeader'
import { Tabs } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import { EVENT_NEW_PATH, EVENTS_MINE_PATH, eventEditPath, eventPath } from '../routes'
import { eventStatusTab, EVENT_STATUS_TABS, type EventStatusTabKey } from '../shared/eventStatus'
import { formatDateTime, formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

const PROPOSED_DATE_LABEL = 'Proposed date: '
const BACK_TO_MY_EVENTS: EventCardBackState = { from: EVENTS_MINE_PATH, fromLabel: 'My events' }

/**
 * AC1/AC4: always labelled, so a date is never mistaken for something else. A draft is saved with
 * only a name, so the date can be missing, or have a start and no end yet.
 */
function describeProposedDate(entry: MyEventEntry): string {
  if (entry.starts_at === null) return `${PROPOSED_DATE_LABEL}Not set`
  if (entry.ends_at === null) {
    return `${PROPOSED_DATE_LABEL}${formatDateTime(entry.starts_at)} (end not set)`
  }
  return `${PROPOSED_DATE_LABEL}${formatSchedule(entry.starts_at, entry.ends_at)}`
}

/**
 * AC2: a draft is still being written, and story 7.1's details page only reads, so a draft opens
 * in the story 2.1 editor. Every other status - approved, rejected, cancelled, all of them - opens
 * the details page.
 */
function pathToOpen(entry: MyEventEntry): string {
  return entry.status === 'DRAFT' ? eventEditPath(entry.id) : eventPath(entry.id)
}

/** AC9: a later page can repeat a request the list already shows, if one was edited meanwhile. */
function withoutRepeats(shown: MyEventEntry[], more: MyEventEntry[]): MyEventEntry[] {
  const shownIds = new Set(shown.map((entry) => entry.id))
  return [...shown, ...more.filter((entry) => !shownIds.has(entry.id))]
}

function loadFirstPage() {
  return listMyEvents(0)
}

/**
 * Story 2.6 - the organiser's own event requests.
 * AC1: every request the signed-in organiser owns, with name, proposed date and current status.
 * AC2: selecting an entry - anywhere on its card - opens it: a draft in the editor, anything else
 *      on the event details page. Either way the back link returns here.
 * AC3: only the signed-in organiser's requests come back - the backend takes no way to ask for
 *      anyone else's.
 * AC4: drafts are listed, with "Not set" where they have no proposed date.
 * AC5: with no requests, the page says so and offers a way to raise one.
 * AC6: the backend orders the list, most recently updated first; the page keeps that order.
 * AC8: the header offers "New event request".
 * AC9: the backend sends a page at a time; "Load more" adds the next, and says how many are left.
 *
 * Story 6.1: a tab strip (All plus the seven visible statuses) filters the currently-loaded
 * page client-side; "Load more" still fetches the next page of everything, regardless of tab.
 */
export function MyEventsPage() {
  const { data: list, error, isLoading, setData: setList } = useLoaded(loadFirstPage)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null)
  const [tab, setTab] = useState<EventStatusTabKey>('ALL')

  const items = useMemo(() => list?.items ?? [], [list])
  const shownItems = useMemo(
    () => (tab === 'ALL' ? items : items.filter((entry) => eventStatusTab(entry.status) === tab)),
    [items, tab],
  )
  const tabs = useMemo(
    () =>
      EVENT_STATUS_TABS.map((item) => ({
        key: item.key,
        label: `${item.label} (${item.key === 'ALL' ? items.length : items.filter((entry) => eventStatusTab(entry.status) === item.key).length})`,
      })),
    [items],
  )

  const handleLoadMore = useCallback(async () => {
    if (list === null) return
    setIsLoadingMore(true)
    setLoadMoreError(null)
    try {
      const next = await listMyEvents(list.items.length)
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

  return (
    <div className="page page-wide">
      <p className="eyebrow">Events</p>
      <PageHeader
        title="My events"
        subtitle="The requests you have raised, and where each one stands."
        action={
          <Link to={EVENT_NEW_PATH} state={BACK_TO_MY_EVENTS} className="button">
            New event request
          </Link>
        }
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading your event requests…" />}

      {list !== null && list.items.length === 0 && (
        <EmptyState>
          You have not raised any event requests yet.{' '}
          <Link to={EVENT_NEW_PATH} state={BACK_TO_MY_EVENTS}>
            Raise your first request
          </Link>
        </EmptyState>
      )}

      {list !== null && list.items.length > 0 && (
        <>
          <Tabs tabs={tabs} activeKey={tab} onChange={setTab} />

          {shownItems.length === 0 && <EmptyState>No requests in this status.</EmptyState>}

          {shownItems.length > 0 && (
            <EventCardGrid>
              {shownItems.map((entry) => (
                <EventCard
                  key={entry.id}
                  title={entry.name}
                  imageUrl={entry.cover_image_url}
                  to={pathToOpen(entry)}
                  state={BACK_TO_MY_EVENTS}
                  details={[
                    <EventStatusBadge key="status" status={entry.status} />,
                    describeProposedDate(entry),
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
                Showing {list.items.length} of {list.total} requests
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
        </>
      )}
    </div>
  )
}
