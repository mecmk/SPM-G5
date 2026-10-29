import { useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { ApiError, formatApiError, mediaUrl } from '../api/client'
import {
  fetchAttendeeEvent,
  fetchProfile,
  registerForEvent,
  withdrawRegistration,
  type AttendeeDetails,
  type AttendeeEvent,
  type GuestDetails,
  type Registration,
  type RegistrationEvent,
} from '../api/registrations'
import type { ErrorCode } from '../errors/registry'
import { useAuth } from '../auth/authContext'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type { EventCardBackState } from '../components/EventCard'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { UPCOMING_EVENTS_PATH } from '../routes'
import { formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { AttendeeDetailsDialog } from './AttendeeDetailsDialog'
import { detailsFrom, withConfirmedDetails } from './attendeeDetails'
import {
  STANDING_BADGES,
  STARTED_NOTE,
  STATE_BADGES,
  UPCOMING_EVENTS_TITLE,
  PLACES_WITH_GUEST,
  describeActiveRegistration,
  describePartyByName,
  describePlacesLeft,
  describeRegistrationTimes,
  describeVenue,
  describeVenues,
  type RegistrationBadge,
} from './registrationLabels'

/** Story 18.4: the refusals that are about the event - not open any more (18.1 AC4/AC10), or not
 *  yet open, closed, full or already registered (AC2/AC6) - which the page shows where it says
 *  where registration stands. Anything else is about the details, and stays in the dialog. */
const EVENT_REFUSAL_CODES: ErrorCode[] = ['REGISTRATION_EVENT_NOT_OPEN', 'REGISTRATION_REFUSED']

/** Why a registration was not taken, and whether that was about the event rather than the
 *  details sent with it. */
interface RegistrationProblem {
  message: string
  isAboutTheEvent: boolean
}

/** What loading the page found: the event, or - story 18.1 AC10 - why there is none for this
 *  attendee, in the server's words: it is not listed, and they never registered for it. */
interface LoadedEvent {
  event: AttendeeEvent | null
  reason: string | null
}

/** Story 18.1 AC1 / 18.2 AC1: a loader for the event that is not the one before it, so the page
 *  loads the event again after a registration or a withdrawal. A 404 is the server saying there
 *  is no page (18.1 AC10/AC11): an answer, not a failure to load, so the event is no longer shown.
 *  Any other failure is one, and the page keeps showing the event as it last had it. */
function eventLoader(eventId: string): () => Promise<LoadedEvent> {
  return async () => {
    try {
      return { event: await fetchAttendeeEvent(eventId), reason: null }
    } catch (err) {
      if (err instanceof ApiError && err.code === 'REGISTRATION_EVENT_NOT_OPEN') {
        return { event: null, reason: formatApiError(err) }
      }
      throw err
    }
  }
}

/** Story 18.1 AC1: the event as the server now has it for this attendee, until it is loaded
 *  again: Registered, a place fewer - two with a guest (18.4 AC13) - and the registration just
 *  made - which, the event being listed and so not started, can be withdrawn (18.2 AC3). */
function markRegistered(event: AttendeeEvent, made: Registration): AttendeeEvent {
  const placesTaken = made.guest_name === null ? 1 : PLACES_WITH_GUEST
  const listing: RegistrationEvent | null =
    event.listing === null
      ? null
      : {
          ...event.listing,
          state: 'REGISTERED',
          registered_at: made.registered_at,
          places_left: event.listing.places_left - placesTaken,
        }
  return {
    ...event,
    listing,
    registration: {
      id: made.id,
      event_id: event.id,
      event_name: event.name,
      cover_image_url: event.cover_image_url,
      starts_at: event.starts_at,
      ends_at: event.ends_at,
      status: 'REGISTERED',
      registered_at: made.registered_at,
      withdrawn_at: null,
      can_withdraw: true,
      guest_name: made.guest_name,
    },
  }
}

/** Story 18.2 AC3/AC6-AC8: whether a refusal is the server's final word on this registration -
 *  its event started or was cancelled, it was already withdrawn, or it is gone - so trying
 *  again cannot succeed. A server that could not be reached may answer next time. */
function isFinalRefusal(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.code === 'WITHDRAWAL_REFUSED' || err.code === 'REGISTRATION_NOT_FOUND')
  )
}

