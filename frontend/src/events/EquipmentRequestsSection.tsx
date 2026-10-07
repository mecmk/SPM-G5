import { useEffect, useId, useState, type FormEvent } from 'react'
import { formatApiError } from '../api/client'
import {
  addEquipmentItem,
  fetchEquipmentAvailability,
  removeEquipmentItem,
  submitEquipment,
  TECHNICAL_NOTES_MAX_LENGTH,
  updateEquipmentItem,
  type EquipmentAvailability,
  type EquipmentItemChange,
} from '../api/equipment'
import type { EquipmentItemStatus, EquipmentLine } from '../api/events'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { StatusBadge } from '../components/StatusBadge'
import { ERROR_REGISTRY } from '../errors/registry'
import { formatDateTime } from '../shared/format'

/** Story 15.1 AC1: how each item status reads on the event page. */
const STATUS_LABELS: Record<EquipmentItemStatus, string> = {
  REQUESTED: 'Not yet sent',
  PENDING: 'Pending',
  ACCEPTED: 'Accepted',
  DECLINED: 'Declined',
  UNAVAILABLE: 'Unavailable',
  CANCELLED: 'Cancelled',
}
/** AC2/AC7: the items the coordinator may still edit or remove, mirroring the backend's
 *  `_EDITABLE_ITEM_STATUSES` (backend/app/equipment/service.py). */
const EDITABLE_STATUSES: readonly EquipmentItemStatus[] = ['REQUESTED', 'PENDING', 'UNAVAILABLE']
/** AC6: an item in one of these takes up its type on the event, mirroring `_OPEN_ITEM_STATUSES`;
 *  a declined or cancelled one does not, so its type can be requested again. */
const OPEN_STATUSES: readonly EquipmentItemStatus[] = [...EDITABLE_STATUSES, 'ACCEPTED']
const WHOLE_NUMBER = /^\d+$/
const UNAVAILABLE_SENTENCE =
  "The event's dates changed and not enough are free. Lower the quantity or remove it."
/** Story 16.1 AC2: a declined item always shows a reason, or that none was recorded. */
const NO_REASON_RECORDED = 'Not recorded'

/** AC4: a typed quantity must be a whole number from 1 to the number available. */
function isQuantityAllowed(value: string, available: number | undefined): boolean {
  if (!WHOLE_NUMBER.test(value)) return false
  const quantity = Number(value)
  return quantity >= 1 && (available === undefined || quantity <= available)
}

/** AC3/AC4: the figure shown under a quantity, for the event's own dates. */
function describeAvailable(available: number): string {
  return `${available} available for this event's dates`
}

/** Notes as they are stored: trimmed, and none at all when only spaces were typed (AC5). */
function trimmedNotes(notes: string): string | null {
  return notes.trim() || null
}

export interface EquipmentRequestsSectionProps {
  eventId: string
  equipment: EquipmentLine[]
  /** AC9: the event's assigned coordinator, while it is Under Review, Clarification Requested or
   *  Planning. Everyone else who can see the event gets the list alone. */
  canChange: boolean
  /** Reloads the event after a change, so every item shows its new status. */
  onChanged: () => Promise<void>
}

/**
 * Story 15.1: the event's equipment, on the event page's Equipment requirements section - there
 * is no separate equipment request page (AC1, CL-041). Everyone who can see the event sees each
 * item and its status (AC1, AC9). The assigned coordinator, while the equipment can change, also
 * adds items from types that show how many are free (AC1, AC3, AC6), edits and removes them (AC2,
 * AC7), and sends what is waiting to Technical Support (AC1). The quantity is checked here before
 * anything is sent (AC4), and the server re-checks every change; after a refusal the figures are
 * reloaded, so the form shows what is free now (AC4, AC10).
 * Story 16.1 AC1/AC2: an item Technical Support accepted reads Accepted, and one it declined shows
 * the reason, so the coordinator knows whether to plan for something else. AC3: a decided item
 * says when, and by whom.
 */
