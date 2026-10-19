import { useCallback, useState } from 'react'
import { formatApiError } from '../api/client'
import { listEventRegistrations } from '../api/registrations'
import { EmptyState } from '../components/EmptyState'
import { RegistrationCount } from '../components/RegistrationCount'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { formatDateTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { STANDING_BADGES } from './registrationLabels'

/**
 * Story 18.3 - who has registered for the event, for its organiser and assigned coordinator, on
 * the registrations report. AC1: each attendee's name, status, email and registration time, a
 * page at a time ("Load more"), and the active count against capacity. AC2/AC7: the count and
 * whether it is full come from the server with each page. AC3: an empty list says so, and a full
 * event says "Full". AC4: withdrawn and cancelled rows show where they stand, as 18.2 tells the
 * attendee, and when they withdrew. Status comes second so a phone shows it beside the name.
 */
export function RegistrationListSection({ eventId }: { eventId: string }) {
  const load = useCallback(() => listEventRegistrations(eventId), [eventId])
  const { data: list, error, isLoading, isStale, setData: setList } = useLoaded(load)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null)

  /** AC1: registrations are only ever added after the last, so the next page starts where the
   *  shown ones end; its counts are the latest, so they replace the shown ones. */
  async function handleLoadMore() {
    if (list === null) return
    setIsLoadingMore(true)
    setLoadMoreError(null)
    try {
      const next = await listEventRegistrations(eventId, list.items.length)
      setList((current) =>
        current === null ? current : { ...next, items: [...current.items, ...next.items] },
      )
    } catch (err) {
      setLoadMoreError(formatApiError(err))
    } finally {
      setIsLoadingMore(false)
    }
  }

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
          <RegistrationCount
            activeCount={list.active_count}
            capacity={list.capacity}
            isFull={list.is_full}
          />
          {list.items.length === 0 ? (
            <EmptyState>No one has registered yet.</EmptyState>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Email</th>
                    <th>Registered</th>
                  </tr>
                </thead>
                <tbody>
                  {list.items.map((registration) => {
                    const badge = STANDING_BADGES[registration.status]
                    return (
                      <tr key={registration.id}>
                        <td>{registration.attendee_name}</td>
                        <td>
                          <StatusBadge status={badge.status} label={badge.label} />
                          {registration.withdrawn_at !== null &&
                            ` ${formatDateTime(registration.withdrawn_at)}`}
                        </td>
                        <td>{registration.attendee_email}</td>
                        <td>{formatDateTime(registration.registered_at)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {loadMoreError && (
            <p role="alert" className="error">
              {loadMoreError}
            </p>
          )}
          {list.items.length < list.total && (
            <div className="load-more">
              <p className="small muted">
                Showing {list.items.length} of {list.total} registrations
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
    </section>
  )
}
