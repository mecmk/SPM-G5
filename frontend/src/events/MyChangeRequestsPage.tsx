import type { MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { listMyChangeRequests } from '../api/changeRequests'
import { EmptyState } from '../components/EmptyState'
import type { EventCardBackState } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { EVENTS_MINE_PATH, eventPath, MY_CHANGE_REQUESTS_PATH } from '../routes'
import { formatDateTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { changeTitle, STATUS_LABELS } from './changeRequestValues'

/** An event opened from a row here leads back to this page, not to Home (story 7.1's back link). */
const BACK_TO_MY_CHANGE_REQUESTS: EventCardBackState = {
  from: MY_CHANGE_REQUESTS_PATH,
  fromLabel: 'Change requests',
}

/**
 * Story 19.4 - the organiser's change requests across all their events.
 * AC1: each row names the event, what it changes, when it was raised and its status.
 * AC2: pending first, newest first within each status - the backend's order, kept as sent.
 * AC3: a click anywhere on a row opens its event's page, as the safety queue's cards do (21.1).
 *      The event page has no anchor for its change requests, so the row opens the page's top.
 * AC4: only the organiser's own requests come back (the backend scopes them); other roles see
 *      "not permitted" at this address (RequirePermission in App.tsx).
 * AC5: with none, the page says so and points to My events.
 */
export function MyChangeRequestsPage() {
  const { data: requests, error, isLoading } = useLoaded(listMyChangeRequests)
  const navigate = useNavigate()

  /** AC3: a plain left click on the row, outside its link and not ending a text selection. */
  function openRow(click: MouseEvent<HTMLLIElement>, eventId: string) {
    if (click.button !== 0 || click.metaKey || click.ctrlKey || click.shiftKey || click.altKey)
      return
    if (click.target instanceof Element && click.target.closest('a')) return
    if (window.getSelection()?.isCollapsed === false) return
    navigate(eventPath(eventId), { state: BACK_TO_MY_CHANGE_REQUESTS })
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Change requests"
        subtitle="The changes you have asked for on your events, and where each one stands."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading your change requests…" />}

      {requests !== null && requests.length === 0 && (
        <EmptyState>
          You have not raised any change requests yet. Ask for one from an approved event in{' '}
          <Link to={EVENTS_MINE_PATH}>My events</Link>.
        </EmptyState>
      )}

      {requests !== null && requests.length > 0 && (
        <ul className="stack queue-list" aria-label="Your change requests">
          {requests.map((request) => (
            <li
              key={request.id}
              className="card stack queue-card-linked"
              onClick={(click) => openRow(click, request.event_id)}
            >
              <div className="item-card-header">
                <StatusBadge status={request.status} label={STATUS_LABELS[request.status]} />
              </div>
              <div>
                <h3 className="queue-card-title">
                  <Link to={eventPath(request.event_id)} state={BACK_TO_MY_CHANGE_REQUESTS}>
                    {request.event_name}
                  </Link>
                </h3>
                <p className="muted">{changeTitle(request.field)}</p>
                <p className="small muted">Raised {formatDateTime(request.created_at)}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
