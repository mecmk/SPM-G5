import { useEffect, useState } from 'react'
import { formatApiError } from '../api/client'
import { listCoordinators, reassignCoordinator, type CoordinatorOption } from '../api/coordination'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { CoordinatorPicker } from '../components/CoordinatorPicker'
import { ERROR_REGISTRY } from '../errors/registry'

interface ReassignDialogProps {
  eventId: string
  eventName: string
  /** The coordinator the page shows, sent so a change since is refused (5.6 AC6). */
  currentCoordinatorId: string
  /** Called once the event has its new coordinator, for the page to read it afresh. */
  onReassigned: () => void
  onCancel: () => void
}

/**
 * Story 5.6 - the Lead hands an event to another coordinator, from the event page or a card on
 * the overview (AC1). AC3: the picker offers only the other active coordinators, each with their
 * active-event count, loaded when the dialog opens. AC6: a refusal - the coordinator changed in
 * the meantime - is shown in the dialog with the backend's own sentence.
 */
export function ReassignDialog({
  eventId,
  eventName,
  currentCoordinatorId,
  onReassigned,
  onCancel,
}: ReassignDialogProps) {
  const [coordinators, setCoordinators] = useState<CoordinatorOption[] | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listCoordinators(eventId)
      .then((options) => {
        if (cancelled) return
        setCoordinators(options)
        setSelectedId(options.length > 0 ? options[0].id : '')
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [eventId])

  async function confirm() {
    // Still loading, or the list failed to load (its error is already shown): nothing to send.
    if (coordinators === null) return
    if (!selectedId) {
      setError(ERROR_REGISTRY.NO_OTHER_COORDINATOR.message)
      return
    }
    setIsSaving(true)
    setError(null)
    try {
      await reassignCoordinator(eventId, selectedId, currentCoordinatorId)
      onReassigned()
    } catch (err) {
      setError(formatApiError(err))
      setIsSaving(false)
    }
  }

  return (
    <ConfirmDialog
      title={`Reassign "${eventName}"?`}
      confirmLabel="Confirm reassignment"
      tone="primary"
      isBusy={isSaving}
      error={error}
      onConfirm={confirm}
      onCancel={onCancel}
    >
      <p>
        Hand this event to a different active Event Coordinator. Both coordinators and the organiser
        are told.
      </p>
      <CoordinatorPicker
        label="New coordinator"
        coordinators={coordinators}
        value={selectedId}
        onChange={setSelectedId}
      />
    </ConfirmDialog>
  )
}
