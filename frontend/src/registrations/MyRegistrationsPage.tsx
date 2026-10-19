import { useState } from 'react'
import { Link } from 'react-router'
import { ApiError, formatApiError, mediaUrl } from '../api/client'
import {
  listMyRegistrations,
  withdrawRegistration,
  type MyRegistration,
} from '../api/registrations'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { UPCOMING_EVENTS_PATH } from '../routes'
import { formatDateTime, formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { STANDING_BADGES, describeRegisteredAt } from './registrationLabels'

/** Story 18.2 AC3: why an active registration offers no Withdraw - its event has started. */
const STARTED_NOTE = 'This event has started, so it can no longer be withdrawn.'

/** Story 18.2 AC1/AC3: when the attendee registered, when they withdrew if they did, and why an
 *  active registration can no longer be withdrawn. */
function describeRegistration(registration: MyRegistration): string[] {
  const lines = [describeRegisteredAt(registration.registered_at)]
  if (registration.withdrawn_at !== null) {
    lines.push(`You withdrew on ${formatDateTime(registration.withdrawn_at)}`)
  }
  if (registration.status === 'REGISTERED' && !registration.can_withdraw) {
    lines.push(STARTED_NOTE)
  }
  return lines
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

/** Story 18.2 AC3: a loader that is not the one before it, so the list is loaded again. */
function freshListLoader(): () => Promise<MyRegistration[]> {
  return () => listMyRegistrations()
}

interface MyRegistrationCardProps {
  registration: MyRegistration
  onWithdraw: (registration: MyRegistration) => void
}

/**
 * Story 18.2 AC1/AC3/AC8: one registration, with its event's name, date and time and where the
 * attendee stands. Withdraw is the card's own control (story 5.4's card action), offered only
 * while the server says it can be withdrawn: an active registration whose event has not started.
 */
function MyRegistrationCard({ registration, onWithdraw }: MyRegistrationCardProps) {
  function handleWithdraw() {
    onWithdraw(registration)
  }

  const badge = STANDING_BADGES[registration.status]
  const details = [
    <StatusBadge key="status" status={badge.status} label={badge.label} />,
    formatSchedule(registration.starts_at, registration.ends_at),
    ...describeRegistration(registration),
  ]
  const withdraw = registration.can_withdraw ? (
    <button
      type="button"
      className="button-sm secondary"
      aria-label={`Withdraw from ${registration.event_name}`}
      onClick={handleWithdraw}
    >
      Withdraw
    </button>
  ) : undefined
  return (
    <EventCard
      title={registration.event_name}
      imageUrl={mediaUrl(registration.cover_image_url)}
      details={details}
      action={withdraw}
    />
  )
}

/**
 * Story 18.2 - view and withdraw my registrations.
 * AC1: the attendee's registrations, one per event, with its name, date and time, status and when
 *      they registered or withdrew. Withdraw asks first; confirming marks it Withdrawn, with the
 *      notification centre's "Withdrawn" as the confirmation, and its place is free again.
 * AC1/AC3: after every withdrawal, whether it went through, was refused or never reached the
 *      server, the list is loaded again, so every card shows where it now stands and an earlier
 *      failed load's message goes once the new list lands. A refused withdrawal (the event
 *      started meanwhile, or it was already withdrawn or cancelled) shows the backend's reason in
 *      the dialog, which then offers only Close. A registration whose event has started says why
 *      it offers no Withdraw.
 * AC5: attendees only - App.tsx guards the route, and the backend sends only their own.
 * AC7: the dialog's Withdraw is disabled while its request is in flight, so a double-click sends
 *      one.
 */
export function MyRegistrationsPage() {
  // Replaced by a fresh loader after every withdrawal, so useLoaded loads the list again; it keeps
  // showing the cards until the new list arrives, and drops the answer of a load still in flight.
  const [loadRegistrations, setLoadRegistrations] = useState(() => listMyRegistrations)
  const { data: registrations, error, isLoading, setData } = useLoaded(loadRegistrations)
  const [pending, setPending] = useState<MyRegistration | null>(null)
  const [isWithdrawing, setIsWithdrawing] = useState(false)
  const [refusal, setRefusal] = useState<{ message: string; isFinal: boolean } | null>(null)

  function askToWithdraw(registration: MyRegistration) {
    setRefusal(null)
    setPending(registration)
  }

  function cancelWithdraw() {
    setPending(null)
  }

  async function confirmWithdraw() {
    if (pending === null) return
    setIsWithdrawing(true)
    setRefusal(null)
    try {
      const withdrawn = await withdrawRegistration(pending)
      setData((current) =>
        current === null ? current : current.map((r) => (r.id === withdrawn.id ? withdrawn : r)),
      )
      setPending(null)
    } catch (err) {
      setRefusal({ message: formatApiError(err), isFinal: isFinalRefusal(err) })
    } finally {
      setIsWithdrawing(false)
      // React calls a function given to a state setter as an updater: freshListLoader is called,
      // and the new loader it returns becomes the state.
      setLoadRegistrations(freshListLoader)
    }
  }

  return (
    <div className="page page-wide my-registrations">
      <p className="eyebrow">Attend</p>
      <PageHeader
        title="My registrations"
        subtitle="The events you have registered for, and where you stand at each."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading your registrations…" />}

      {registrations !== null && registrations.length === 0 && (
        <EmptyState>
          You have not registered for any events yet.{' '}
          <Link to={UPCOMING_EVENTS_PATH}>Browse upcoming events</Link>
        </EmptyState>
      )}

      {registrations !== null && registrations.length > 0 && (
        <EventCardGrid>
          {registrations.map((registration) => (
            <MyRegistrationCard
              key={registration.id}
              registration={registration}
              onWithdraw={askToWithdraw}
            />
          ))}
        </EventCardGrid>
      )}

      {pending !== null && (
        <ConfirmDialog
          title={`Withdraw from ${pending.event_name}?`}
          confirmLabel="Withdraw"
          isBusy={isWithdrawing}
          error={refusal?.message ?? null}
          canConfirm={refusal === null || !refusal.isFinal}
          cancelLabel={refusal?.isFinal ? 'Close' : undefined}
          onConfirm={confirmWithdraw}
          onCancel={cancelWithdraw}
        >
          <p>
            Your place will be given up for someone else. If registration has closed or the event
            fills up, you may not be able to register again.
          </p>
        </ConfirmDialog>
      )}
    </div>
  )
}
