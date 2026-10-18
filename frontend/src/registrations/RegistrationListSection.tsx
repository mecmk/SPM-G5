import { useCallback } from 'react'
import { listEventRegistrations } from '../api/registrations'
import { Chip } from '../components/Chip'
import { EmptyState } from '../components/EmptyState'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { formatDateTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

/**
 * Story 18.3 - who has registered for the event, for its organiser and assigned coordinator, on
 * the registrations report. AC1: each attendee's name, email, registration time and status, and the active count
 * against capacity. AC2/AC7: the count and whether it is full come from the server with the list.
 * AC3: an empty list says so, and a full event says "Full". AC4: withdrawn rows show their status.
 */
export function RegistrationListSection({ eventId }: { eventId: string }) {
  const load = useCallback(() => listEventRegistrations(eventId), [eventId])
  const { data: list, error, isLoading, isStale } = useLoaded(load)

  return (
    <section className="card stack" aria-labelledby="registration-list-heading">
      <h2 id="registration-list-heading">Registered attendees</h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {(isLoading || (isStale && !error)) && <LoadingState label="Loading registrations…" />}
      {/* Another event's rows never show under this one while it loads (useLoaded's isStale). */}
      {list !== null && !isStale && (
        <>
          <div className="cluster">
            <span>
              {list.active_count} / {list.capacity ?? '–'} registered
            </span>
            {list.is_full && <Chip label="Full" tone="warning" />}
          </div>
          {list.items.length === 0 ? (
            <EmptyState>No one has registered yet.</EmptyState>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Registered</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {list.items.map((registration) => (
                    <tr key={registration.id}>
                      <td>{registration.attendee_name}</td>
                      <td>{registration.attendee_email}</td>
                      <td>{formatDateTime(registration.registered_at)}</td>
                      <td>
                        <StatusBadge status={registration.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  )
}
