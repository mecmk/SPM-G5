import { useCallback, useState, type ChangeEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import type { EventStatus } from '../api/events'
import {
  listActiveEvents,
  listWorkloads,
  UNASSIGNED_FILTER,
  type ActiveEventEntry,
  type CoordinatorWorkloadEntry,
} from '../api/coordination'
import { EmptyState } from '../components/EmptyState'
import { EventCard, EventCardGrid } from '../components/EventCard'
import { EventStatusBadge } from '../components/EventStatusBadge'
import { PageHeader } from '../components/PageHeader'
import { Tabs } from '../components/Tabs'
import { LoadingState } from '../layout/LoadingState'
import {
  ASSIGNED_BY_ME,
  ASSIGNMENT_SEARCH_PARAMS,
  COORDINATORS_VIEW,
  EVENTS_ASSIGNMENTS_PATH,
  eventPath,
} from '../routes'
import {
  ACTIVE_EVENT_STATUSES,
  EVENT_STATUS_TABS,
  type EventStatusTabKey,
} from '../shared/eventStatus'
import { formatSchedule, NOT_RECORDED, NOT_YET_ASSIGNED } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

const PAGE_TITLE = 'Assignments'
const DEACTIVATED = 'Deactivated'
const BACK_TO_PAGE = { from: EVENTS_ASSIGNMENTS_PATH, fromLabel: PAGE_TITLE }
const ALL_COORDINATORS = ''

/** Story 5.5 AC1 (PO decision P1): 6.1's tabs and labels, for the active statuses only. */
const ACTIVE_TABS = EVENT_STATUS_TABS.filter(
  (tab) => tab.key === 'ALL' || ACTIVE_EVENT_STATUSES.includes(tab.key as EventStatus),
)

/** A status from the address, if it is one of the active ones; anything else shows them all. */
function activeStatus(value: string | null): EventStatus | undefined {
  return ACTIVE_EVENT_STATUSES.find((status) => status === value)
}

function countLabel(count: number): string {
  return `${count} active ${count === 1 ? 'event' : 'events'}`
}

/**
 * A filter as the Lead sees it: their choice shows at once, while the address - which React
 * Router updates in a transition - catches up, and a change to the address (back, a link) shows
 * too. The same approach as 8.1's `useFilterValue` in `venues/VenueFilterPanel.tsx`.
 */
function useShownFilter<T>(fromAddress: T) {
  const [value, setValue] = useState(fromAddress)
  const [lastFromAddress, setLastFromAddress] = useState(fromAddress)
  if (fromAddress !== lastFromAddress) {
    setLastFromAddress(fromAddress)
    setValue(fromAddress)
  }
  return { value, setValue }
}

/** Story 5.5 AC1: who the event is with - a coordinator, flagged if deactivated, or nobody yet. */
function coordinatorDetail(entry: ActiveEventEntry) {
  if (entry.coordinator_name === null) {
    return <span className="badge badge-neutral">{NOT_YET_ASSIGNED}</span>
  }
  return (
    <span className="cluster">
      Coordinator: {entry.coordinator_name}
      {entry.coordinator_is_active === false && (
        <span className="badge badge-danger">{DEACTIVATED}</span>
      )}
    </span>
  )
}

/**
 * Story 5.5 - the Event Coordinator Lead's overview of coordinators' assignments.
 * AC1: every active event with its status, dates, coordinator (or "Not yet assigned") and the
 * Lead who assigned it, narrowed by 6.1's status tabs, by coordinator and to "Assigned by me".
 * The view and the filters live in the page address, so a link or a reload keeps them (and AC5's
 * "shown on refresh" reads afresh).
 * AC2/AC4: the per-coordinator view lists each coordinator with their number of active events,
 * 0 included, and the events themselves.
 * AC3: each event opens its read-only details page (7.1).
 * AC5: a deactivated coordinator who still holds events is flagged in both views.
 */
export function AssignmentOverviewPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const isCoordinatorsView = searchParams.get(ASSIGNMENT_SEARCH_PARAMS.view) === COORDINATORS_VIEW
  const status = activeStatus(searchParams.get(ASSIGNMENT_SEARCH_PARAMS.status))
  const coordinator = searchParams.get(ASSIGNMENT_SEARCH_PARAMS.coordinator) ?? ALL_COORDINATORS
  const isAssignedByMe = searchParams.get(ASSIGNMENT_SEARCH_PARAMS.assignedByMe) === ASSIGNED_BY_ME

  const loadOverview = useCallback(
    () => listActiveEvents({ coordinator: coordinator || undefined, status, isAssignedByMe }),
    [coordinator, status, isAssignedByMe],
  )
  const overview = useLoaded(loadOverview)
  const workloads = useLoaded(listWorkloads)
  // While a changed filter loads, the previous filter's events are hidden rather than shown under
  // the new one (`useLoaded`'s isStale).
  const freshEvents = overview.isStale ? null : overview.data
  const shownStatus = useShownFilter<EventStatusTabKey>(status ?? 'ALL')
  const shownCoordinator = useShownFilter(coordinator)
  const shownAssignedByMe = useShownFilter(isAssignedByMe)

  /** Change one filter in the address, keeping the others; an empty value removes it. */
  function setFilter(name: string, value: string) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current)
        if (value) next.set(name, value)
        else next.delete(name)
        return next
      },
      { replace: true },
    )
  }

  function changeTab(key: EventStatusTabKey) {
    shownStatus.setValue(key)
    setFilter(ASSIGNMENT_SEARCH_PARAMS.status, key === 'ALL' ? '' : key)
  }

  function changeCoordinator(change: ChangeEvent<HTMLSelectElement>) {
    shownCoordinator.setValue(change.target.value)
    setFilter(ASSIGNMENT_SEARCH_PARAMS.coordinator, change.target.value)
  }

  function changeAssignedByMe(change: ChangeEvent<HTMLInputElement>) {
    shownAssignedByMe.setValue(change.target.checked)
    setFilter(ASSIGNMENT_SEARCH_PARAMS.assignedByMe, change.target.checked ? ASSIGNED_BY_ME : '')
  }

  /** The address for the other view, keeping the filters. */
  function viewPath(isCoordinators: boolean): string {
    const next = new URLSearchParams(searchParams)
    if (isCoordinators) next.set(ASSIGNMENT_SEARCH_PARAMS.view, COORDINATORS_VIEW)
    else next.delete(ASSIGNMENT_SEARCH_PARAMS.view)
    const query = next.toString()
    return query ? `${EVENTS_ASSIGNMENTS_PATH}?${query}` : EVENTS_ASSIGNMENTS_PATH
  }

  return (
    <div className="page page-wide assignment-overview">
      <p className="eyebrow">Events</p>
      <PageHeader
        title={PAGE_TITLE}
        subtitle="Every active event, and each coordinator's share of them."
      />

      <nav className="view-switch" aria-label="View">
        <Link
          to={viewPath(false)}
          className="view-switch-link"
          aria-current={isCoordinatorsView ? undefined : 'page'}
        >
          All active events
        </Link>
        <Link
          to={viewPath(true)}
          className="view-switch-link"
          aria-current={isCoordinatorsView ? 'page' : undefined}
        >
          By coordinator
        </Link>
      </nav>

      {isCoordinatorsView ? (
        <CoordinatorsView workloads={workloads.data} error={workloads.error} />
      ) : (
        <div className="stack">
          <Tabs tabs={ACTIVE_TABS} activeKey={shownStatus.value} onChange={changeTab} />

          <div className="filter-bar">
            <label>
              Coordinator
              <select value={shownCoordinator.value} onChange={changeCoordinator}>
                <option value={ALL_COORDINATORS}>All coordinators</option>
                <option value={UNASSIGNED_FILTER}>{NOT_YET_ASSIGNED}</option>
                {workloads.data?.map((entry) => (
                  <option key={entry.coordinator_id} value={entry.coordinator_id}>
                    {entry.is_active
                      ? entry.coordinator_name
                      : `${entry.coordinator_name} (${DEACTIVATED.toLowerCase()})`}
                  </option>
                ))}
              </select>
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={shownAssignedByMe.value}
                onChange={changeAssignedByMe}
              />
              Assigned by me
            </label>
          </div>

          {overview.error && (
            <p role="alert" className="error">
              {overview.error}
            </p>
          )}
          {(overview.isLoading || overview.isStale) && (
            <LoadingState label="Loading active events…" />
          )}
          {freshEvents !== null && freshEvents.length === 0 && (
            <EmptyState>No active events match these filters.</EmptyState>
          )}
          {freshEvents !== null && freshEvents.length > 0 && (
            <EventCardGrid label="Active events">
              {freshEvents.map((entry) => (
                <EventCard
                  key={entry.id}
                  title={entry.name}
                  imageUrl={null}
                  to={eventPath(entry.id)}
                  state={BACK_TO_PAGE}
                  details={[
                    <EventStatusBadge key="status" status={entry.status} />,
                    formatSchedule(entry.starts_at, entry.ends_at),
                    <span key="coordinator">{coordinatorDetail(entry)}</span>,
                    `Assigned by ${entry.assigned_by_name ?? NOT_RECORDED}`,
                  ]}
                />
              ))}
            </EventCardGrid>
          )}
        </div>
      )}
    </div>
  )
}

