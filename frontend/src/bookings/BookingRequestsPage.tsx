import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router'
import {
  approveBooking,
  listBookingRequests,
  rejectBooking,
  type Booking,
  type BookingQueue,
  type BookingQueueEntry,
  type BookingQueueOrder,
} from '../api/bookings'
import { formatApiError } from '../api/client'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import type { EventCardBackState } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { Pagination } from '../components/Pagination'
import { QueueSearchBar } from '../components/QueueSearchBar'
import { ReplacementNote } from '../components/ReplacementNote'
import { Chip } from '../components/Chip'
import { StatusBadge } from '../components/StatusBadge'
import { Tabs } from '../components/Tabs'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import { BOOKING_REQUESTS_PATH, bookingRequestPath } from '../routes'
import {
  bookingOutcomeLabels,
  bookingTabCount,
  bookingTabStatus,
  BOOKING_STATUS_TABS,
  APPROVED_BOOKING_STATUS,
  closedAt,
  EXPIRED_BOOKING_STATUS,
  HOLD_EXPIRED_LABEL,
  HOLD_EXPIRES_LABEL,
  openHoldExpiry,
  PENDING_BOOKING_STATUS,
  VENUE_UNAVAILABLE_LABEL,
  withBookingMoved,
  type BookingStatusTabKey,
} from '../shared/bookingStatus'
import {
  CANCELLED_AT_LABEL,
  CLEAR_SEARCH,
  formatDate,
  formatDateTime,
  formatTime,
  inputToInstant,
  instantToInput,
  nowAsInput,
  shortReference,
} from '../shared/format'
import {
  COMMON_QUEUE_ORDERS,
  DEFAULT_QUEUE_ORDER,
  queuePath,
  useQueueView,
  type QueueOrderOption,
  type QueueView,
  type QueueViewOptions,
} from '../shared/queueView'
import { useLoaded } from '../shared/useLoaded'
import { holdExpiryRefusal } from './holdExpiry'
import { venueStaffOutsideHoursNotice } from './turnaround'

/** Story 13.1.2 AC4: requests per numbered page. */
const QUEUE_PAGE_SIZE = 10
const PAGE_TITLE = 'Booking Requests'

/** Story 13.3 AC3: the booking queue's orders, as its Order by list offers them. */
const BOOKING_QUEUE_ORDERS: QueueOrderOption<BookingQueueOrder>[] = [
  ...COMMON_QUEUE_ORDERS,
  { key: 'venue_name', label: 'Venue: A to Z' },
]

type BookingQueueView = QueueView<BookingStatusTabKey, BookingQueueOrder>

/** Story 13.3 AC7: what the queue's address may name. With none, it opens on Pending (13.1.2
 * AC1), soonest first, on page 1. */
const BOOKING_QUEUE_VIEW: QueueViewOptions<BookingStatusTabKey, BookingQueueOrder> = {
  tabs: BOOKING_STATUS_TABS.map((item) => item.key),
  orders: BOOKING_QUEUE_ORDERS.map((option) => option.key),
  defaults: { tab: 'PENDING', search: '', order: DEFAULT_QUEUE_ORDER, page: 1 },
}

function requirementsText(notes: string | null): string {
  return notes && notes.trim() !== '' ? notes : 'No requirements stated.'
}

/** One page of a tab, and which page (1-based) it is. */
interface QueuePage extends BookingQueue {
  page: number
}

function fetchQueuePage(view: BookingQueueView, page: number): Promise<BookingQueue> {
  return listBookingRequests({
    status: bookingTabStatus(view.tab),
    search: view.search,
    order: view.order,
    offset: (page - 1) * QUEUE_PAGE_SIZE,
    limit: QUEUE_PAGE_SIZE,
  })
}

/** Load the view's page - or, when decisions made since have left that page past the end, the
 * last page that has any requests, so the page never settles on an empty one (story 13.3 AC9, under
 * a search too). */
async function loadQueuePage(view: BookingQueueView): Promise<QueuePage> {
  const queue = await fetchQueuePage(view, view.page)
  const lastPage = Math.max(1, Math.ceil(queue.total / QUEUE_PAGE_SIZE))
  if (view.page <= lastPage) return { ...queue, page: view.page }
  return { ...(await fetchQueuePage(view, lastPage)), page: lastPage }
}

/** Story 12.7 AC1: when an approved booking's open hold expires, as one of its card's facts;
 * nothing for any other booking. */
function OpenHoldFact({ entry }: { entry: BookingQueueEntry }) {
  const openHold = openHoldExpiry(entry)
  if (openHold === null) return null
  return (
    <div className="subtle-block">
      <p className="fact-label">{HOLD_EXPIRES_LABEL}</p>
      <p className="fact-value">{formatDateTime(openHold)}</p>
    </div>
  )
}