/**
 * Story 18.1 AC9 (fix f18.1.2) - an event's page, as an attendee opens it from its card on
 * Upcoming events or, story 18.2 AC9 (fix f18.2.1), on My registrations: its cover picture (AC8),
 * name, description, date and time and venues; while it is listed, the places left, where
 * registration stands and when it opens and closes; and where the attendee stands, if they
 * registered. A back link returns to the list it was opened from (Upcoming events otherwise).
 *
 * Story 18.1:
 * AC1: the attendee registers here - Register, then confirming their details (story 18.4) - and
 *      the page then shows the event Registered, with when they registered, at once from the
 *      registration's answer and then as the server has it.
 * AC3: Register is disabled while the event is full, closed or not yet open, and not offered while
 *      the attendee is registered.
 * AC6: Register and the dialog's Confirm and register are disabled while a registration is sent,
 *      so a double-click sends one.
 * AC10: an event that is neither listed nor registered for has no page: the server's 404 says it
 *      is not open for registration, as for an unknown event.
 * AC11: a refused registration says why here, and the event is loaded again, so the page shows
 *      where it now stands - or, once it has no page, that it is not open (AC10).
 * AC5: attendees only - App.tsx guards the route, and the backend refuses everyone else.
 *
 * Story 18.2:
 * AC1/AC9: the attendee withdraws here, after confirming; the page then shows where registration
 *      stands, as for an attendee who never registered - Open, say - and offers Register again
 *      while the event is open (AC4). One badge at a time, and no history of when they withdrew.
 * AC3: once the event has started there is no Withdraw, and the page says why.
 * AC10: an event they registered for opens even once it is no longer listed, with no places left
 *      or Register, and only the venues it still has booked.
 * AC11: a refused withdrawal says why in the dialog - which then offers only Close if it is final
 *      (AC3/AC6-AC8) - and the event is loaded again, so the page shows where they now stand.
 * AC7: the dialog's Withdraw is disabled while its request is in flight, so a double-click sends
 *      one.
 *
 * Story 18.4 AC2/AC3: Register opens "Confirm your details", filled in from the attendee's
 * profile (once it has loaded, so the dialog never opens half filled); confirming registers and
 * saves them. A refusal about the event closes the dialog and shows here; one about the details
 * stays in the dialog, so nothing typed is lost. If the profile cannot be loaded, the dialog opens
 * empty and the details are typed in. AC12-AC14 (fix f18.4.1): the attendee may bring a guest,
 * who takes a place too; once registered, the page names them, and withdrawing gives up both
 * places.
 *
 * Keyed by the event in the address, so moving to another event's page starts afresh.
 */
export function AttendeeEventPage() {
  const { eventId = '' } = useParams()
  return <AttendeeEventView key={eventId} eventId={eventId} />
}