interface CoordinatorsViewProps {
  workloads: CoordinatorWorkloadEntry[] | null
  error: string | null
}

/** Story 5.5 AC2/AC4/AC5: each coordinator, their count (0 included), flag and events. */
function CoordinatorsView({ workloads, error }: CoordinatorsViewProps) {
  if (error) {
    return (
      <p role="alert" className="error">
        {error}
      </p>
    )
  }
  if (workloads === null) return <LoadingState label="Loading coordinators…" />
  if (workloads.length === 0) return <EmptyState>No Event Coordinators yet.</EmptyState>
  return (
    <ul className="workload-list" aria-label="Coordinators">
      {workloads.map((entry) => (
        <li key={entry.coordinator_id} className="card stack workload-card">
          <div className="cluster">
            <h2 className="workload-name">{entry.coordinator_name}</h2>
            {!entry.is_active && <span className="badge badge-danger">{DEACTIVATED}</span>}
          </div>
          <p className="muted">{countLabel(entry.active_event_count)}</p>
          {entry.events.length > 0 && (
            <ul className="workload-events">
              {entry.events.map((event) => (
                <li key={event.id} className="workload-event">
                  <Link to={eventPath(event.id)} state={BACK_TO_PAGE}>
                    {event.name}
                  </Link>
                  <span className="cluster small muted">
                    <EventStatusBadge status={event.status} />
                    {formatSchedule(event.starts_at, event.ends_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  )
}
