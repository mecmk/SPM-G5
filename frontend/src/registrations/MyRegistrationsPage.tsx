import { useState } from 'react'
import { Link } from 'react-router'
import { formatApiError } from '../api/client'
import {
  listMyRegistrations,
  withdrawRegistration,
  type MyRegistration,
  type RegistrationStanding,
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

/** Story 18.2 AC1/AC8: each status's label, and the badge colour it takes (App.css). */
const STANDING_BADGES: Record<RegistrationStanding, { status: string; label: string }> = {
  REGISTERED: { status: 'registered', label: 'Registered' },
  WITHDRAWN: { status: 'withdrawn', label: 'Withdrawn' },
  EVENT_CANCELLED: { status: 'cancelled', label: 'Event cancelled' },
}

/** Story 18.2 AC1: when the attendee registered, and when they withdrew if they did. */
function describeRegistration(registration: MyRegistration): string[] {
  const registered = `You registered on ${formatDateTime(registration.registered_at)}`
  return registration.withdrawn_at === null
    ? [registered]
    : [registered, `You withdrew on ${formatDateTime(registration.withdrawn_at)}`]
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
      imageUrl={null}
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
 * AC3: a refused withdrawal (the event started meanwhile, or it was already withdrawn or
 *      cancelled) shows the backend's reason in the dialog, and the list is loaded again so every
 *      card shows where it now stands.
 * AC5: attendees only - App.tsx guards the route, and the backend sends only their own.
 * AC7: the dialog's Withdraw is disabled while its request is in flight, so a double-click sends
 *      one.
 */
export function MyRegistrationsPage() {
  // Replaced by a fresh loader after a refused withdrawal, so useLoaded loads the list again; it
  // keeps showing the cards until the new list arrives.
  const [loadRegistrations, setLoadRegistrations] = useState(() => listMyRegistrations)
  const { data: registrations, error, isLoading, setData } = useLoaded(loadRegistrations)
  const [pending, setPending] = useState<MyRegistration | null>(null)
  const [isWithdrawing, setIsWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<string | null>(null)

  function askToWithdraw(registration: MyRegistration) {
    setWithdrawError(null)
    setPending(registration)
  }

  function cancelWithdraw() {
    setPending(null)
  }

  async function confirmWithdraw() {
    if (pending === null) return
    setIsWithdrawing(true)
    setWithdrawError(null)
    try {
      const withdrawn = await withdrawRegistration(pending)
      setData((current) =>
        current === null ? current : current.map((r) => (r.id === withdrawn.id ? withdrawn : r)),
      )
      setPending(null)
    } catch (err) {
      setWithdrawError(formatApiError(err))
      setLoadRegistrations(freshListLoader)
    } finally {
      setIsWithdrawing(false)
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
          error={withdrawError}
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
