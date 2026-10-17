import { useState } from 'react'
import { formatApiError } from '../api/client'
import {
  confirmEvent,
  requestSafetyReview,
  unchangedArrangementsOf,
  type EventSafety,
} from '../api/safety'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { SafetyFindingsList } from '../components/SafetyFindingsList'
import { StatusBadge } from '../components/StatusBadge'
import { formatDateTime } from '../shared/format'

interface SafetyReviewSectionProps {
  eventId: string
  eventName: string
  /** The event's safety summary, loaded by the page so the sections it flags can say so. */
  safety: EventSafety | null
  loadError: string | null
  /** Reloads the event and its safety summary: after a request or confirmation, after a refusal
   *  (whatever was out of date is shown as it is now), and after any other change on the page. */
  onChanged: () => Promise<void>
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
 * before anything is sent, and the coordinator can go back or submit anyway. AC7/AC14: the
 * coordinator confirms an approved event, or reads why not. AC18: no one else is offered either.
 */
export function SafetyReviewSection({
  eventId,
  eventName,
  safety,
  loadError,
  onChanged,
}: SafetyReviewSectionProps) {
  const [isBusy, setIsBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [unchangedWarning, setUnchangedWarning] = useState<string | null>(null)

  async function act(action: () => Promise<EventSafety>) {
    setIsBusy(true)
    setActionError(null)
    try {
      await action()
      setUnchangedWarning(null)
    } catch (caught) {
      if (unchangedArrangementsOf(caught) !== null) setUnchangedWarning(formatApiError(caught))
      else setActionError(formatApiError(caught))
    } finally {
      await onChanged()
      setIsBusy(false)
    }
  }

  function handleRequestReview() {
    setActionError(null)
    if (safety?.unchanged_warning) setUnchangedWarning(safety.unchanged_warning)
    else void act(() => requestSafetyReview(eventId, eventName, false))
  }

  function handleSubmitAnyway() {
    void act(() => requestSafetyReview(eventId, eventName, true))
  }

  function handleCancelWarning() {
    setUnchangedWarning(null)
    setActionError(null)
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
              <SafetyFindingsList findings={review.findings} />
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

          {actionError && unchangedWarning === null && (
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
          error={actionError}
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
