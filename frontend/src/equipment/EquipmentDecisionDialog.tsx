import { useState } from 'react'
import { ApiError, formatApiError } from '../api/client'
import {
  decideEquipmentRequest,
  shortfallOf,
  type EquipmentDecision,
  type EquipmentDecisionOutcome,
  type EquipmentQueueEntry,
  type EquipmentShortfall,
} from '../api/equipment'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { ERROR_REGISTRY } from '../errors/registry'
import { formatSchedule } from '../shared/format'

export interface EquipmentDecisionDialogProps {
  entry: EquipmentQueueEntry
  outcome: EquipmentDecisionOutcome
  onCancel: () => void
  onDecided: (decided: EquipmentQueueEntry) => void
  /** Story 16.1 AC6: an accept was refused for a shortfall, with the figures it reported. */
  onShortfall: (figures: EquipmentShortfall) => void
  /** Story 16.1 AC7/AC9: any other refusal - decided by someone else meanwhile, its event closed,
   * or the request removed - so the page loads it again. */
  onRefused: () => void
}

/**
 * Story 16.1 - the Accept and Decline dialogs, shared by the queue and a request's own page.
 * AC1: Accept asks before reserving, naming the event's whole period, which the hold covers. AC2/AC4: Decline asks for a reason and refuses a blank or
 * spaces-only one before anything is sent. AC6/AC7/AC9: a refusal stays in the dialog with the
 * backend's sentence. AC9: the confirm button is disabled while the decision is saved, and a
 * click that lands meanwhile is ignored, so a double-click decides once.
 * AC7/AC9: a refusal other than a shortfall, or a request gone meanwhile, has the page load it
 * again behind the dialog, so it stops offering a decision that can no longer be made.
 * AC6: when the request is short - as its card showed, or as a refused accept reported - Accept
 * warns that it will be refused and suggests declining instead. Accept stays enabled: the server
 * decides, and the figures on screen may be out of date either way.
 */
export function EquipmentDecisionDialog({
  entry,
  outcome,
  onCancel,
  onDecided,
  onShortfall,
  onRefused,
}: EquipmentDecisionDialogProps) {
  const [reason, setReason] = useState('')
  const [isDeciding, setIsDeciding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refusedFigures, setRefusedFigures] = useState<EquipmentShortfall | null>(null)
  const isAccept = outcome === 'ACCEPTED'
  const shortFigures =
    refusedFigures ??
    (entry.shortfall > 0 ? { available: entry.available, shortfall: entry.shortfall } : null)

  async function decide(decision: EquipmentDecision) {
    setIsDeciding(true)
    setError(null)
    try {
      onDecided(await decideEquipmentRequest(entry, decision))
    } catch (err) {
      setError(formatApiError(err))
      const figures = shortfallOf(err)
      if (figures !== null) {
        setRefusedFigures(figures)
        onShortfall(figures)
      } else if (err instanceof ApiError && (err.status === 409 || err.status === 404)) {
        onRefused()
      }
    } finally {
      setIsDeciding(false)
    }
  }

  async function confirm() {
    if (isDeciding) return
    if (isAccept) {
      await decide({ outcome: 'ACCEPTED' })
      return
    }
    const trimmed = reason.trim()
    if (trimmed === '') {
      setError(ERROR_REGISTRY.EQUIPMENT_REASON_REQUIRED.message)
      return
    }
    await decide({ outcome: 'DECLINED', reason: trimmed })
  }

  if (isAccept) {
    return (
      <ConfirmDialog
        title="Accept this request?"
        confirmLabel="Accept"
        tone="primary"
        isBusy={isDeciding}
        error={error}
        onConfirm={confirm}
        onCancel={onCancel}
      >
        <p>
          {entry.equipment_type_name} ×{entry.quantity} will be reserved for {entry.event_name} on{' '}
          {formatSchedule(entry.starts_at, entry.ends_at)}.
        </p>
        {shortFigures !== null && (
          <p className="warning">
            Only {shortFigures.available} {shortFigures.available === 1 ? 'is' : 'are'} available
            for this event's dates, short by {shortFigures.shortfall}. Accepting will be refused, so
            consider declining it with a reason instead.
          </p>
        )}
      </ConfirmDialog>
    )
  }

  return (
    <ConfirmDialog
      title="Decline this request?"
      confirmLabel="Decline"
      isBusy={isDeciding}
      error={error}
      onConfirm={confirm}
      onCancel={onCancel}
    >
      <p>
        {entry.event_name}'s request for {entry.equipment_type_name} ×{entry.quantity} will be
        declined, and the units it holds released.
      </p>
      <label>
        Reason for declining
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={3}
          disabled={isDeciding}
        />
      </label>
    </ConfirmDialog>
  )
}
