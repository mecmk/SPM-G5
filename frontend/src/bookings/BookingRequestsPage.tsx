import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router'
import {
  approveBooking,
  listBookingRequests,
  rejectBooking,
  type Booking,
  type BookingQueue,
  type BookingQueueEntry,
} from '../api/bookings'
import { formatApiError } from '../api/client'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { Pagination } from '../components/Pagination'
import { StatusBadge } from '../components/StatusBadge'
import { Tabs } from '../components/Tabs'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import { bookingRequestPath } from '../routes'
import {
  bookingOutcomeLabels,
  bookingTabCount,
  bookingTabStatus,
  BOOKING_STATUS_TABS,
  PENDING_BOOKING_STATUS,
  withBookingMoved,
  type BookingStatusTabKey,
} from '../shared/bookingStatus'
import { formatDate, formatDateTime, formatTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'

const SHORT_ID_LENGTH = 8
/** Story 13.1.2 AC4: requests per numbered page. */
const QUEUE_PAGE_SIZE = 10

function requirementsText(notes: string | null): string {
  return notes && notes.trim() !== '' ? notes : 'No requirements stated.'
}

/** One page of a tab, and which page (1-based) it is. */
interface QueuePage extends BookingQueue {
  page: number
}

function fetchQueuePage(tab: BookingStatusTabKey, page: number): Promise<BookingQueue> {
  return listBookingRequests(bookingTabStatus(tab), (page - 1) * QUEUE_PAGE_SIZE, QUEUE_PAGE_SIZE)
}

/** Load the `page`th page of a tab - or, when decisions made since have left that page past the
 * end, the last page that has any requests, so the page never settles on an empty one. */
async function loadQueuePage(tab: BookingStatusTabKey, page: number): Promise<QueuePage> {
  const queue = await fetchQueuePage(tab, page)
  const lastPage = Math.max(1, Math.ceil(queue.total / QUEUE_PAGE_SIZE))
  if (page <= lastPage) return { ...queue, page }
  return { ...(await fetchQueuePage(tab, lastPage)), page: lastPage }
}

/** Under All, `queue` once `decided` - the request it names - was decided on this page: the
 * entry stays where it is, showing the outcome, and the counts move it to its new status. */
function withDecisionInPlace(queue: QueuePage, decided: Booking): QueuePage {
  return {
    ...queue,
    items: queue.items.map((entry) =>
      entry.id === decided.id
        ? {
            ...entry,
            status: decided.status,
            decision_reason: decided.decision_reason,
            decided_at: decided.decided_at,
          }
        : entry,
    ),
    counts: withBookingMoved(queue.counts, PENDING_BOOKING_STATUS, decided.status),
  }
}

/**
 * Story 13.1 - the venue staff booking requests queue.
 * AC1: every pending request, for the signed-in Venue Staff member to decide.
 * AC2: each entry shows the event name, requested venue, period, expected attendance and stated
 * requirements.
 * AC3: decided requests do not appear in the pending queue.
 *
 * Story 13.1.2 AC1: the page opens on the Pending tab, so it reads as a queue; All / Approved /
 * Rejected show the rest, matching the coordinator's Events inbox tab pattern (story 6.1). Each
 * tab asks the backend for its own status, and every tab label carries the backend's count.
 * AC2: when the coordinator raised the request. AC3: when and why a decided one was decided.
 * AC4: ten requests a page, with Previous / numbered pages / Next.
 *
 * Story 13.2 AC1: an Approve action on each pending card, so a request that needs no closer
 * look can be decided without opening its detail page.
 *
 * Story 13.2.1 AC1-AC3: a Reject action alongside it, requiring a reason.
 */
export function BookingRequestsPage() {
  // One object, so every `setView` is a new `loadPage` and so a fresh load through `useLoaded`,
  // even when the tab and page stay the same - which is how a decision refetches the page. The
  // `cancelled` flag in `useLoaded` then drops an older load's answer if the tab changes first,
  // and `isStale` hides the old tab or page's requests until the new answer arrives.
  const [view, setView] = useState<{ tab: BookingStatusTabKey; page: number }>({
    tab: 'PENDING',
    page: 1,
  })
  const { tab } = view
  const loadPage = useCallback(() => loadQueuePage(view.tab, view.page), [view])
  const { data: queue, error, isLoading, isStale, setData: setQueue } = useLoaded(loadPage)
  const [pendingApprove, setPendingApprove] = useState<BookingQueueEntry | null>(null)
  const [isApproving, setIsApproving] = useState(false)
  const [approveError, setApproveError] = useState<string | null>(null)
  const [pendingReject, setPendingReject] = useState<BookingQueueEntry | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [isRejecting, setIsRejecting] = useState(false)
  const [rejectError, setRejectError] = useState<string | null>(null)

  const tabs = useMemo(
    () =>
      BOOKING_STATUS_TABS.map((item) => ({
        key: item.key,
        label: `${item.label} (${queue ? bookingTabCount(item.key, queue.counts) : 0})`,
      })),
    [queue],
  )

  const pageCount = queue ? Math.ceil(queue.total / QUEUE_PAGE_SIZE) : 0
  const firstShown = queue ? (queue.page - 1) * QUEUE_PAGE_SIZE + 1 : 0

  function changeTab(next: BookingStatusTabKey) {
    setView({ tab: next, page: 1 })
  }

  function changePage(next: number) {
    setView({ tab, page: next })
  }

  /** Under All the decided entry stays, showing its outcome. Under a status tab it no longer
   * belongs, so the page is fetched again and the next request moves up - `loadQueuePage` steps
   * back a page if that one is now empty. */
  function recordDecision(decided: Booking) {
    if (tab === 'ALL') {
      setQueue((current) => current && withDecisionInPlace(current, decided))
      return
    }
    setView({ tab, page: queue?.page ?? 1 })
  }

  function askToApprove(entry: BookingQueueEntry) {
    setApproveError(null)
    setPendingApprove(entry)
  }

  function cancelApprove() {
    setPendingApprove(null)
  }

  async function confirmApprove() {
    if (!pendingApprove) return
    const { id, event_name: eventName } = pendingApprove
    setIsApproving(true)
    setApproveError(null)
    try {
      const decided = await approveBooking(id, eventName)
      setPendingApprove(null)
      recordDecision(decided)
    } catch (err) {
      setApproveError(formatApiError(err))
    } finally {
      setIsApproving(false)
    }
  }

  function askToReject(entry: BookingQueueEntry) {
    setRejectError(null)
    setRejectReason('')
    setPendingReject(entry)
  }

  function cancelReject() {
    setPendingReject(null)
  }

  async function confirmReject() {
    if (!pendingReject) return
    const reason = rejectReason.trim()
    if (reason === '') {
      setRejectError(ERROR_REGISTRY.BOOKING_REASON_REQUIRED.message)
      return
    }
    const { id, event_name: eventName } = pendingReject
    setIsRejecting(true)
    setRejectError(null)
    try {
      const decided = await rejectBooking(id, eventName, reason)
      setPendingReject(null)
      recordDecision(decided)
    } catch (err) {
      setRejectError(formatApiError(err))
    } finally {
      setIsRejecting(false)
    }
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Booking Requests"
        subtitle="Venue booking requests to decide, and the decisions already made."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {(isLoading || (isStale && error === null)) && (
        <LoadingState label="Loading booking requests…" />
      )}

      {queue !== null && (
        <div className="stack">
          <Tabs tabs={tabs} activeKey={tab} onChange={changeTab} />

          {!isStale && queue.items.length === 0 && (
            <EmptyState>
              {tab === PENDING_BOOKING_STATUS
                ? 'No requests waiting. You are up to date.'
                : 'No requests in this tab.'}
            </EmptyState>
          )}

          {!isStale && queue.items.length > 0 && (
            <ul className="stack">
              {queue.items.map((entry) => (
                <li key={entry.id} className="card stack">
                  <div className="item-card-header">
                    <div className="cluster">
                      <StatusBadge status={entry.status} />
                      <span className="small muted mono">
                        #{entry.id.slice(-SHORT_ID_LENGTH).toUpperCase()}
                      </span>
                    </div>
                    <div className="item-card-capacity">
                      <div>{formatDate(entry.starts_at)}</div>
                      <div className="small muted">
                        {formatTime(entry.starts_at)}–{formatTime(entry.ends_at)}
                      </div>
                    </div>
                  </div>

                  <div>
                    <h3 className="queue-card-title">
                      <Link to={bookingRequestPath(entry.id)}>{entry.event_name}</Link>
                    </h3>
                    <p className="muted">
                      {entry.venue_name} · {entry.venue_location}
                    </p>
                  </div>

                  <div className="fact-grid">
                    <div className="subtle-block">
                      <p className="fact-label">Layout</p>
                      <p className="fact-value">{entry.required_layout_name ?? 'Any'}</p>
                    </div>
                    <div className="subtle-block">
                      <p className="fact-label">Attendance</p>
                      <p className="fact-value">{entry.expected_attendance}</p>
                    </div>
                    <div className="subtle-block">
                      <p className="fact-label">Submitted by</p>
                      <p className="fact-value">{entry.requested_by_name}</p>
                    </div>
                    <div className="subtle-block">
                      <p className="fact-label">Requested at</p>
                      <p className="fact-value">{formatDateTime(entry.created_at)}</p>
                    </div>
                  </div>

                  <div className="subtle-block">
                    <p className="fact-label">Special requirements</p>
                    <p>{requirementsText(entry.requirement_notes)}</p>
                  </div>

                  {entry.decided_at !== null && (
                    <div className="subtle-block">
                      <p className="fact-label">{bookingOutcomeLabels(entry.status).when}</p>
                      <p>{formatDateTime(entry.decided_at)}</p>
                    </div>
                  )}

                  {entry.decision_reason !== null && (
                    <div className="subtle-block">
                      <p className="fact-label">{bookingOutcomeLabels(entry.status).why}</p>
                      <p>{entry.decision_reason}</p>
                    </div>
                  )}

                  <div className="item-card-footer">
                    {entry.status === PENDING_BOOKING_STATUS && (
                      <div className="cluster">
                        <button
                          type="button"
                          className="brand button-sm"
                          onClick={() => askToApprove(entry)}
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          className="danger-solid button-sm"
                          onClick={() => askToReject(entry)}
                        >
                          Reject
                        </button>
                      </div>
                    )}
                    <Link to={bookingRequestPath(entry.id)} className="link">
                      View details →
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {!isStale && pageCount > 1 && (
            <div className="pager-bar">
              <p className="small muted">
                Showing {firstShown}–{firstShown + queue.items.length - 1} of {queue.total} requests
              </p>
              <Pagination page={queue.page} pageCount={pageCount} onChange={changePage} />
            </div>
          )}
        </div>
      )}

      {pendingApprove && (
        <ConfirmDialog
          title="Approve this booking?"
          confirmLabel="Approve"
          tone="primary"
          isBusy={isApproving}
          error={approveError}
          onConfirm={confirmApprove}
          onCancel={cancelApprove}
        >
          <p>
            {pendingApprove.venue_name} will be booked for {pendingApprove.event_name} from{' '}
            {formatDate(pendingApprove.starts_at)}, {formatTime(pendingApprove.starts_at)}–
            {formatTime(pendingApprove.ends_at)}.
          </p>
        </ConfirmDialog>
      )}

      {pendingReject && (
        <ConfirmDialog
          title="Reject this booking?"
          confirmLabel="Reject"
          isBusy={isRejecting}
          error={rejectError}
          onConfirm={confirmReject}
          onCancel={cancelReject}
        >
          <p>
            {pendingReject.event_name}'s request for {pendingReject.venue_name} will be rejected.
          </p>
          <label>
            Reason for rejecting
            <textarea
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              rows={3}
              disabled={isRejecting}
            />
          </label>
        </ConfirmDialog>
      )}
    </div>
  )
}
