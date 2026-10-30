import { Fragment, useCallback, useState } from 'react'
import { formatApiError } from '../api/client'
import { listEventRegistrations } from '../api/registrations'
import { EmptyState } from '../components/EmptyState'
import { RegistrationCount } from '../components/RegistrationCount'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { formatDateTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import {
  STANDING_BADGES,
  describeDietaryRequirements,
  describeGuestOf,
  describePhone,
} from './registrationLabels'

/**
 * Story 18.3 - who has registered for the event, for its organiser and assigned coordinator, on
 * the registrations report. AC1: each attendee's name, status, email and registration time, a
 * page at a time ("Load more"), and the active count against capacity. AC2/AC7: the count and
 * whether it is full come from the server with each page. AC3: an empty list says so, and a full
 * event says "Full". AC4: withdrawn and cancelled rows show where they stand, as 18.2 tells the
 * attendee, and when they withdrew. Status comes second so a phone shows it beside the name.
 *
 * Story 18.4 AC5: each Registered attendee's phone number and dietary requirements, for catering
 * and contact - "None" when none were given (AC6). A row no longer Registered leaves both empty
 * (AC9): the server sends neither. On a desktop the list is a table; on a phone each attendee is a
 * card of labelled lines (App.css `.registration-table`), and long dietary requirements wrap.
 *
 * Story 18.5 AC4: each guest an attendee brings on a row of their own, under the attendee's and in
 * their order, marked as their guest, with their dietary requirements in the same column as the
 * attendee's - "None" when blank - and a count that includes them. AC9: a row no longer Registered
 * shows its guests by name only, as it does the attendee. On a phone each guest is a card of their
 * own, set in under the attendee's (App.css `.registration-guest`).
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
              <table className="registration-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Email</th>
                    <th>Phone</th>
                    <th>Dietary requirements</th>
                    <th>Registered</th>
                  </tr>
                </thead>
                <tbody>
                  {list.items.map((registration) => {
                    const badge = STANDING_BADGES[registration.status]
                    const isRegistered = registration.status === 'REGISTERED'
                    return (
                      <Fragment key={registration.id}>
                        <tr>
                          <td className="registration-name">{registration.attendee_name}</td>
                          <td data-label="Status">
                            <StatusBadge status={badge.status} label={badge.label} />
                            {registration.withdrawn_at !== null &&
                              ` ${formatDateTime(registration.withdrawn_at)}`}
                          </td>
                          <td data-label="Email">{registration.attendee_email}</td>
                          <td data-label="Phone">
                            {isRegistered ? describePhone(registration.attendee_phone) : ''}
                          </td>
                          <td data-label="Dietary requirements" className="registration-dietary">
                            {isRegistered
                              ? describeDietaryRequirements(registration.dietary_requirements)
                              : ''}
                          </td>
                          <td data-label="Registered">
                            {formatDateTime(registration.registered_at)}
                          </td>
                        </tr>
                        {registration.guests.map((guest, index) => (
                          <tr key={index} className="registration-guest">
                            <td className="registration-name">
                              {guest.full_name}
                              <span className="registration-guest-of">
                                {describeGuestOf(registration.attendee_name)}
                              </span>
                            </td>
                            <td />
                            <td />
                            <td />
                            <td data-label="Dietary requirements" className="registration-dietary">
                              {isRegistered
                                ? describeDietaryRequirements(guest.dietary_requirements)
                                : ''}
                            </td>
                            <td />
                          </tr>
                        ))}
                      </Fragment>
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
