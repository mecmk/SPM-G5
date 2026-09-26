import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import {
  approveBooking,
  listBookingRequests,
  rejectBooking,
  type BookingQueueEntry,
} from '../api/bookings'
import { formatApiError } from '../api/client'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import { bookingRequestPath } from '../routes'
import { formatDate, formatTime } from '../shared/format'

const SHORT_ID_LENGTH = 8

function requirementsText(notes: string | null): string {
  return notes && notes.trim() !== '' ? notes : 'No requirements stated.'
}

/**
 * Story 13.1 - the venue staff booking requests queue.
 * AC1: every pending request, for the signed-in Venue Staff member to decide.
 * AC2: each entry shows the event name, requested venue, period, expected attendance and
 * stated requirements.
 * AC3: decided requests never appear - the backend query excludes them.
 *
 * Story 13.2 AC1: an Approve action on each card, so a request that needs no closer look can be
 * decided without opening its detail page.
 *
 * Story 13.2.1 AC1-AC3: a Reject action alongside it, requiring a reason.
 */
export function BookingRequestsPage() {
  const [entries, setEntries] = useState<BookingQueueEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pendingApprove, setPendingApprove] = useState<BookingQueueEntry | null>(null)
  const [isApproving, setIsApproving] = useState(false)
  const [approveError, setApproveError] = useState<string | null>(null)
  const [pendingReject, setPendingReject] = useState<BookingQueueEntry | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [isRejecting, setIsRejecting] = useState(false)
  const [rejectError, setRejectError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listBookingRequests()
      .then((data) => {
        if (!cancelled) setEntries(data)
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

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
      await approveBooking(id, eventName)
      setEntries((current) => current && current.filter((entry) => entry.id !== id))
      setPendingApprove(null)
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
      await rejectBooking(id, eventName, reason)
      setEntries((current) => current && current.filter((entry) => entry.id !== id))
      setPendingReject(null)
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
        subtitle="Incoming venue booking requests awaiting your review."
      />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {entries === null && !error && <LoadingState label="Loading booking requests…" />}

      {entries !== null && (
        <div className="stack">
          <p className="eyebrow">Pending ({entries.length})</p>

          {entries.length === 0 && (
            <EmptyState>No requests waiting. You are up to date.</EmptyState>
          )}

          {entries.length > 0 && (
            <ul className="stack">
              {entries.map((entry) => (
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
                  </div>

                  <div className="subtle-block">
                    <p className="fact-label">Special requirements</p>
                    <p>{requirementsText(entry.requirement_notes)}</p>
                  </div>

                  <div className="item-card-footer">
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
                    <Link to={bookingRequestPath(entry.id)} className="link">
                      View details →
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
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
