import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError, formatApiError, mediaUrl } from '../api/client'
import {
  fetchProfile,
  fetchRegistrationEvent,
  MAX_GUESTS,
  registerForEvent,
  type AttendeeDetails,
  type GuestInput,
  type Registration,
  type RegistrationEvent,
} from '../api/registrations'
import type { ErrorCode } from '../errors/registry'
import { useAuth } from '../auth/authContext'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { UPCOMING_EVENTS_PATH } from '../routes'
import { formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { AttendeeDetailsDialog } from './AttendeeDetailsDialog'
import { detailsFrom, withConfirmedDetails } from './attendeeDetails'
import {
  STATE_BADGES,
  UPCOMING_EVENTS_TITLE,
  describePlacesLeft,
  describeRegistrationTimes,
  describeVenues,
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
  /** A 409: the event is open, but this registration was not taken - not yet open, closed, full,
   *  already registered, or (18.5 AC2) a group that does not fit. */
  isRefused: boolean
}

/** Story 18.1 AC1: a loader for the event that is not the one before it, so the page loads the
 *  event again after a registration. */
function eventLoader(eventId: string): () => Promise<RegistrationEvent> {
  return () => fetchRegistrationEvent(eventId)
}

/** Story 18.5 AC2/AC6: how many guests a new registration may bring - one per place left after
 *  the attendee's own, but never more than MAX_GUESTS. */
function guestLimit(event: RegistrationEvent): number {
  return Math.min(MAX_GUESTS, Math.max(event.places_left - 1, 0))
}

/** Story 18.1 AC1: the event as the server now has it for this attendee, until it is loaded
 *  again. Story 18.5 AC2: the attendee and each of their guests took a place. */
function markRegistered(event: RegistrationEvent, registration: Registration): RegistrationEvent {
  return {
    ...event,
    state: 'REGISTERED',
    registered_at: registration.registered_at,
    places_left: event.places_left - 1 - registration.guests.length,
  }
}

/**
 * Story 18.1 AC9 (fix f18.1.2) - an event's page, as an attendee opens it from its card on
 * Upcoming events: its cover picture (AC8), name, description, date and time, each booked venue,
 * the places left, where registration stands and when it opens and closes. A back link returns to
 * Upcoming events.
 * AC1: the attendee registers here - Register, then confirming their details (story 18.4) - and
 *      the page then shows the event Registered, with when they registered, at once from the
 *      registration's answer and then as the server has it.
 * AC3: Register is disabled while the event is full, closed or not yet open, and not offered once
 *      the attendee is registered.
 * AC6: Register and the dialog's Confirm and register are disabled while a registration is sent,
 *      so a double-click sends one.
 * AC10: an event that is not listed has no page: the server's 404 says it is not open for
 *      registration, as for an unknown event.
 * AC11: a refused registration says why here, and the event is loaded again, so the page shows
 *      where it now stands - or, once it is no longer listed, that it is not open (AC10).
 * AC5: attendees only - App.tsx guards the route, and the backend refuses everyone else.
 *
 * Story 18.4 AC2/AC3: Register opens "Confirm your details", filled in from the attendee's
 * profile (once it has loaded, so the dialog never opens half filled); confirming registers and
 * saves them. A refusal about the event closes the dialog and shows here; one about the details
 * stays in the dialog, so nothing typed is lost. If the profile cannot be loaded, the dialog opens
 * empty and the details are typed in. Story 18.5 AC1/AC2: the dialog also takes the attendee's
 * guests, up to one per place left after their own; a group that no longer fits is refused in
 * the dialog, where fewer guests can be sent.
 *
 * Keyed by the event in the address, so moving to another event's page starts afresh.
 */
export function AttendeeEventPage() {
  const { eventId = '' } = useParams()
  return <AttendeeEvent key={eventId} eventId={eventId} />
}

function AttendeeEvent({ eventId }: { eventId: string }) {
  // Replaced by a fresh loader after every registration, so useLoaded loads the event again; it
  // keeps showing the event until the new answer arrives.
  const [loadEvent, setLoadEvent] = useState(() => eventLoader(eventId))
  const { data: event, error, isLoading, setData: setEvent } = useLoaded(loadEvent)
  const [hasImageFailed, setHasImageFailed] = useState(false)
  const [isRegistering, setIsRegistering] = useState(false)
  const [refusal, setRefusal] = useState<string | null>(null)

  // Story 18.4: the profile the dialog fills in from. Read again after a registration, which
  // saves the details confirmed with it, so the frame's own name (AC1) - and the next dialog -
  // shows them as the server stored them.
  const { setFullName } = useAuth()
  const { data: profile, error: profileError, setData: setProfile } = useLoaded(fetchProfile)
  const [profileRefreshError, setProfileRefreshError] = useState<string | null>(null)
  const isProfileLoading = profile === null && profileError === null
  const [isConfirming, setIsConfirming] = useState(false)
  const [detailsError, setDetailsError] = useState<string | null>(null)

  function markImageFailed() {
    setHasImageFailed(true)
  }

  /** Register for `registering` with the details the attendee confirmed (18.4 AC2/AC3). Answers
   *  why it was refused, or null when it was taken. */
  async function sendRegistration(
    registering: RegistrationEvent,
    details: AttendeeDetails,
    guests: GuestInput[],
  ): Promise<RegistrationProblem | null> {
    setIsRegistering(true)
    setRefusal(null)
    try {
      const registration = await registerForEvent(registering, details, guests)
      // AC1: Registered at once, not only when the reload lands, so Register cannot be pressed
      // again in between.
      setEvent((current) => (current === null ? current : markRegistered(current, registration)))
      return null
    } catch (err) {
      return {
        message: formatApiError(err),
        isAboutTheEvent: err instanceof ApiError && EVENT_REFUSAL_CODES.includes(err.code),
        isRefused: err instanceof ApiError && err.code === 'REGISTRATION_REFUSED',
      }
    } finally {
      setIsRegistering(false)
      // AC1/AC11: whether it was taken or refused, show where the event now stands.
      setLoadEvent(() => eventLoader(eventId))
    }
  }

  /** 18.4 AC2/AC3: Register opens the details to confirm - filled in from the profile. */
  function handleRegister() {
    setDetailsError(null)
    setIsConfirming(true)
  }

  function handleCancelDetails() {
    setIsConfirming(false)
  }

  /** 18.4 AC2/AC3: register with the confirmed details, which saves them to the profile - and,
   *  18.5 AC1, with the guests added in the dialog. A refusal about the event shows on the page
   *  (18.1 AC11); one about the details stays in the dialog, so nothing typed is lost. 18.5 AC2:
   *  so does a 409 for a registration with guests - a group that no longer fits among them -
   *  since the way out, fewer guests or none, is in the dialog. An event no longer open (404)
   *  still closes it. The event is read again either way, so the guest limit catches up. */
  async function handleConfirmDetails(details: AttendeeDetails, guests: GuestInput[]) {
    if (event === null) return
    setDetailsError(null)
    const problem = await sendRegistration(event, details, guests)
    if (
      problem !== null &&
      (!problem.isAboutTheEvent || (problem.isRefused && guests.length > 0))
    ) {
      setDetailsError(problem.message)
      return
    }
    setIsConfirming(false)
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

  return (
    <div className="page page-wide attendee-event">
      <Link to={UPCOMING_EVENTS_PATH} className="back-link">
        ← {UPCOMING_EVENTS_TITLE}
      </Link>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading the event…" />}
      {(profileError ?? profileRefreshError) && (
        <p role="alert" className="error">
          {profileError ?? profileRefreshError}
        </p>
      )}

      {/* AC10/AC11: once the event cannot be loaded - it is no longer listed - only why is shown. */}
      {event !== null && error === null && (
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
              <section className="card stack" aria-labelledby="attendee-event-venues-heading">
                <p className="eyebrow" id="attendee-event-venues-heading">
                  Where
                </p>
                <ul className="check-list">
                  {describeVenues(event).map((venue) => (
                    <li key={venue}>{venue}</li>
                  ))}
                </ul>
              </section>
            </div>

            <RegistrationPanel
              event={event}
              refusal={refusal}
              isBusy={isRegistering || isProfileLoading}
              onRegister={handleRegister}
            />
          </div>
        </>
      )}

      {isConfirming && event !== null && (
        <AttendeeDetailsDialog
          initial={detailsFrom(profile)}
          eventName={event.name}
          maxGuests={guestLimit(event)}
          isFirstTime={profile === null || !profile.has_confirmed_details}
          isBusy={isRegistering}
          error={detailsError}
          onConfirm={handleConfirmDetails}
          onCancel={handleCancelDetails}
        />
      )}
    </div>
  )
}

interface RegistrationPanelProps {
  event: RegistrationEvent
  /** Why the latest attempt to register was refused, null when it was not. */
  refusal: string | null
  /** A registration is being sent - or, story 18.4, the details it confirms are still loading. */
  isBusy: boolean
  onRegister: () => void
}

/** Story 18.1 AC1/AC3/AC9/AC11: where registration stands, the places left, when it opens and
 *  closes (or when the attendee registered), why the latest attempt was refused, and Register -
 *  enabled only while the event is open, and not offered once the attendee is registered.
 *  Register is the brand colour, as the dialog's Confirm and register is, so it stands apart
 *  from the page's other buttons. */
function RegistrationPanel({ event, refusal, isBusy, onRegister }: RegistrationPanelProps) {
  const badge = STATE_BADGES[event.state]
  return (
    <section
      className="card stack attendee-event-registration"
      aria-labelledby="attendee-event-registration-heading"
    >
      <p className="eyebrow" id="attendee-event-registration-heading">
        Registration
      </p>
      <div className="cluster">
        <StatusBadge status={badge.status} label={badge.label} />
      </div>
      <p>{describePlacesLeft(event.places_left)}</p>
      {describeRegistrationTimes(event).map((line) => (
        <p key={line} className="muted small">
          {line}
        </p>
      ))}
      {refusal !== null && (
        <p role="alert" className="error">
          {refusal}
        </p>
      )}
      {event.state !== 'REGISTERED' && (
        <button
          type="button"
          className="button-block brand"
          aria-label={`Register for ${event.name}`}
          disabled={event.state !== 'OPEN' || isBusy}
          onClick={onRegister}
        >
          Register
        </button>
      )}
    </section>
  )
}
