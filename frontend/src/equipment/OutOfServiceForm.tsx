import { useId, useRef, useState, type FormEvent, type RefObject } from 'react'
import { formatApiError } from '../api/client'
import {
  OUT_OF_SERVICE_NOTES_MAX_LENGTH,
  addOutOfService,
  checkOutOfService,
  editOutOfService,
  type OutOfServiceInput,
  type OutOfServiceReason,
  type OutOfServiceRecord,
  type ShortHold,
} from '../api/equipment'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { RequiredMark } from '../components/RequiredMark'
import { ERROR_REGISTRY } from '../errors/registry'
import { formatSchedule, inputToInstant, instantToInput } from '../shared/format'
import { REASON_CODES, REASON_LABELS, describeHoldShort, hasStarted } from './outOfServiceLabels'

const WHOLE_NUMBER = /^\d+$/
const UNTIL_HINT = 'Leave blank to keep them out until the record is ended.'

/** What the form holds: the inputs' own strings. */
interface FormValues {
  units: string
  reason: OutOfServiceReason
  note: string
  from: string
  until: string
}

const BLANK: FormValues = { units: '', reason: 'DAMAGED', note: '', from: '', until: '' }

function valuesOf(record: OutOfServiceRecord | null): FormValues {
  if (record === null) return BLANK
  return {
    units: String(record.quantity),
    reason: record.reason,
    note: record.notes ?? '',
    from: instantToInput(record.starts_at),
    until: record.ends_at === null ? '' : instantToInput(record.ends_at),
  }
}

interface Problems {
  units: string | null
  from: string | null
  until: string | null
}

/** The first moment of the current minute: a start in it is not in the past (the server's rule). */
function startOfThisMinute(): number {
  const now = new Date()
  now.setSeconds(0, 0)
  return now.getTime()
}

/**
 * Story 16.2 AC3: what is wrong with the form before anything is sent - the units not a whole
 * number of at least 1, no start, a start in the past (only when it is a new one: a record in force
 * keeps its own), an end not after the start. How many the stock can spare is the server's to say.
 */
function problemsOf(values: FormValues, opened: FormValues, isEditing: boolean): Problems {
  const isNewStart = !isEditing || values.from !== opened.from
  let from: string | null = null
  if (values.from === '') from = ERROR_REGISTRY.OUT_OF_SERVICE_START_REQUIRED.message
  else if (isNewStart && Date.parse(inputToInstant(values.from)) < startOfThisMinute()) {
    from = ERROR_REGISTRY.OUT_OF_SERVICE_START_IN_PAST.message
  }
  const isEndBeforeStart =
    values.from !== '' &&
    values.until !== '' &&
    Date.parse(inputToInstant(values.until)) <= Date.parse(inputToInstant(values.from))
  return {
    units:
      WHOLE_NUMBER.test(values.units) && Number(values.units) >= 1
        ? null
        : ERROR_REGISTRY.OUT_OF_SERVICE_QUANTITY_INVALID.message,
    from,
    until: isEndBeforeStart ? ERROR_REGISTRY.OUT_OF_SERVICE_END_BEFORE_START.message : null,
  }
}

/** The record the form describes. An edit keeps the record's own instants for a time left as it
 *  was, since a record made through the API may hold seconds the form's minutes cannot show. */
function inputOf(
  values: FormValues,
  opened: FormValues,
  record: OutOfServiceRecord | null,
): OutOfServiceInput {
  const keepsStart = record !== null && values.from === opened.from
  const keepsEnd = record !== null && values.until === opened.until
  return {
    quantity: Number(values.units),
    reason: values.reason,
    notes: values.note.trim() || null,
    starts_at: keepsStart ? record.starts_at : inputToInstant(values.from),
    ends_at: keepsEnd ? record.ends_at : values.until === '' ? null : inputToInstant(values.until),
  }
}