function AttendeeEventView({ eventId }: { eventId: string }) {
  // Story 7.1's back state, set by the card that opened the page.
  const backState = useLocation().state as EventCardBackState | null
  // Replaced by a fresh loader after every registration and withdrawal, so useLoaded loads the
  // event again; it keeps showing the event until the new answer arrives.
  const [loadEvent, setLoadEvent] = useState(() => eventLoader(eventId))
  const { data: loaded, error, isLoading, setData: setLoaded } = useLoaded(loadEvent)
  const event = loaded?.event ?? null
  const registration = event?.registration ?? null
  const [hasImageFailed, setHasImageFailed] = useState(false)
  const [isRegistering, setIsRegistering] = useState(false)
  const [refusal, setRefusal] = useState<string | null>(null)
  const [isConfirmingWithdrawal, setIsConfirmingWithdrawal] = useState(false)
  const [isWithdrawing, setIsWithdrawing] = useState(false)
  const [withdrawalRefusal, setWithdrawalRefusal] = useState<{
    message: string
    isFinal: boolean
  } | null>(null)

  // Story 18.4: the profile the dialog fills in from. Read again after a registration, which
  // saves the details confirmed with it, so the frame's own name (AC1) - and the next dialog, once
  // the attendee withdraws and registers again - shows them as the server stored them.
  const { setFullName } = useAuth()
  const { data: profile, error: profileError, setData: setProfile } = useLoaded(fetchProfile)
  const [profileRefreshError, setProfileRefreshError] = useState<string | null>(null)
  const isProfileLoading = profile === null && profileError === null
  const [isConfirmingDetails, setIsConfirmingDetails] = useState(false)
  const [detailsError, setDetailsError] = useState<string | null>(null)

  function markImageFailed() {
    setHasImageFailed(true)
  }

  function updateEvent(change: (current: AttendeeEvent) => AttendeeEvent) {
    setLoaded((current) =>
      current === null || current.event === null
        ? current
        : { ...current, event: change(current.event) },
    )
  }

  function loadEventAgain() {
    setLoadEvent(() => eventLoader(eventId))
  }

  /** Register for `registering` with the details the attendee confirmed (18.4 AC2/AC3), and the
   *  guest they bring, if any (AC12). Answers why it was refused, or null when it was taken. */
  async function sendRegistration(
    registering: AttendeeEvent,
    details: AttendeeDetails,
    guest: GuestDetails | null,
  ): Promise<RegistrationProblem | null> {
    setIsRegistering(true)
    setRefusal(null)
    try {
      const made = await registerForEvent(registering, details, guest)
      // 18.1 AC1: Registered at once, not only when the reload lands, so Register cannot be
      // pressed again in between.
      updateEvent((current) => markRegistered(current, made))
      return null
    } catch (err) {
      return {
        message: formatApiError(err),
        isAboutTheEvent: err instanceof ApiError && EVENT_REFUSAL_CODES.includes(err.code),
      }
    } finally {
      setIsRegistering(false)
      // 18.1 AC1/AC11: whether it was taken or refused, show where the event now stands.
      loadEventAgain()
    }
  }

  /** 18.4 AC2/AC3: Register opens the details to confirm - filled in from the profile. */
  function handleRegister() {
    setDetailsError(null)
    setIsConfirmingDetails(true)
  }

  function handleCancelDetails() {
    setIsConfirmingDetails(false)
  }

  /** 18.4 AC2/AC3: register with the confirmed details, which saves them to the profile. A
   *  refusal about the event shows on the page (18.1 AC11); one about the details stays in the
   *  dialog, so nothing typed is lost. */
  async function handleConfirmDetails(details: AttendeeDetails, guest: GuestDetails | null) {
    if (event === null) return
    setDetailsError(null)
    const problem = await sendRegistration(event, details, guest)
    if (problem !== null && !problem.isAboutTheEvent) {
      setDetailsError(problem.message)
      return
    }
    setIsConfirmingDetails(false)
    if (problem !== null) {
      setRefusal(problem.message)
      return
    }
    // What was just confirmed is kept at once, so a dialog opened before the profile is read
    // again - or when that read fails - shows it; the read then only corrects it.
    setProfile((current) => (current === null ? current : withConfirmedDetails(current, details)))
    setFullName(details.full_name.trim())
    await refreshProfile()
  }

  /** 18.4 AC2/AC3: read the profile the registration just saved, for the frame's name and any
   *  later dialog. The registration itself is already taken, so a failure here only says so. */
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

  /** 18.2 AC1: Withdraw asks first. */
  function handleWithdraw() {
    setRefusal(null)
    setWithdrawalRefusal(null)
    setIsConfirmingWithdrawal(true)
  }

  function handleCancelWithdrawal() {
    setIsConfirmingWithdrawal(false)
  }

  /** 18.2 AC1/AC11: withdraw the attendee's registration. Whether it went through, was refused or
   *  never reached the server, the event is loaded again, so the page shows where they now stand;
   *  a refusal stays in the dialog, which offers only Close once it is final. */
  async function handleConfirmWithdrawal() {
    if (registration === null) return
    setIsWithdrawing(true)
    setWithdrawalRefusal(null)
    try {
      const withdrawn = await withdrawRegistration(registration)
      updateEvent((current) => ({ ...current, registration: withdrawn }))
      setIsConfirmingWithdrawal(false)
    } catch (err) {
      setWithdrawalRefusal({ message: formatApiError(err), isFinal: isFinalRefusal(err) })
    } finally {
      setIsWithdrawing(false)
      loadEventAgain()
    }
  }

  const venues =
    event === null
      ? []
      : event.listing === null
        ? event.venues.map(describeVenue)
        : describeVenues(event.venues)
  return (
    <div className="page page-wide attendee-event">
      <Link to={backState?.from ?? UPCOMING_EVENTS_PATH} className="back-link">
        ← {backState?.fromLabel ?? UPCOMING_EVENTS_TITLE}
      </Link>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loaded?.reason && (
        <p role="alert" className="error">
          {loaded.reason}
        </p>
      )}
      {isLoading && <LoadingState label="Loading the event…" />}
      {(profileError ?? profileRefreshError) && (
        <p role="alert" className="error">
          {profileError ?? profileRefreshError}
        </p>
      )}

      {event !== null && (
        <>
          <div className="venue-hero">
            {event.cover_image_url !== null && !hasImageFailed ? (
              <img
                className="venue-hero-picture"
                src={mediaUrl(event.cover_image_url) ?? undefined}
                alt=""
                onError={markImageFailed}
              />
            ) : (
              <span aria-hidden="true">
                <Icon name="image" size={36} />
              </span>
            )}
            <div className="venue-hero-overlay">
              <h1>{event.name}</h1>
              <p className="venue-hero-meta">{formatSchedule(event.starts_at, event.ends_at)}</p>
            </div>
          </div>

          <div className="layout-split">
            <div className="stack">
              {event.description !== null && (
                <section className="card stack" aria-labelledby="attendee-event-about-heading">
                  <p className="eyebrow" id="attendee-event-about-heading">
                    About this event
                  </p>
                  <p className="attendee-event-description">{event.description}</p>
                </section>
              )}
              {venues.length > 0 && (
                <section className="card stack" aria-labelledby="attendee-event-venues-heading">
                  <p className="eyebrow" id="attendee-event-venues-heading">
                    Where
                  </p>
                  <ul className="check-list">
                    {venues.map((venue) => (
                      <li key={venue}>{venue}</li>
                    ))}
                  </ul>
                </section>
              )}
            </div>

            <RegistrationPanel
              event={event}
              refusal={refusal}
              isRegisterBusy={isRegistering || isProfileLoading}
              onRegister={handleRegister}
              onWithdraw={handleWithdraw}
            />
          </div>
        </>
      )}

      {isConfirmingDetails && event !== null && (
        <AttendeeDetailsDialog
          initial={detailsFrom(profile)}
          eventName={event.name}
          placesLeft={event.listing?.places_left ?? 0}
          isFirstTime={profile === null || !profile.has_confirmed_details}
          isBusy={isRegistering}
          error={detailsError}
          onConfirm={handleConfirmDetails}
          onCancel={handleCancelDetails}
        />
      )}

      {isConfirmingWithdrawal && registration !== null && (
        <ConfirmDialog
          title={`Withdraw from ${registration.event_name}?`}
          confirmLabel="Withdraw"
          isBusy={isWithdrawing}
          error={withdrawalRefusal?.message ?? null}
          canConfirm={withdrawalRefusal === null || !withdrawalRefusal.isFinal}
          cancelLabel={withdrawalRefusal?.isFinal ? 'Close' : undefined}
          onConfirm={handleConfirmWithdrawal}
          onCancel={handleCancelWithdrawal}
        >
          <p>
            {registration.guest_name === null
              ? 'Your place will be given up for someone else.'
              : `Your place and ${registration.guest_name}'s will be given up for someone else.`}{' '}
            If registration has closed or the event fills up, you may not be able to register again.
          </p>
        </ConfirmDialog>
      )}
    </div>
  )
}

