import type { ChangeEvent } from 'react'
import { useSearchParams } from 'react-router'
import { listManagedRegistrationEvents } from '../api/registrations'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import { formatSchedule } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { RegistrationListSection } from './RegistrationListSection'

/** The search parameter that holds the picked event, so the event page can link straight to it. */
const EVENT_PARAM = 'event'

/**
 * Story 18.3 - the registrations report. AC5: the organiser or assigned coordinator picks one of
 * the events taking registrations that they manage, and AC1-AC4 reads who registered for it
 * (`RegistrationListSection`). The event page's "View registrations" opens it with that event
 * picked.
 */
export function RegistrationReportPage() {
  const { data: events, error, isLoading } = useLoaded(listManagedRegistrationEvents)
  const [searchParams, setSearchParams] = useSearchParams()
  const eventId = searchParams.get(EVENT_PARAM) ?? ''

  function pickEvent(e: ChangeEvent<HTMLSelectElement>) {
    setSearchParams(e.target.value ? { [EVENT_PARAM]: e.target.value } : {})
  }

  return (
    <div className="page stack">
      <PageHeader
        title="Registrations"
        subtitle="Who has registered for the events you organise or coordinate."
      />
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading your events…" />}
      {events !== null && events.length === 0 && (
        <EmptyState>You have no events taking registrations.</EmptyState>
      )}
      {events !== null && events.length > 0 && (
        <label>
          Event
          <select value={eventId} onChange={pickEvent}>
            <option value="">Choose an event</option>
            {events.map((event) => (
              <option key={event.id} value={event.id}>
                {event.name} · {formatSchedule(event.starts_at, event.ends_at)}
              </option>
            ))}
          </select>
        </label>
      )}
      {eventId && <RegistrationListSection eventId={eventId} />}
    </div>
  )
}