/** Story 16.2 AC2: the fields an edit changed, so nothing else is sent. */
function changedFields(
  values: FormValues,
  opened: FormValues,
  input: OutOfServiceInput,
): Partial<OutOfServiceInput> {
  const changes: Partial<OutOfServiceInput> = {}
  if (values.units !== opened.units) changes.quantity = input.quantity
  if (values.reason !== opened.reason) changes.reason = input.reason
  if (values.note !== opened.note) changes.notes = input.notes
  if (values.from !== opened.from) changes.starts_at = input.starts_at
  if (values.until !== opened.until) changes.ends_at = input.ends_at
  return changes
}

export interface OutOfServiceFormProps {
  typeId: string
  typeName: string
  /** The record being edited, or null to record new units. The page keys the form on it. */
  editing: OutOfServiceRecord | null
  /** A record was saved: the page loads the type again and stops editing. */
  onSaved: () => void
  /** An edit was abandoned. */
  onCancel: () => void
}

/**
 * Story 16.2 - the Out of service form on a type's page. AC1: how many units, why, an optional
 * note, from when and, optionally, until when. AC3: the form's own checks stop a save before
 * anything is sent, each announced (`role="alert"`) and tied to its field, and focus goes to the
 * first. AC5: saving first asks the server, which checks the units against the stock and lists the
 * holds the record would leave short; when there are any, a dialog names them - event, dates, how
 * short, and the coordinator who will be told - and saves only once confirmed. The server checks
 * again on saving. AC2: editing opens the form on a record; one in force keeps its start, so the
 * field is not offered, and only what changed is sent.
 */