/** Story 18.2 AC9: the one badge the page shows. While the event is listed, where registration
 *  stands for the attendee (18.1 AC1) - Registered, or, never registered or withdrawn, Open, Full
 *  and so on, as for anyone else. Once it is not, where they stand (AC10) - Registered, Withdrawn
 *  or Event cancelled. The page of an unlisted event is only ever one they registered for. */
function panelBadge({ listing, registration }: AttendeeEvent): RegistrationBadge | null {
  if (listing !== null) return STATE_BADGES[listing.state]
  return registration === null ? null : STANDING_BADGES[registration.status]
}

/** Story 18.2 AC3/AC9: when the attendee registered, while they still are, and why there is no
 *  Withdraw once the event has started; otherwise, story 18.1 AC9, while the event is listed,
 *  when registration opens and closes. No history of when they withdrew. */
function panelTimes({ listing, registration }: AttendeeEvent): string[] {
  if (registration?.status === 'REGISTERED') {
    const lines = describeActiveRegistration(registration)
    if (!registration.can_withdraw) lines.push(STARTED_NOTE)
    return lines
  }
  return listing === null ? [] : describeRegistrationTimes(listing)
}

interface RegistrationPanelProps {
  event: AttendeeEvent
  /** Why the latest attempt to register was refused, null when it was not. */
  refusal: string | null
  /** A registration is being sent - or, story 18.4, the details it confirms are still loading. */
  isRegisterBusy: boolean
  onRegister: () => void
  onWithdraw: () => void
}

