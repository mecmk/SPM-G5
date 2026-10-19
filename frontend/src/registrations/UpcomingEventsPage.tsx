import { useCallback, useMemo, useState } from 'react'
import { formatApiError } from '../api/client'
import {
  listRegistrationEvents,
  registerForEvent,
  REGISTRATION_EVENTS_MAX_LIMIT,
  REGISTRATION_EVENTS_PAGE_SIZE,
  type RegistrationEvent,
  type RegistrationState,
} from '../api/registrations'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { FULL_LABEL } from '../components/RegistrationCount'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { formatDateTime, formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import {
  REGISTERED_BADGE,
  describeRegisteredAt,
  type RegistrationBadge,
} from './registrationLabels'

/** Story 18.1 AC1/AC3: each state's label, and the badge colour it takes (App.css). */
const STATE_BADGES: Record<RegistrationState, RegistrationBadge> = {
  OPEN: { status: 'success', label: 'Open' },
  NOT_YET_OPEN: { status: 'info', label: 'Not yet open' },
  FULL: { status: 'warning', label: FULL_LABEL },
  CLOSED: { status: 'neutral', label: 'Closed' },
  REGISTERED: REGISTERED_BADGE,
}

/** Story 18.1 AC1: what a Confirmed event with no approved venue booking shows. */
const NO_VENUE_YET = 'Venue to be confirmed'

/** Story 18.1 AC1: the places left are shown (decided 14 Oct 2026). */
function describePlacesLeft(placesLeft: number): string {
  return `${placesLeft} ${placesLeft === 1 ? 'place' : 'places'} left`
}

/**
 * Story 18.1 AC1-AC3: where registration stands in time for this attendee - when they registered
 * (AC1's confirmation, kept after a reload), when it opens, or when it closes or closed.
 */
function describeRegistration(event: RegistrationEvent): string {
  if (event.registered_at !== null) {
    return describeRegisteredAt(event.registered_at)
  }
  if (event.registration_opens_at !== null && event.state === 'NOT_YET_OPEN') {
    return `Registration opens ${formatDateTime(event.registration_opens_at)}`
  }
  if (event.state === 'CLOSED') {
    return `Registration closed ${formatDateTime(event.registration_closes_at)}`
  }
  return `Registration closes ${formatDateTime(event.registration_closes_at)}`
}

/** Story 18.1 AC1: each booked venue's name and location. */
function describeVenues(event: RegistrationEvent): string[] {
  return event.venues.length === 0
    ? [NO_VENUE_YET]
    : event.venues.map((venue) => `${venue.name}, ${venue.location}`)
}

/**
 * AC1: the next page is asked for by how many events are shown. An event added ahead of them
 * meanwhile pushes one already shown onto it, and that one is shown once. (One that dropped off
 * ahead of them pushes the next one back a page instead, so it is missed until the list is next
 * loaded whole, after a registration or when the page is opened again.)
 */
function withoutRepeats(
  shown: RegistrationEvent[],
  more: RegistrationEvent[],
): RegistrationEvent[] {
  const shownIds = new Set(shown.map((event) => event.id))
  return [...shown, ...more.filter((event) => !shownIds.has(event.id))]
}

/** AC1: the event as the server now has it for this attendee, until the list is loaded again. */
function markRegistered(event: RegistrationEvent, registeredAt: string): RegistrationEvent {
  return {
    ...event,
    state: 'REGISTERED',
    registered_at: registeredAt,
    places_left: event.places_left - 1,
  }
}

interface UpcomingEventCardProps {
  event: RegistrationEvent
  /** A registration is being sent, for this event or another. */
  isRegistering: boolean
  /** Why the latest attempt to register was refused, null when it was not. */
  refusal: string | null
  onRegister: (event: RegistrationEvent) => void
}

/**
 * Story 18.1 AC1/AC3: one event, with Register as the card's own control (story 5.4's card
 * action: beside the details, below them on a phone), enabled only while the event is open (AC3:
 * disabled when full, closed or not yet open; not offered once registered). AC6: disabled while
 * any registration is being sent, so a double-click sends one, and a second card's answer cannot
 * enable the first card's Register while its own is still on the way.
 */
function UpcomingEventCard({ event, isRegistering, refusal, onRegister }: UpcomingEventCardProps) {
  function handleRegister() {
    onRegister(event)
  }

  const badge = STATE_BADGES[event.state]
  const details = [
    <StatusBadge key="state" status={badge.status} label={badge.label} />,
    formatSchedule(event.starts_at, event.ends_at),
    ...describeVenues(event),
    ...(event.description === null ? [] : [event.description]),
    describePlacesLeft(event.places_left),
    describeRegistration(event),
  ]
  if (refusal !== null) {
    details.push(
      <p key="refusal" role="alert" className="error">
        {refusal}
      </p>,
    )
  }
  const register =
    event.state === 'REGISTERED' ? undefined : (
      <button
        type="button"
        className="button-sm"
        aria-label={`Register for ${event.name}`}
        disabled={event.state !== 'OPEN' || isRegistering}
        onClick={handleRegister}
      >
        Register
      </button>
    )
  return <EventCard title={event.name} imageUrl={null} details={details} action={register} />
}

/** The size of the list to load again after a registration: what is shown, so a refreshed list
 *  keeps the pages already loaded - up to REGISTRATION_EVENTS_MAX_LIMIT, the most the API sends
 *  at once, past which it is cut back to that many. */
function refreshLimit(shownCount: number): number {
  return Math.min(
    Math.max(shownCount, REGISTRATION_EVENTS_PAGE_SIZE),
    REGISTRATION_EVENTS_MAX_LIMIT,
  )
}

/**
 * Story 18.1 - browse and register for an event.
 * AC1: the Confirmed, Public events taking registrations that have not started, soonest first, a
 *      page at a time ("Load more"), each with its date and time, venues, description, places
 *      left and state. Registering shows a confirmation - the notification centre's "Registered",
 *      and the card's own "You registered on <time>" - and the event then shows as Registered.
 * AC3: full, closed and not-yet-open events stay listed with Register disabled.
 * AC5: attendees only - App.tsx guards the route, and the backend refuses everyone else.
 * AC6: a refused registration (full, closed, already registered) shows the backend's reason on
 *      the card, and the list is loaded again so every card shows where it now stands.
 * AC4: an event that stopped taking registrations is gone from the reloaded list, so its refusal
 *      is shown above the list instead, naming the event.
 */
export function UpcomingEventsPage() {
  // What to load: the first page, then everything shown again after each registration. A new
  // object each time, so the list loads again even when its size is unchanged.
  const [shown, setShown] = useState({ limit: REGISTRATION_EVENTS_PAGE_SIZE })
  const loadShown = useCallback(() => listRegistrationEvents(0, shown.limit), [shown])
  const { data: list, error, isLoading, setData: setList } = useLoaded(loadShown)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null)
  const [registeringId, setRegisteringId] = useState<string | null>(null)
  const [refusal, setRefusal] = useState<{
    eventId: string
    eventName: string
    message: string
  } | null>(null)

  const items = useMemo(() => list?.items ?? [], [list])
  const isRefusalOnItsCard = refusal !== null && items.some((event) => event.id === refusal.eventId)

  const handleLoadMore = useCallback(async () => {
    setIsLoadingMore(true)
    setLoadMoreError(null)
    try {
      const next = await listRegistrationEvents(items.length)
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
  }, [items, setList])

  const handleRegister = useCallback(
    async (event: RegistrationEvent) => {
      setRegisteringId(event.id)
      setRefusal(null)
      // The list is loaded again below, so an earlier page's failure no longer applies.
      setLoadMoreError(null)
      try {
        const registration = await registerForEvent(event)
        // AC1: Registered at once, not only when the reload lands, so Register cannot be pressed
        // again in between.
        setList((current) =>
          current === null
            ? current
            : {
                ...current,
                items: current.items.map((item) =>
                  item.id === event.id ? markRegistered(item, registration.registered_at) : item,
                ),
              },
        )
      } catch (err) {
        setRefusal({ eventId: event.id, eventName: event.name, message: formatApiError(err) })
      } finally {
        setRegisteringId(null)
        setShown({ limit: refreshLimit(items.length) })
      }
    },
    [items, setList],
  )

  return (
    <div className="page page-wide upcoming-events">
      <p className="eyebrow">Attend</p>
      <PageHeader
        title="Upcoming events"
        subtitle="Confirmed events you can register for, soonest first."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading upcoming events…" />}
      {refusal !== null && !isRefusalOnItsCard && (
        <p role="alert" className="error">
          {refusal.eventName}: {refusal.message}
        </p>
      )}

      {list !== null && list.items.length === 0 && (
        <EmptyState>No events are open for registration right now.</EmptyState>
      )}

      {list !== null && list.items.length > 0 && (
        <>
          <EventCardGrid>
            {list.items.map((event) => (
              <UpcomingEventCard
                key={event.id}
                event={event}
                isRegistering={registeringId !== null}
                refusal={refusal?.eventId === event.id ? refusal.message : null}
                onRegister={handleRegister}
              />
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