export function EquipmentRequestsSection({
  eventId,
  equipment,
  canChange,
  onChanged,
}: EquipmentRequestsSectionProps) {
  const ids = useId()
  const [availability, setAvailability] = useState<EquipmentAvailability[] | null>(null)
  const [availabilityError, setAvailabilityError] = useState<string | null>(null)
  const [availabilityVersion, setAvailabilityVersion] = useState(0)
  const [typeCode, setTypeCode] = useState('')
  const [quantity, setQuantity] = useState('')
  const [notes, setNotes] = useState('')
  const [isAddChecked, setIsAddChecked] = useState(false)
  const [isAdding, setIsAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [editing, setEditing] = useState<EquipmentLine | null>(null)
  const [editQuantity, setEditQuantity] = useState('')
  const [editNotes, setEditNotes] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [pendingRemoval, setPendingRemoval] = useState<EquipmentLine | null>(null)
  const [isRemoving, setIsRemoving] = useState(false)
  const [removeError, setRemoveError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    if (!canChange) return undefined
    let cancelled = false
    fetchEquipmentAvailability(eventId)
      .then((data) => {
        if (cancelled) return
        setAvailability(data)
        setAvailabilityError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setAvailabilityError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [eventId, canChange, availabilityVersion])

  const availableByCode = new Map(
    (availability ?? []).map((row) => [row.equipment_type_code, row.available]),
  )
  const openCodes = new Set(
    equipment
      .filter((item) => OPEN_STATUSES.includes(item.status))
      .map((item) => item.equipment_type_code),
  )
  const choices = (availability ?? []).filter((row) => !openCodes.has(row.equipment_type_code))
  const chosen = choices.find((row) => row.equipment_type_code === typeCode)
  const isNewQuantityAllowed = isQuantityAllowed(quantity, chosen?.available)
  const showsNewQuantityProblem = (isAddChecked || quantity !== '') && !isNewQuantityAllowed
  const editAvailable = editing ? availableByCode.get(editing.equipment_type_code) : undefined
  const isEditQuantityAllowed = isQuantityAllowed(editQuantity, editAvailable)
  const hasWaiting = equipment.some((item) => item.status === 'REQUESTED')

  function reloadAvailability() {
    setAvailabilityVersion((version) => version + 1)
  }

  async function handleAdd(submitted: FormEvent<HTMLFormElement>) {
    submitted.preventDefault()
    setIsAddChecked(true)
    if (chosen === undefined || !isNewQuantityAllowed) return
    setIsAdding(true)
    setAddError(null)
    try {
      await addEquipmentItem(
        eventId,
        {
          equipment_type_code: chosen.equipment_type_code,
          quantity: Number(quantity),
          technical_notes: trimmedNotes(notes),
        },
        chosen.equipment_type_name,
      )
      setTypeCode('')
      setQuantity('')
      setNotes('')
      setIsAddChecked(false)
      await onChanged()
    } catch (err) {
      setAddError(formatApiError(err))
    } finally {
      setIsAdding(false)
      reloadAvailability()
    }
  }

  function startEditing(item: EquipmentLine) {
    setEditing(item)
    setEditQuantity(String(item.quantity))
    setEditNotes(item.technical_notes ?? '')
    setEditError(null)
  }

  function stopEditing() {
    setEditing(null)
  }

  async function handleSave(submitted: FormEvent<HTMLFormElement>) {
    submitted.preventDefault()
    if (editing === null || !isEditQuantityAllowed) return
    // A partial edit: the notes travel only when they changed, so an item recorded with longer
    // notes than AC5 allows can still have its quantity corrected.
    const change: EquipmentItemChange = { quantity: Number(editQuantity) }
    const notesNow = trimmedNotes(editNotes)
    if (notesNow !== editing.technical_notes) change.technical_notes = notesNow
    setIsSaving(true)
    setEditError(null)
    try {
      await updateEquipmentItem(eventId, editing.id, change, editing.equipment_type_name)
      setEditing(null)
      await onChanged()
    } catch (err) {
      setEditError(formatApiError(err))
    } finally {
      setIsSaving(false)
      reloadAvailability()
    }
  }

  function askToRemove(item: EquipmentLine) {
    setRemoveError(null)
    setPendingRemoval(item)
  }

  function cancelRemove() {
    setPendingRemoval(null)
  }

  async function confirmRemove() {
    if (pendingRemoval === null) return
    setIsRemoving(true)
    setRemoveError(null)
    try {
      await removeEquipmentItem(eventId, pendingRemoval.id, pendingRemoval.equipment_type_name)
      setPendingRemoval(null)
      await onChanged()
    } catch (err) {
      setRemoveError(formatApiError(err))
    } finally {
      setIsRemoving(false)
      reloadAvailability()
    }
  }

  async function sendToTechnicalSupport() {
    setIsSubmitting(true)
    setSubmitError(null)
    try {
      await submitEquipment(eventId)
      await onChanged()
    } catch (err) {
      setSubmitError(formatApiError(err))
      reloadAvailability()
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className="card stack" aria-labelledby="equipment-heading">
      <h2 id="equipment-heading">Equipment requirements</h2>
      {equipment.length === 0 ? (
        <p className="muted">No equipment requested.</p>
      ) : (
        <ul className="check-list">
          {equipment.map((item) =>
            editing?.id === item.id ? (
              <li key={item.id}>
                <form
                  className="stack grow-text"
                  aria-label={`Edit ${item.equipment_type_name}`}
                  noValidate
                  onSubmit={handleSave}
                >
                  <strong>{item.equipment_type_name}</strong>
                  <label>
                    Quantity
                    <input
                      type="number"
                      inputMode="numeric"
                      value={editQuantity}
                      aria-invalid={isEditQuantityAllowed ? undefined : true}
                      aria-describedby={`${ids}-edit-quantity`}
                      onChange={(e) => setEditQuantity(e.target.value)}
                    />
                  </label>
                  <span id={`${ids}-edit-quantity`} className="small muted">
                    {editAvailable !== undefined && describeAvailable(editAvailable)}
                  </span>
                  {!isEditQuantityAllowed && (
                    <span className="field-error">
                      {ERROR_REGISTRY.EQUIPMENT_QUANTITY_INVALID.message}
                    </span>
                  )}
                  <label>
                    Technical notes
                    <textarea
                      rows={2}
                      maxLength={TECHNICAL_NOTES_MAX_LENGTH}
                      value={editNotes}
                      onChange={(e) => setEditNotes(e.target.value)}
                    />
                  </label>
                  {editError && (
                    <p role="alert" className="error">
                      {editError}
                    </p>
                  )}
                  <span className="row-actions">
                    <button type="submit" disabled={isSaving}>
                      {isSaving ? 'Saving…' : 'Save'}
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      disabled={isSaving}
                      onClick={stopEditing}
                    >
                      Cancel
                    </button>
                  </span>
                </form>
              </li>
            ) : (
              <li key={item.id}>
                <span className="grow-text">
                  {item.equipment_type_name}
                  {item.technical_notes && (
                    <>
                      <br />
                      <span className="small muted">{item.technical_notes}</span>
                    </>
                  )}
                  {item.status === 'PENDING' && item.submitted_at !== null && (
                    <>
                      <br />
                      <span className="small muted">
                        Sent {formatDateTime(item.submitted_at)}
                        {item.submitted_by_name !== null && ` by ${item.submitted_by_name}`}
                      </span>
                    </>
                  )}
                  {item.decided_at !== null && (
                    <>
                      <br />
                      <span className="small muted">
                        Decided {formatDateTime(item.decided_at)}
                        {item.decided_by_name !== null && ` by ${item.decided_by_name}`}
                      </span>
                    </>
                  )}
                  {item.status === 'UNAVAILABLE' && (
                    <>
                      <br />
                      <span className="small">{UNAVAILABLE_SENTENCE}</span>
                    </>
                  )}
                  {item.status === 'DECLINED' && (
                    <>
                      <br />
                      <span className="small">
                        Reason: {item.decision_reason ?? NO_REASON_RECORDED}
                      </span>
                    </>
                  )}
                </span>
                <span className="mono">×{item.quantity}</span>
                <StatusBadge status={item.status} label={STATUS_LABELS[item.status]} />
                {canChange && EDITABLE_STATUSES.includes(item.status) && (
                  <span className="row-actions">
                    <button
                      type="button"
                      className="secondary"
                      aria-label={`Edit ${item.equipment_type_name}`}
                      onClick={() => startEditing(item)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      aria-label={`Remove ${item.equipment_type_name}`}
                      onClick={() => askToRemove(item)}
                    >
                      Remove
                    </button>
                  </span>
                )}
              </li>
            ),
          )}
        </ul>
      )}

      {canChange && hasWaiting && (
        <div className="stack">
          {submitError && (
            <p role="alert" className="error">
              {submitError}
            </p>
          )}
          <div className="page-actions">
            <button type="button" disabled={isSubmitting} onClick={sendToTechnicalSupport}>
              {isSubmitting ? 'Sending…' : 'Submit to Technical Support'}
            </button>
          </div>
        </div>
      )}

      {canChange && (
        <form className="stack" aria-label="Add equipment" noValidate onSubmit={handleAdd}>
          <p className="eyebrow">Add equipment</p>
          {availabilityError && (
            <p role="alert" className="error">
              {availabilityError}
            </p>
          )}
          <label>
            Equipment type
            <select
              value={typeCode}
              aria-invalid={isAddChecked && chosen === undefined ? true : undefined}
              onChange={(e) => setTypeCode(e.target.value)}
            >
              <option value="">Choose a type</option>
              {choices.map((row) => (
                <option
                  key={row.equipment_type_code}
                  value={row.equipment_type_code}
                  disabled={row.available === 0}
                >
                  {row.equipment_type_name} ({row.available} available)
                </option>
              ))}
            </select>
          </label>
          {isAddChecked && chosen === undefined && (
            <span className="field-error">
              {ERROR_REGISTRY.EVENT_EQUIPMENT_TYPE_REQUIRED.message}
            </span>
          )}
          <label>
            Quantity
            <input
              type="number"
              inputMode="numeric"
              value={quantity}
              aria-invalid={showsNewQuantityProblem ? true : undefined}
              aria-describedby={`${ids}-new-quantity`}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </label>
          <span id={`${ids}-new-quantity`} className="small muted">
            {chosen !== undefined && describeAvailable(chosen.available)}
          </span>
          {showsNewQuantityProblem && (
            <span className="field-error">{ERROR_REGISTRY.EQUIPMENT_QUANTITY_INVALID.message}</span>
          )}
          <label>
            Technical notes
            <textarea
              rows={2}
              maxLength={TECHNICAL_NOTES_MAX_LENGTH}
              placeholder="Optional, e.g. HDMI and USB-C adaptors"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
          {addError && (
            <p role="alert" className="error">
              {addError}
            </p>
          )}
          <div className="page-actions">
            <button type="submit" className="secondary" disabled={isAdding}>
              {isAdding ? 'Adding…' : 'Add item'}
            </button>
          </div>
        </form>
      )}

      {pendingRemoval && (
        <ConfirmDialog
          title="Remove this equipment item?"
          confirmLabel="Remove"
          isBusy={isRemoving}
          error={removeError}
          onConfirm={confirmRemove}
          onCancel={cancelRemove}
        >
          <p>
            {pendingRemoval.equipment_type_name} ×{pendingRemoval.quantity} will be removed from
            this event, and the units it holds released.
          </p>
        </ConfirmDialog>
      )}
    </section>
  )
}
