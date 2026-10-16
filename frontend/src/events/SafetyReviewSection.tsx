import { useCallback, useState } from 'react'
import { formatApiError } from '../api/client'
import {
  confirmEvent,
  getEventSafety,
  requestSafetyReview,
  unchangedArrangementsOf,
  type EventSafety,
} from '../api/safety'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { StatusBadge } from '../components/StatusBadge'
import { formatDateTime } from '../shared/format'
import { ARRANGEMENT_LABELS } from '../shared/safetyReview'
import { useLoaded } from '../shared/useLoaded'

interface SafetyReviewSectionProps {
  eventId: string
  eventName: string
  /** Called once a request or confirmation has moved the event on, so the page reloads it. */
  onStatusChanged: () => void
}

function BlockerList({ intro, blockers }: { intro: string; blockers: string[] }) {
  return (
    <div className="subtle-block stack">
      <p className="fact-label">{intro}</p>
      <ul>
        {blockers.map((blocker) => (
          <li key={blocker}>{blocker}</li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Story 21.2 - the event's safety review, on its page.
 * AC4: the latest review, with each finding and the arrangement it says must change, for anyone
 * who may see the event. AC1/AC19: the assigned coordinator requests a review once everything is
 * secured, or reads what is missing. AC12: when a flagged arrangement is unchanged, a warning asks
 * before sending anyway. AC7/AC14: the coordinator confirms an approved event, or reads why not.
 */
export function SafetyReviewSection({
  eventId,
  eventName,
  onStatusChanged,
}: SafetyReviewSectionProps) {
  const loadSafety = useCallback(() => getEventSafety(eventId), [eventId])
  const { data: safety, error: loadError, setData } = useLoaded(loadSafety)
  const [isBusy, setIsBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [unchangedWarning, setUnchangedWarning] = useState<string | null>(null)

  async function act(action: () => Promise<EventSafety>) {
    setIsBusy(true)
    setActionError(null)
    try {
      setData(await action())
      setUnchangedWarning(null)
      onStatusChanged()
    } catch (caught) {
      if (unchangedArrangementsOf(caught) !== null) setUnchangedWarning(formatApiError(caught))
      else setActionError(formatApiError(caught))
    } finally {
      setIsBusy(false)
    }
  }

  function handleRequestReview() {
    void act(() => requestSafetyReview(eventId, eventName, false))
  }

  function handleSubmitAnyway() {
    void act(() => requestSafetyReview(eventId, eventName, true))
  }

  function handleCancelWarning() {
    setUnchangedWarning(null)
  }

  function handleConfirm() {
    void act(() => confirmEvent(eventId, eventName))
  }

  const review = safety?.latest_review ?? null
  const canRequest =
    safety?.status === 'PLANNING' &&
    safety.request_blockers !== null &&
    safety.confirm_blockers?.length !== 0
  const canConfirm = safety?.confirm_blockers?.length === 0

  return (
    <section className="card stack" aria-labelledby="safety-review-heading">
      <h2 id="safety-review-heading">Safety review</h2>
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      {safety !== null && (
        <>
          {review === null ? (
            <p className="muted">Not reviewed yet.</p>
          ) : (
            <div className="subtle-block stack">
              <div className="cluster">
                <StatusBadge status={review.outcome} />
                <span className="small muted">
                  {formatDateTime(review.reviewed_at)} by {review.reviewed_by_name}
                </span>
              </div>
              {review.findings.length > 0 && (
                <ol className="stack">
                  {review.findings.map((finding, index) => (
                    <li key={index}>
                      <p className="fact-label">
                        {finding.factor_name}
                        {finding.arrangement &&
                          ` · ${ARRANGEMENT_LABELS[finding.arrangement]} must change`}
                      </p>
                      <p>{finding.required_change}</p>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}

          {safety.status === 'AWAITING_SAFETY_CHECK' && (
            <p className="muted">Awaiting the Safety Officer's review.</p>
          )}

          {canRequest &&
            (safety.request_blockers?.length === 0 ? (
              <div>
                <button type="button" disabled={isBusy} onClick={handleRequestReview}>
                  Request safety review
                </button>
              </div>
            ) : (
              <BlockerList
                intro="Before requesting a safety review:"
                blockers={safety.request_blockers ?? []}
              />
            ))}

          {canConfirm && (
            <div>
              <button type="button" disabled={isBusy} onClick={handleConfirm}>
                Confirm event
              </button>
            </div>
          )}
          {review?.outcome === 'APPROVED' &&
            safety.status === 'PLANNING' &&
            (safety.confirm_blockers?.length ?? 0) > 0 && (
              <BlockerList
                intro="Before confirming this event:"
                blockers={safety.confirm_blockers ?? []}
              />
            )}

          {actionError && (
            <p role="alert" className="error">
              {actionError}
            </p>
          )}
        </>
      )}

      {unchangedWarning !== null && (
        <ConfirmDialog
          title="Flagged arrangements unchanged"
          confirmLabel="Submit anyway"
          tone="primary"
          isBusy={isBusy}
          error={null}
          onConfirm={handleSubmitAnyway}
          onCancel={handleCancelWarning}
        >
          <p>{unchangedWarning}</p>
          <p>Send it for a safety review anyway?</p>
        </ConfirmDialog>
      )}
    </section>
  )
}
