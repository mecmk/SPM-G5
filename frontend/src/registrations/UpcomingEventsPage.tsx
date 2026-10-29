import { useCallback, useMemo, useState } from 'react'
import { ApiError, formatApiError, mediaUrl } from '../api/client'
import {
  fetchProfile,
  listRegistrationEvents,
  registerForEvent,
  REGISTRATION_EVENTS_MAX_LIMIT,
  REGISTRATION_EVENTS_PAGE_SIZE,
  type AttendeeDetails,
  type GuestInput,
  type Registration,
  type RegistrationEvent,
  type RegistrationState,
} from '../api/registrations'
import type { ErrorCode } from '../errors/registry'
import { useAuth } from '../auth/authContext'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { FULL_LABEL } from '../components/RegistrationCount'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { formatDateTime, formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { AttendeeDetailsDialog } from './AttendeeDetailsDialog'
import { detailsFrom, withConfirmedDetails } from './attendeeDetails'
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

/** AC1: the event as the server now has it for this attendee, until the list is loaded again.
 *  Story 18.5 AC2: the attendee and each of their guests took a place. */
function markRegistered(event: RegistrationEvent, registration: Registration): RegistrationEvent {
  return {
    ...event,
    state: 'REGISTERED',
    registered_at: registration.registered_at,
    places_left: event.places_left - 1 - registration.guests.length,
  }
}

interface UpcomingEventCardProps {
  event: RegistrationEvent
  /** A registration is being sent, for this event or another - or, story 18.4, the attendee's
   *  details it confirms are still loading. */
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
 * enable the first card's Register while its own is still on the way. AC8 (fix f18.1.1): the
 * event's cover picture, from the API when it was uploaded (mediaUrl), or the placeholder. Story
 * 18.4 AC2/AC3: Register opens the attendee's details to confirm; confirming registers.
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
  return (
    <EventCard
      title={event.name}
      imageUrl={mediaUrl(event.cover_image_url)}
      details={details}
      action={register}
    />
  )
}

/** Story 18.4: the refusals that are about the event - not open any more (18.1 AC4), or not
 *  yet open, closed, full or already registered (AC2/AC6) - which 18.1 shows on the event's card
 *  or above the list. Anything else is about the details, and stays in the dialog with them. */
const EVENT_REFUSAL_CODES: ErrorCode[] = ['REGISTRATION_EVENT_NOT_OPEN', 'REGISTRATION_REFUSED']

/** Why a registration was not taken, and whether that was about the event rather than the
 *  details sent with it. */
interface RegistrationProblem {
  message: string
  isAboutTheEvent: boolean
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
 * AC8 (fix f18.1.1): each card shows its event's cover picture, or the placeholder.
 *
 * Story 18.4 - autofill attendee profile details.
 * AC2: Register opens "Confirm your details". An attendee who has never given their details is
 *      asked for them there; nothing is registered until they confirm.
 * AC3: after that the dialog shows the details from their profile, filled in, to confirm before
 *      registering (CL-167); a change made there is saved to My profile with the
 *      registration. Register waits for the profile, so the dialog never opens half filled.
 * A refusal about the event closes the dialog and shows where 18.1 shows it; one about the details
 * stays in the dialog, so nothing typed is lost. If the profile cannot be loaded, the dialog opens
 * empty and the details are typed in.
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

  // Story 18.4: the profile the dialog fills in from. Read again after each registration, which
  // saves the details confirmed with it, so the next dialog - and the frame's own name (AC1) -
  // shows them as the server stored them.
  const { setFullName } = useAuth()
  const { data: profile, error: profileError, setData: setProfile } = useLoaded(fetchProfile)
  const [profileRefreshError, setProfileRefreshError] = useState<string | null>(null)
  const isProfileLoading = profile === null && profileError === null
  const [confirmingFor, setConfirmingFor] = useState<RegistrationEvent | null>(null)
  const [detailsError, setDetailsError] = useState<string | null>(null)

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

  /** Register for `event` with the details the attendee confirmed (18.4 AC2/AC3). Answers why it
   *  was refused, or null when it was taken. */
  const sendRegistration = useCallback(
    async (
      event: RegistrationEvent,
      details: AttendeeDetails,
      guests: GuestInput[],
    ): Promise<RegistrationProblem | null> => {
      setRegisteringId(event.id)
      setRefusal(null)
      // The list is loaded again below, so an earlier page's failure no longer applies.
      setLoadMoreError(null)
      try {
        const registration = await registerForEvent(event, details, guests)
        // AC1: Registered at once, not only when the reload lands, so Register cannot be pressed
        // again in between.
        setList((current) =>
          current === null
            ? current
            : {
                ...current,
                items: current.items.map((item) =>
                  item.id === event.id ? markRegistered(item, registration) : item,
                ),
              },
        )
        return null
      } catch (err) {
        return {
          message: formatApiError(err),
          isAboutTheEvent: err instanceof ApiError && EVENT_REFUSAL_CODES.includes(err.code),
        }
      } finally {
        setRegisteringId(null)
        setShown({ limit: refreshLimit(items.length) })
      }
    },
    [items, setList],
  )

  /** 18.4 AC2/AC3: Register opens the details to confirm - filled in from the profile. */
  function handleRegister(event: RegistrationEvent) {
    setDetailsError(null)
    setConfirmingFor(event)
  }

  function handleCancelDetails() {
    setConfirmingFor(null)
  }

  /** 18.4 AC2/AC3: register with the confirmed details, which saves them to the profile - and,
   *  18.5 AC1, with the guests added in the dialog. A refusal about the event shows where 18.1
   *  shows it (AC4/AC6), a group that does not fit among them (18.5 AC12); one about the details
   *  stays in the dialog, so nothing typed is lost. */
  async function handleConfirmDetails(details: AttendeeDetails, guests: GuestInput[]) {
    if (confirmingFor === null) return
    const event = confirmingFor
    setDetailsError(null)
    const problem = await sendRegistration(event, details, guests)
    if (problem !== null && !problem.isAboutTheEvent) {
      setDetailsError(problem.message)
      return
    }
    setConfirmingFor(null)
    if (problem !== null) {
      setRefusal({ eventId: event.id, eventName: event.name, message: problem.message })
      return
    }
    // What was just confirmed is kept at once, so a Register pressed before the profile is read
    // again - or when that read fails - shows it; the read then only corrects it.
    setProfile((current) => (current === null ? current : withConfirmedDetails(current, details)))
    setFullName(details.full_name.trim())
    await refreshProfile()
  }

  /** 18.4 AC2/AC3: read the profile the registration just saved, for the next dialog and the
   *  frame's name. The registration itself is already taken, so a failure here only says so. */
  async function refreshProfile() {
    try {
      const saved = await fetchProfile()
      setProfile(saved)
      setFullName(saved.full_name)
      setProfileRefreshError(null)
    } catch (err) {
      setProfileRefreshError(formatApiError(err))
    }
  }

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
      {(profileError ?? profileRefreshError) && (
        <p role="alert" className="error">
          {profileError ?? profileRefreshError}
        </p>
      )}
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
                isRegistering={registeringId !== null || isProfileLoading}
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

      {confirmingFor !== null && (
        <AttendeeDetailsDialog
          initial={detailsFrom(profile)}
          eventName={confirmingFor.name}
          isFirstTime={profile === null || !profile.has_confirmed_details}
          isBusy={registeringId !== null}
          error={detailsError}
          onConfirm={handleConfirmDetails}
          onCancel={handleCancelDetails}
        />
      )}
    </div>
  )
}
