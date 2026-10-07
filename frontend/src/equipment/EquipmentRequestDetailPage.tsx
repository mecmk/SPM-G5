import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router'
import {
  getEquipmentRequest,
  type EquipmentDecisionOutcome,
  type EquipmentQueueEntry,
  type EquipmentShortfall,
} from '../api/equipment'
import type { EventCardBackState } from '../components/EventCard'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../layout/LoadingState'
import { EQUIPMENT_REQUESTS_PATH, equipmentRequestPath, eventPath } from '../routes'
import { NOT_RECORDED, formatDate, formatDateTime, formatTime } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { EquipmentDecisionDialog } from './EquipmentDecisionDialog'

/** The event page's back link returns to this request's page (story 7.1's back state). */
function backToRequest(itemId: string): EventCardBackState {
  return { from: equipmentRequestPath(itemId), fromLabel: 'Equipment Request' }
}

/**
 * Story 16.1 - one equipment request's own page, opened from View details in the queue, as Venue
 * Staff open a booking request (story 13.1). It shows what the queue card shows (15.2 AC1/AC2):
 * the event and its dates, the item, its quantity and technical notes, who sent it, and what the
 * event's period has for it, with any shortfall.
 * AC1/AC2: Accept and Decline next to the status while the request is Pending, through the
 * dialogs the queue uses; the page then shows the outcome and the actions go.
 * AC3: a decided request says who decided and when, and a declined one always shows its reason,
 * or that none was recorded (a request declined before reasons were required).
 * AC6: a refused accept leaves the page showing the shortfall it reported. AC7/AC9: any other
 * refusal loads the request again, so a decision made elsewhere meanwhile shows.
 * View event details opens the event (story 7.1), whose back link returns to this page.
 */
export function EquipmentRequestDetailPage() {
  const { itemId = '' } = useParams()
  const loadRequest = useCallback(() => getEquipmentRequest(itemId), [itemId])
  const { data: entry, error, isLoading, setData: setEntry } = useLoaded(loadRequest)
  const [openOutcome, setOpenOutcome] = useState<EquipmentDecisionOutcome | null>(null)

  function closeDecision() {
    setOpenOutcome(null)
  }

  function recordDecision(decided: EquipmentQueueEntry) {
    setOpenOutcome(null)
    setEntry(decided)
  }

  function recordShortfall(figures: EquipmentShortfall) {
    setEntry((current) => current && { ...current, ...figures })
  }

  /** Story 16.1 AC7/AC9: a decision refused for the request's state - load it again, so the page
   * shows what happened meanwhile. */
  async function reloadRequest() {
    try {
      setEntry(await loadRequest())
    } catch {
      // The dialog already shows the refusal; the page keeps what it last loaded.
    }
  }

  function askToAccept() {
    setOpenOutcome('ACCEPTED')
  }

  function askToDecline() {
    setOpenOutcome('DECLINED')
  }

  return (
    <div className="page page-wide equipment-request-page">
      <Link to={EQUIPMENT_REQUESTS_PATH} className="back-link">
        ← Equipment Requests
      </Link>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading the equipment request…" />}

      {entry !== null && (
        <>
          <div className="item-card-header booking-detail-header">
            <div className="cluster">
              <h1>{entry.event_name}</h1>
              <StatusBadge status={entry.status} />
            </div>
            {entry.status === 'PENDING' && (
              <div className="cluster">
                <button type="button" className="brand button-sm" onClick={askToAccept}>
                  Accept
                </button>
                <button type="button" className="danger-solid button-sm" onClick={askToDecline}>
                  Decline
                </button>
              </div>
            )}
          </div>

          {entry.status === 'DECLINED' && (
            <p className="subtle-block">
              <span className="fact-label">Reason</span>
              <br />
              {entry.decision_reason ?? NOT_RECORDED}
            </p>
          )}
          {entry.decided_at !== null && (
            <p className="small muted">
              Decided {formatDateTime(entry.decided_at)}
              {entry.decided_by_name !== null && ` by ${entry.decided_by_name}`}
            </p>
          )}

          <div className="stack">
            <section className="stat-card-grid" aria-labelledby="equipment-summary-heading">
              <h2 id="equipment-summary-heading" className="visually-hidden">
                Request summary
              </h2>
              <div className="stat-card">
                <Icon name="calendar" size={20} />
                <p className="stat-card-value">{formatDate(entry.starts_at)}</p>
                <p className="fact-label">Date</p>
              </div>
              <div className="stat-card">
                <Icon name="calendar-check" size={20} />
                <p className="stat-card-value">
                  {formatTime(entry.starts_at)} – {formatTime(entry.ends_at)}
                </p>
                <p className="fact-label">Time</p>
              </div>
            </section>

            <section className="card stack" aria-labelledby="equipment-request-heading">
              <h2 id="equipment-request-heading">{entry.equipment_type_name}</h2>
              <div className="fact-grid">
                <div className="subtle-block">
                  <p className="fact-label">Requested</p>
                  <p className="fact-value">{entry.quantity}</p>
                </div>
                <div className="subtle-block">
                  <p className="fact-label">Available</p>
                  <p className="fact-value">{entry.available}</p>
                </div>
                <div className="subtle-block">
                  <p className="fact-label">Shortfall</p>
                  <p className="fact-value">
                    {entry.shortfall > 0 ? (
                      <span className="badge badge-warning">Short by {entry.shortfall}</span>
                    ) : (
                      'None'
                    )}
                  </p>
                </div>
                <div className="subtle-block">
                  <p className="fact-label">Requested by</p>
                  <p className="fact-value">{entry.requested_by_name ?? NOT_RECORDED}</p>
                </div>
                <div className="subtle-block">
                  <p className="fact-label">Requested at</p>
                  <p className="fact-value">
                    {entry.submitted_at === null
                      ? NOT_RECORDED
                      : formatDateTime(entry.submitted_at)}
                  </p>
                </div>
              </div>
              <div className="subtle-block">
                <p className="fact-label">Technical notes</p>
                <p>{entry.technical_notes ?? 'No technical notes.'}</p>
              </div>
              <div className="item-card-footer item-card-footer-end">
                <Link
                  to={eventPath(entry.event_id)}
                  state={backToRequest(entry.id)}
                  className="link"
                >
                  View event details →
                </Link>
              </div>
            </section>
          </div>
        </>
      )}

      {entry !== null && openOutcome !== null && (
        <EquipmentDecisionDialog
          key={openOutcome}
          entry={entry}
          outcome={openOutcome}
          onCancel={closeDecision}
          onDecided={recordDecision}
          onShortfall={recordShortfall}
          onRefused={reloadRequest}
        />
      )}
    </div>
  )
}