/** f12.1.2 (story 12.1 AC17): when the request's setup or teardown runs outside its venue's
 * opening hours, the card says so, with the booked period; nothing otherwise, nor for an entry
 * that gives no hours. */
function OutsideHoursNotice({ entry }: { entry: BookingQueueEntry }) {
  const notice = venueStaffOutsideHoursNotice(
    entry,
    entry.venue_operating_hours_start,
    entry.venue_operating_hours_end,
  )
  if (notice === null) return null
  return <p className="warning">{notice}</p>
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
            cancelled_at: decided.cancelled_at,
            hold_expires_at: decided.hold_expires_at,
            hold_completed_at: decided.hold_completed_at,
            // Story 12.6 AC3: a decided request releases nothing, so its card stops saying that
            // approving it will.
            approval_releases_venue_name: null,
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
 *
 * Story 12.7 (the customer's hold, 12 Oct 2026) AC1: approving starts the booking's hold, so the
 * Approve dialog asks when it expires, with no default, and refuses none, a past one or one after
 * the booked period starts before sending (AC5). An approved booking's card shows when its open
 * hold expires. AC3: one whose hold expired leaves Approved for the Expired tab, showing when it
 * was approved and when it expired.
 *
 * f12.1.2 (story 12.1 AC17): a request can be approved from its card (13.2 AC1), so a card whose
 * setup or teardown runs outside the venue's opening hours says so under the venue, with the
 * booked period.
 *
 * Story 6.2 AC14: a Cancelled tab lists, read-only, the bookings released when their event was
 * cancelled. AC16: such a card says when it was approved, if it was, and when it was cancelled.
 *
 * Story 13.3 AC1-AC3: a search box and an Order by list beside the tabs; the server searches the
 * event name, venue name and Submitted by, orders the tab and counts each tab's matches. AC4: a new
 * search or order starts again at page 1. AC6: a search nothing matches says so, with Clear
 * search. AC7: the tab, search, order and page live in the page address, and the request's page
 * (View details or its name) leads back to the same list.
 */
export function BookingRequestsPage() {
  const { view, query, changeView } = useQueueView(BOOKING_QUEUE_VIEW)
  const { tab } = view
  // One request object per view and per decision made on this page, so a decision is a new
  // `loadPage` and so a fresh load of the same view through `useLoaded`. Its `cancelled` flag drops
  // an older load's answer if the view changes first, and `isStale` hides the old view's requests
  // until the new answer arrives.
  const [decisionCount, setDecisionCount] = useState(0)
  const request = useMemo(() => ({ view, decisionCount }), [view, decisionCount])
  const loadPage = useCallback(() => loadQueuePage(request.view), [request])
  const { data: queue, error, isLoading, isStale, setData: setQueue } = useLoaded(loadPage)
  const [pendingApprove, setPendingApprove] = useState<BookingQueueEntry | null>(null)
  const [approveExpiry, setApproveExpiry] = useState('')
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
  // Story 13.3 AC7: a request's page leads back to this list as it stands.
  const backToQueue: EventCardBackState = {
    from: queuePath(BOOKING_REQUESTS_PATH, query),
    fromLabel: PAGE_TITLE,
  }
  const isSearched = view.search.trim() !== ''

  function changeTab(next: BookingStatusTabKey) {
    changeView({ tab: next })
  }

  function changePage(next: number) {
    changeView({ page: next })
  }

  const changeSearch = useCallback((search: string) => changeView({ search }), [changeView])

  function changeOrder(order: BookingQueueOrder) {
    changeView({ order })
  }

  function clearSearch() {
    changeView({ search: '' })
  }

  /** Under All the decided entry stays, showing its outcome. Under a status tab it no longer
   * belongs, so the page is fetched again and the next request moves up - `loadQueuePage` steps
   * back a page if that one is now empty. Story 12.6 AC3: approving a replacement released the
   * booking it replaces, which moves too and which the card says no more of, so under All the page
   * is fetched again as well. */
  function recordDecision(decided: Booking) {
    const hasReleased =
      decided.status === APPROVED_BOOKING_STATUS && decided.replaces_booking_id !== null
    if (tab === 'ALL' && !hasReleased) {
      setQueue((current) => current && withDecisionInPlace(current, decided))
      return
    }
    setDecisionCount((count) => count + 1)
  }

  function askToApprove(entry: BookingQueueEntry) {
    setApproveError(null)
    setApproveExpiry('')
    setPendingApprove(entry)
  }

  function cancelApprove() {
    setPendingApprove(null)
  }

  /** Story 12.7 AC1/AC5: the hold's expiry is checked before the approval is sent. */
  async function confirmApprove() {
    if (!pendingApprove) return
    const { id, event_name: eventName, held_from: heldFrom } = pendingApprove
    const refusal = holdExpiryRefusal(approveExpiry, heldFrom)
    if (refusal !== null) {
      setApproveError(refusal)
      return
    }
    setIsApproving(true)
    setApproveError(null)
    try {
      const decided = await approveBooking(
        id,
        { hold_expires_at: inputToInstant(approveExpiry) },
        eventName,
      )
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
        title={PAGE_TITLE}
        subtitle="Venue booking requests to decide, and the decisions already made."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading booking requests…" />}

      {queue !== null && (
        <div className="stack">
          <Tabs tabs={tabs} activeKey={tab} onChange={changeTab} />

          <QueueSearchBar
            search={view.search}
            placeholder="Event, venue or who submitted it"
            onSearch={changeSearch}
            order={view.order}
            orders={BOOKING_QUEUE_ORDERS}
            onOrder={changeOrder}
          />

          {/* Below the search box, so the box stays where it is while the list loads. */}
          {isStale && error === null && <LoadingState label="Loading booking requests…" />}

          {!isStale && queue.items.length === 0 && isSearched && (
            <EmptyState>
              No requests match your search.{' '}
              <button type="button" className="link" onClick={clearSearch}>
                {CLEAR_SEARCH}
              </button>
            </EmptyState>
          )}

          {!isStale && queue.items.length === 0 && !isSearched && (
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
                      <span className="small muted mono">{shortReference(entry.id)}</span>
                      {/* Story 9.4 AC3: its venue is unavailable for part of the request. */}
                      {entry.venue_unavailable_marked_at !== null && (
                        <Chip tone="warning" label={VENUE_UNAVAILABLE_LABEL} />
                      )}
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
                      <Link to={bookingRequestPath(entry.id)} state={backToQueue}>
                        {entry.event_name}
                      </Link>
                    </h3>
                    <p className="muted">
                      {entry.venue_name} · {entry.venue_location}
                    </p>
                  </div>

                  <OutsideHoursNotice entry={entry} />

                  {/* Story 12.6 AC3/AC6: a replacement says what it replaces and what approving
                      it releases. */}
                  <ReplacementNote
                    replacesVenueName={entry.replaces_venue_name}
                    approvalReleasesVenueName={entry.approval_releases_venue_name}
                    originalIsMarked={entry.original_is_marked}
                  />

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
                    <OpenHoldFact entry={entry} />
                  </div>

                  <div className="subtle-block">
                    <p className="fact-label">Special requirements</p>
                    <p>{requirementsText(entry.requirement_notes)}</p>
                  </div>

                  {entry.decided_at !== null && (
                    <div className="subtle-block">
                      <p className="fact-label">{bookingOutcomeLabels(entry).when}</p>
                      <p>{formatDateTime(closedAt(entry) ?? entry.decided_at)}</p>
                    </div>
                  )}

                  {entry.cancelled_at !== null && (
                    <div className="subtle-block">
                      <p className="fact-label">{CANCELLED_AT_LABEL}</p>
                      <p>{formatDateTime(entry.cancelled_at)}</p>
                    </div>
                  )}

                  {entry.status === EXPIRED_BOOKING_STATUS && entry.hold_expires_at && (
                    <div className="subtle-block">
                      <p className="fact-label">{HOLD_EXPIRED_LABEL}</p>
                      <p>{formatDateTime(entry.hold_expires_at)}</p>
                    </div>
                  )}

                  {entry.decision_reason !== null && (
                    <div className="subtle-block">
                      <p className="fact-label">{bookingOutcomeLabels(entry).why}</p>
                      <p>{entry.decision_reason}</p>
                    </div>
                  )}

                  {entry.status === PENDING_BOOKING_STATUS &&
                    entry.venue_unavailable_marked_at !== null && (
                      <p id={`unavailable-${entry.id}`} className="small muted">
                        This venue is unavailable for part of this request. It cannot be approved
                        while the closure stands.
                      </p>
                    )}

                  <div className="item-card-footer">
                    {entry.status === PENDING_BOOKING_STATUS && (
                      <div className="cluster">
                        <button
                          type="button"
                          className="brand button-sm"
                          disabled={entry.venue_unavailable_marked_at !== null}
                          aria-describedby={
                            entry.venue_unavailable_marked_at !== null
                              ? `unavailable-${entry.id}`
                              : undefined
                          }
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
                    <Link to={bookingRequestPath(entry.id)} state={backToQueue} className="link">
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
          {/* Story 12.7 AC1/AC5: the hold this approval starts, and when it expires. */}
          <p>
            It is held until the event is confirmed. Choose when the hold expires if it is not, no
            later than the start of the booked period, {formatDateTime(pendingApprove.held_from)}.
          </p>
          <label>
            {HOLD_EXPIRES_LABEL}
            <input
              type="datetime-local"
              value={approveExpiry}
              min={nowAsInput()}
              max={instantToInput(pendingApprove.held_from)}
              onChange={(event) => setApproveExpiry(event.target.value)}
              disabled={isApproving}
            />
          </label>
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