export function OutOfServiceForm({
  typeId,
  typeName,
  editing,
  onSaved,
  onCancel,
}: OutOfServiceFormProps) {
  const ids = useId()
  const opened = valuesOf(editing)
  // Decided once, as the form opens on the record: the page keys the form on it.
  const [isStartLocked] = useState(() => editing !== null && hasStarted(editing, Date.now()))
  const [values, setValues] = useState(opened)
  const [isChecked, setIsChecked] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [short, setShort] = useState<ShortHold[] | null>(null)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const unitsInput = useRef<HTMLInputElement>(null)
  const fromInput = useRef<HTMLInputElement>(null)
  const untilInput = useRef<HTMLInputElement>(null)

  const problems = isChecked ? problemsOf(values, opened, editing !== null) : null
  const headingId = `${ids}-heading`
  const problemId = (field: keyof Problems) => `${ids}-${field}-problem`

  function set<K extends keyof FormValues>(field: K, value: FormValues[K]) {
    setValues((current) => ({ ...current, [field]: value }))
  }

  async function save() {
    const input = inputOf(values, opened, editing)
    if (editing === null) await addOutOfService(typeId, typeName, input)
    else await editOutOfService(typeId, typeName, editing.id, changedFields(values, opened, input))
    setValues(BLANK)
    setIsChecked(false)
    onSaved()
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsChecked(true)
    setFormError(null)
    const found = problemsOf(values, opened, editing !== null)
    const inOrder: [string | null, RefObject<HTMLInputElement | null>][] = [
      [found.units, unitsInput],
      [found.from, fromInput],
      [found.until, untilInput],
    ]
    const firstProblem = inOrder.find(([problem]) => problem !== null)
    if (firstProblem !== undefined) {
      firstProblem[1].current?.focus()
      return
    }
    setIsSaving(true)
    try {
      const holds = await checkOutOfService(
        typeId,
        inputOf(values, opened, editing),
        editing?.id ?? null,
      )
      if (holds.length > 0) {
        setConfirmError(null)
        setShort(holds)
        return
      }
      await save()
    } catch (err) {
      setFormError(formatApiError(err))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleConfirmShort() {
    setIsSaving(true)
    setConfirmError(null)
    try {
      await save()
      setShort(null)
    } catch (err) {
      setConfirmError(formatApiError(err))
    } finally {
      setIsSaving(false)
    }
  }

  function handleCancelShort() {
    setShort(null)
  }

  return (
    <>
      <form
        className="card stack out-of-service-form"
        aria-labelledby={headingId}
        onSubmit={handleSubmit}
        noValidate
      >
        <h2 id={headingId}>
          {editing === null ? 'Take units out of service' : 'Edit units out of service'}
        </h2>
        <p className="small muted">
          Fields marked <RequiredMark /> are required.
        </p>
        <label>
          Units <RequiredMark />
          <input
            ref={unitsInput}
            type="number"
            inputMode="numeric"
            min={1}
            step={1}
            required
            aria-required="true"
            value={values.units}
            disabled={isSaving}
            aria-invalid={problems?.units ? true : undefined}
            aria-describedby={problems?.units ? problemId('units') : undefined}
            onChange={(e) => set('units', e.target.value)}
          />
          {problems?.units && (
            <span id={problemId('units')} role="alert" className="field-error">
              {problems.units}
            </span>
          )}
        </label>
        <label>
          Reason <RequiredMark />
          <select
            value={values.reason}
            disabled={isSaving}
            onChange={(e) => set('reason', e.target.value as OutOfServiceReason)}
          >
            {REASON_CODES.map((code) => (
              <option key={code} value={code}>
                {REASON_LABELS[code]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Note
          <textarea
            rows={2}
            maxLength={OUT_OF_SERVICE_NOTES_MAX_LENGTH}
            value={values.note}
            disabled={isSaving}
            onChange={(e) => set('note', e.target.value)}
          />
        </label>
        <label>
          From <RequiredMark />
          <input
            ref={fromInput}
            type="datetime-local"
            required
            aria-required="true"
            value={values.from}
            disabled={isSaving || isStartLocked}
            aria-invalid={problems?.from ? true : undefined}
            aria-describedby={problems?.from ? problemId('from') : undefined}
            onChange={(e) => set('from', e.target.value)}
          />
          {isStartLocked && (
            <span className="small muted">In force, so its start stays as it is.</span>
          )}
          {problems?.from && (
            <span id={problemId('from')} role="alert" className="field-error">
              {problems.from}
            </span>
          )}
        </label>
        <label>
          Until
          <input
            ref={untilInput}
            type="datetime-local"
            value={values.until}
            disabled={isSaving}
            aria-invalid={problems?.until ? true : undefined}
            aria-describedby={
              problems?.until ? `${ids}-until-hint ${problemId('until')}` : `${ids}-until-hint`
            }
            onChange={(e) => set('until', e.target.value)}
          />
          <span id={`${ids}-until-hint`} className="small muted">
            {UNTIL_HINT}
          </span>
          {problems?.until && (
            <span id={problemId('until')} role="alert" className="field-error">
              {problems.until}
            </span>
          )}
        </label>

        {formError && (
          <p role="alert" className="error">
            {formError}
          </p>
        )}

        <div className="cluster">
          <button type="submit" className="brand" disabled={isSaving}>
            {editing === null ? 'Take out of service' : 'Save changes'}
          </button>
          {editing !== null && (
            <button type="button" className="secondary" disabled={isSaving} onClick={onCancel}>
              Cancel
            </button>
          )}
        </div>
      </form>

      {short !== null && (
        <ConfirmDialog
          title="Some holds will be short"
          confirmLabel="Save anyway"
          tone="primary"
          isBusy={isSaving}
          error={confirmError}
          onConfirm={handleConfirmShort}
          onCancel={handleCancelShort}
        >
          <p>
            Saving leaves these events with fewer {typeName} units than they hold. Each event&apos;s
            coordinator is told, and the item shows as short on the event until enough are back.
          </p>
          <ul className="check-list">
            {short.map((hold) => (
              <li key={`${hold.event_id}-${hold.starts_at}`}>
                <span className="grow-text">
                  {hold.event_name}
                  <br />
                  <span className="small muted">
                    {formatSchedule(hold.starts_at, hold.ends_at)} ·{' '}
                    {hold.coordinator_name ?? 'No coordinator yet'}
                  </span>
                </span>
                <span className="mono">{describeHoldShort(hold.units_short, hold.units_held)}</span>
              </li>
            ))}
          </ul>
        </ConfirmDialog>
      )}
    </>
  )
}
