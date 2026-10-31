import { useCallback, useState } from 'react'
import { formatApiError, mediaUrl } from '../api/client'
import { listRegistrationEvents, type RegistrationEvent } from '../api/registrations'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { upcomingEventPath } from '../routes'
import { formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import {
  STATE_BADGES,
  UPCOMING_EVENTS_TITLE,
  describePlacesLeft,
  describeRegistration,
  describeVenues,
} from './registrationLabels'

/** AC1: the first page of the list, loaded when the page opens. */
function loadFirstPage() {
  return listRegistrationEvents(0)
}

/**
 * AC1: the next page is asked for by how many events are shown. An event added ahead of them
 * meanwhile pushes one already shown onto it, and that one is shown once. (One that dropped off
 * ahead of them pushes the next one back a page instead, so it is missed until the list is next
 * loaded, when the page is opened again.)
 */
function withoutRepeats(
  shown: RegistrationEvent[],
  more: RegistrationEvent[],
): RegistrationEvent[] {
  const shownIds = new Set(shown.map((event) => event.id))
  return [...shown, ...more.filter((event) => !shownIds.has(event.id))]
}

/**
 * Story 18.1 AC1/AC3: one event's card - its picture, name, where registration stands, date and
 * time, venues, places left, and when registration closes (or opens, or when the attendee
 * registered) - so an attendee can tell before opening it whether it is worth opening. AC8 (fix
 * f18.1.1): the event's cover picture, from the API when it was uploaded (mediaUrl), or the
 * placeholder. AC9 (fix f18.1.2): a click anywhere on it opens the event's page, where the
 * attendee registers; the card itself offers no Register.
 */
function UpcomingEventCard({ event }: { event: RegistrationEvent }) {
  const badge = STATE_BADGES[event.state]
  const details = [
    <StatusBadge key="state" status={badge.status} label={badge.label} />,
    formatSchedule(event.starts_at, event.ends_at),
    ...describeVenues(event),
    describePlacesLeft(event.places_left),
    describeRegistration(event),
  ]
  return (
    <EventCard
      title={event.name}
      imageUrl={mediaUrl(event.cover_image_url)}
      details={details}
      to={upcomingEventPath(event.id)}
    />
  )
}

/**
 * Story 18.1 - browse and register for an event.
 * AC1: the Confirmed, Public events taking registrations that have not started, soonest first, a
 *      page at a time ("Load more"), each with its date and time, venues, places left, state and
 *      when registration closes. Registering is on the event's page (AttendeeEventPage).
 * AC3: full, closed and not-yet-open events stay listed.
 * AC5: attendees only - App.tsx guards the route, and the backend refuses everyone else.
 * AC8 (fix f18.1.1): each card shows its event's cover picture, or the placeholder.
 * AC9 (fix f18.1.2): each card opens its event's page.
 */
export function UpcomingEventsPage() {
  const { data: list, error, isLoading, setData: setList } = useLoaded(loadFirstPage)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null)
  const shownCount = list?.items.length ?? 0

  const handleLoadMore = useCallback(async () => {
    setIsLoadingMore(true)
    setLoadMoreError(null)
    try {
      const next = await listRegistrationEvents(shownCount)
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
  }, [shownCount, setList])

  return (
    <div className="page page-wide upcoming-events">
      <p className="eyebrow">Attend</p>
      <PageHeader
        title={UPCOMING_EVENTS_TITLE}
        subtitle="Confirmed events you can register for, soonest first."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading upcoming events…" />}

      {list !== null && list.items.length === 0 && (
        <EmptyState>No events are open for registration right now.</EmptyState>
      )}

      {list !== null && list.items.length > 0 && (
        <>
          <EventCardGrid>
            {list.items.map((event) => (
              <UpcomingEventCard key={event.id} event={event} />
            ))}
          </EventCardGrid>

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
        </>
      )}
    </div>
  )
}