/**
 * Story 18.1 AC1/AC3/AC9/AC11 and 18.2 AC3/AC9/AC10: where the attendee and registration stand,
 * the places left while the event is listed, the times that go with them, why the latest attempt
 * to register was refused, and the one thing the attendee can do: Register - enabled only while
 * the event is open, offered only while it is listed and they are not registered - or Withdraw,
 * offered only while the server says their registration can be withdrawn. Register is the brand
 * colour, as the dialog's Confirm and register is, so it stands apart from the page's other
 * buttons; Withdraw is red, as giving up a place is, like its confirmation's button.
 */
function RegistrationPanel({
  event,
  refusal,
  isRegisterBusy,
  onRegister,
  onWithdraw,
}: RegistrationPanelProps) {
  const { listing, registration } = event
  const badge = panelBadge(event)
  return (
    <section
      className="card stack attendee-event-registration"
      aria-labelledby="attendee-event-registration-heading"
    >
      <p className="eyebrow" id="attendee-event-registration-heading">
        Registration
      </p>
      {badge !== null && (
        <div className="cluster">
          <StatusBadge status={badge.status} label={badge.label} />
        </div>
      )}
      {listing !== null && <p>{describePlacesLeft(listing.places_left)}</p>}
      {registration !== null &&
        describePartyByName(registration).map((line) => <p key={line}>{line}</p>)}
      {panelTimes(event).map((line) => (
        <p key={line} className="muted small">
          {line}
        </p>
      ))}
      {refusal !== null && (
        <p role="alert" className="error">
          {refusal}
        </p>
      )}
      {listing !== null && listing.state !== 'REGISTERED' && (
        <button
          type="button"
          className="button-block brand"
          aria-label={`Register for ${event.name}`}
          disabled={listing.state !== 'OPEN' || isRegisterBusy}
          onClick={onRegister}
        >
          Register
        </button>
      )}
      {registration?.can_withdraw && (
        <button
          type="button"
          className="button-block danger"
          aria-label={`Withdraw from ${event.name}`}
          onClick={onWithdraw}
        >
          Withdraw
        </button>
      )}
    </section>
  )
}
