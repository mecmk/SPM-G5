import { useState } from 'react'
import {
  approveChangeRequest,
  CHANGE_REASON_MAX_LENGTH,
  rejectChangeRequest,
  type ChangeRequest,
  type ChangeRequestStatus,
} from '../api/changeRequests'
import { ApiError, formatApiError } from '../api/client'
import type { EventReferenceData } from '../api/events'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { ERROR_REGISTRY } from '../errors/registry'
import { ChangeRequestChanges } from './ChangeRequestChanges'
import { FIELD_LABELS } from './changeRequestValues'

export interface ChangeRequestDecisionDialogProps {
  request: ChangeRequest
  /** The decision being made: approving or rejecting. */
  outcome: Extract<ChangeRequestStatus, 'APPROVED' | 'REJECTED'>
  /** For the field's values in words - layout and equipment names. */
  references: EventReferenceData | null
  onCancel: () => void
  onDecided: (decided: ChangeRequest) => void
  /** AC7: refused because the request or its event moved on meanwhile - decided, withdrawn, gone
   *  or changed - so the page loads it again behind the dialog. */
  onRefused: () => void
}

/**
 * Story 19.2 - the Approve and Reject dialogs, shared by the coordinator's queue and the event
 * page. AC2: Approve shows what changes, now beside requested, before applying it. AC3/AC4: Reject
 * asks for a reason and refuses a blank or spaces-only one before anything is sent. AC5/AC7/AC8:
 * a refusal stays in the dialog with the backend's sentence, and one caused by the request or its
 * event moving on has the page reload it. The confirm button is disabled while the decision is
 * saved, and a click that lands meanwhile is ignored, so a double-click decides once.
 */
export function ChangeRequestDecisionDialog({
  request,
  outcome,
  references,
  onCancel,
  onDecided,
  onRefused,
}: ChangeRequestDecisionDialogProps) {
  const [reason, setReason] = useState('')
  const [isDeciding, setIsDeciding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const label = FIELD_LABELS[request.field].toLowerCase()
  const isApprove = outcome === 'APPROVED'

  async function decide(send: () => Promise<ChangeRequest>) {
    setIsDeciding(true)
    setError(null)
    try {
      onDecided(await send())
    } catch (err) {
      setError(formatApiError(err))
      if (err instanceof ApiError && (err.status === 409 || err.status === 404)) onRefused()
    } finally {
      setIsDeciding(false)
    }
  }

  async function confirm() {
    if (isDeciding) return
    if (isApprove) {
      await decide(() => approveChangeRequest(request.event_id, request.id, label))
      return
    }
    const trimmed = reason.trim()
    if (trimmed === '') {
      setError(ERROR_REGISTRY.CHANGE_REQUEST_REJECTION_REASON_REQUIRED.message)
      return
    }
    await decide(() => rejectChangeRequest(request.event_id, request.id, trimmed, label))
  }

  if (isApprove) {
    return (
      <ConfirmDialog
        title="Approve this change?"
        confirmLabel="Approve"
        tone="primary"
        isBusy={isDeciding}
        error={error}
        onConfirm={confirm}
        onCancel={onCancel}
      >
        <p>This change is applied to the event, and the organiser will be told.</p>
        <ChangeRequestChanges request={request} references={references} />
      </ConfirmDialog>
    )
  }

  return (
    <ConfirmDialog
      title="Reject this change?"
      confirmLabel="Reject"
      isBusy={isDeciding}
      error={error}
      onConfirm={confirm}
      onCancel={onCancel}
    >
      <p>The {label} stays as it is, and the organiser will be told your reason.</p>
      <label>
        Reason for rejecting
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={3}
          maxLength={CHANGE_REASON_MAX_LENGTH}
          disabled={isDeciding}
        />
      </label>
    </ConfirmDialog>
  )
}
