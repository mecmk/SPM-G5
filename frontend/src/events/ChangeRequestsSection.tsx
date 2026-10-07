import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import {
  CHANGE_REASON_MAX_LENGTH,
  listChangeRequests,
  raiseChangeRequest,
  withdrawChangeRequest,
  type ChangeRequest,
  type ChangeRequestField,
  type ChangeRequestInput,
  type ChangeRequestStatus,
} from '../api/changeRequests'
import { ApiError, formatApiError } from '../api/client'
import {
  fetchEventReferenceData,
  type EquipmentInput,
  type EventDetail,
  type EventReferenceData,
  type VenueRequirement,
  type VenueRequirementInput,
} from '../api/events'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { StatusBadge } from '../components/StatusBadge'
import { ERROR_REGISTRY } from '../errors/registry'
import {
  formatDate,
  formatDateTime,
  formatSchedule,
  inputToInstant,
  instantToInput,
} from '../shared/format'

/** Story 19.1 AC1: how each requestable field is named, in the order the form offers them.
 *  Mirrors the backend's `FIELD_LABELS` (app/change_requests/service.py). */
const FIELD_LABELS: Record<ChangeRequestField, string> = {
  schedule: 'Date and time',
  expected_attendance: 'Expected attendance',
  venue_requirements: 'Venue requirements',
  equipment: 'Equipment',
}
const FIELDS = Object.keys(FIELD_LABELS) as ChangeRequestField[]

/** AC1/AC9: how each request status reads on the event page. */
const STATUS_LABELS: Record<ChangeRequestStatus, string> = {
  PENDING: 'Pending',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  WITHDRAWN: 'Withdrawn',
}
const WHOLE_NUMBER = /^\d+$/
const NOT_RECORDED = 'Not recorded'

/** The canonical value shapes the backend stores (app/change_requests/service.py). */
interface ScheduleValue {
  starts_at: string | null
  ends_at: string | null
}
interface RequirementValue {
  name: string | null
  capacity: number | null
  layout_code: string | null
}
interface EquipmentValue {
  equipment_type_code: string
  quantity: number
}

/** One venue requirement as the form edits it. An existing one keeps its own times and
 *  facilities, which this form does not edit, so proposing a new name or size never drops them. */
interface RequirementDraft {
  key: number
  source: VenueRequirement | null
  name: string
  capacity: string
  layoutCode: string
}

/** One equipment item as the form edits it; an existing one keeps its line and its notes. */
interface EquipmentDraft {
  key: number
  sourceId: string | null
  code: string
  quantity: string
  notes: string | null
}

/** What the form found wrong before sending, and which input to point at. */
interface FormProblem {
  target: 'field' | 'value' | 'reason'
  message: string
}

let nextDraftKey = 0
function newDraftKey(): number {
  nextDraftKey += 1
  return nextDraftKey
}

function isPositiveWholeNumber(value: string): boolean {
  return WHOLE_NUMBER.test(value.trim()) && Number(value) > 0
}

function namesByCode(items: { code: string; name: string }[] | undefined): Map<string, string> {
  return new Map((items ?? []).map((item) => [item.code, item.name]))
}

/** "Wed, 18 Nov 2026 · 09:00–17:00", or both dates when it runs over more than one day. */
function describeSchedule(value: ScheduleValue): string {
  if (value.starts_at === null || value.ends_at === null) return NOT_RECORDED
  if (formatDate(value.starts_at) === formatDate(value.ends_at)) {
    return formatSchedule(value.starts_at, value.ends_at)
  }
  return `${formatDateTime(value.starts_at)} – ${formatDateTime(value.ends_at)}`
}

/** AC1: a stored value in words, for the request's "now" and "requested" lines. */
function describeValue(
  field: ChangeRequestField,
  value: unknown,
  references: EventReferenceData | null,
): string {
  if (value === null || value === undefined) return NOT_RECORDED
  if (field === 'schedule') return describeSchedule(value as ScheduleValue)
  if (field === 'expected_attendance') return `${value as number} people`
  if (field === 'venue_requirements') {
    const layouts = namesByCode(references?.layouts)
    const requirements = value as RequirementValue[]
    if (requirements.length === 0) return 'No venue requirements'
    return requirements
      .map((item) => {
        const layout = item.layout_code
          ? `, ${layouts.get(item.layout_code) ?? item.layout_code}`
          : ''
        return `${item.name ?? 'Unnamed'} (${item.capacity ?? '?'} people${layout})`
      })
      .join('; ')
  }
  const types = namesByCode(references?.equipment_types)
  const lines = value as EquipmentValue[]
  if (lines.length === 0) return 'No equipment'
  return lines
    .map(
      (line) =>
        `${types.get(line.equipment_type_code) ?? line.equipment_type_code} ×${line.quantity}`,
    )
    .join('; ')
}

/**
 * AC4: a refusal in the server's own words. A venue requirement the server refuses comes back
 * located like a validation error (story 2.7 AC11), so its sentence is shown without the field
 * path `formatApiError` would put in front of it.
 */
function describeRefusal(err: unknown): string {
  if (err instanceof ApiError && Array.isArray(err.detail)) {
    const sentences = (err.detail as { msg?: unknown }[])
      .map((issue) => issue.msg)
      .filter((msg): msg is string => typeof msg === 'string')
    if (sentences.length > 0) return sentences.join(' ')
  }
  return formatApiError(err)
}

function requirementDraftFrom(requirement: VenueRequirement): RequirementDraft {
  return {
    key: newDraftKey(),
    source: requirement,
    name: requirement.name ?? '',
    capacity: requirement.capacity === null ? '' : String(requirement.capacity),
    layoutCode: requirement.layout_code ?? '',
  }
}

function requirementInputFrom(draft: RequirementDraft): VenueRequirementInput {
  const { source } = draft
  return {
    id: source?.id ?? null,
    name: draft.name.trim() || null,
    capacity: draft.capacity.trim() === '' ? null : Number(draft.capacity),
    starts_at: source?.starts_at ?? null,
    ends_at: source?.ends_at ?? null,
    layout_code: draft.layoutCode || null,
    facilities: (source?.facilities ?? []).map((facility) => ({
      code: facility.code,
      quantity: facility.quantity,
      notes: facility.notes,
    })),
    notes: source?.notes ?? null,
  }
}

function equipmentInputFrom(draft: EquipmentDraft): EquipmentInput {
  return {
    id: draft.sourceId,
    equipment_type_code: draft.code,
    quantity: Number(draft.quantity),
    technical_notes: draft.notes,
  }
}

export interface ChangeRequestsSectionProps {
  event: EventDetail
  /** AC1/AC5/AC7: the owning organiser, while the event is in Planning. */
  canRaise: boolean
  /** AC9: the owning organiser may withdraw their pending requests. */
  canWithdraw: boolean
}

/**
 * Story 19.1: the event's change requests, on the event page. The organiser and the assigned
 * coordinator see each one with what is there now, what is asked for, why, and its status (AC1).
 * While the event is in Planning the organiser asks for one field to change - date and time,
 * expected attendance, venue requirements or equipment - with a reason (AC1, AC4), at most one
 * pending per field (AC5), and withdraws a pending request after confirming (AC9). Nothing
 * changes on the event until the coordinator decides (stories 19.2-19.5). The form checks the
 * reason and the simple value rules before sending; the server re-checks every rule (AC3, AC4).
 */
export function ChangeRequestsSection({
  event,
  canRaise,
  canWithdraw,
}: ChangeRequestsSectionProps) {
  const ids = useId()
  const reasonInput = useRef<HTMLTextAreaElement>(null)
  const valueInput = useRef<HTMLInputElement>(null)
  const fieldSelect = useRef<HTMLSelectElement>(null)
  const [requests, setRequests] = useState<ChangeRequest[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [listVersion, setListVersion] = useState(0)
  const [references, setReferences] = useState<EventReferenceData | null>(null)
  const [referencesError, setReferencesError] = useState<string | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [field, setField] = useState<ChangeRequestField | ''>('')
  const [startsAt, setStartsAt] = useState('')
  const [endsAt, setEndsAt] = useState('')
  const [attendance, setAttendance] = useState('')
  const [requirements, setRequirements] = useState<RequirementDraft[]>([])
  const [equipment, setEquipment] = useState<EquipmentDraft[]>([])
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState<FormProblem | null>(null)
  const [isSending, setIsSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  const [pendingWithdraw, setPendingWithdraw] = useState<ChangeRequest | null>(null)
  const [isWithdrawing, setIsWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listChangeRequests(event.id)
      .then((data) => {
        if (cancelled) return
        setRequests(data)
        setListError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setListError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [event.id, listVersion])

  useEffect(() => {
    let cancelled = false
    fetchEventReferenceData()
      .then((data) => {
        if (!cancelled) setReferences(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setReferencesError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const pendingFields = new Set(
    (requests ?? []).filter((request) => request.status === 'PENDING').map((r) => r.field),
  )

  function reloadRequests() {
    setListVersion((version) => version + 1)
  }

  function openForm() {
    setField('')
    setReason('')
    setProblem(null)
    setSendError(null)
    setIsFormOpen(true)
  }

  function closeForm() {
    setIsFormOpen(false)
  }

  /** AC1: choosing a field starts its new value from the event's current one. */
  function chooseField(chosen: ChangeRequestField | '') {
    setField(chosen)
    setProblem(null)
    setStartsAt(event.starts_at ? instantToInput(event.starts_at) : '')
    setEndsAt(event.ends_at ? instantToInput(event.ends_at) : '')
    setAttendance(event.expected_attendance === null ? '' : String(event.expected_attendance))
    setRequirements(event.venue_requirements.map(requirementDraftFrom))
    setEquipment(
      event.equipment.map((line) => ({
        key: newDraftKey(),
        sourceId: line.id,
        code: line.equipment_type_code,
        quantity: String(line.quantity),
        notes: line.technical_notes,
      })),
    )
  }

  function updateRequirement(key: number, change: Partial<RequirementDraft>) {
    setRequirements((rows) => rows.map((row) => (row.key === key ? { ...row, ...change } : row)))
  }

  function addRequirement() {
    setRequirements((rows) => [
      ...rows,
      { key: newDraftKey(), source: null, name: '', capacity: '', layoutCode: '' },
    ])
  }

  function removeRequirement(key: number) {
    setRequirements((rows) => rows.filter((row) => row.key !== key))
  }

  function updateEquipment(key: number, change: Partial<EquipmentDraft>) {
    setEquipment((rows) => rows.map((row) => (row.key === key ? { ...row, ...change } : row)))
  }

  function addEquipment() {
    setEquipment((rows) => [
      ...rows,
      { key: newDraftKey(), sourceId: null, code: '', quantity: '', notes: null },
    ])
  }

  function removeEquipment(key: number) {
    setEquipment((rows) => rows.filter((row) => row.key !== key))
  }

  /** AC4: the checks made here before sending; the server re-checks all of them and more. */
  function findProblem(): FormProblem | null {
    if (field === '') {
      return { target: 'field', message: ERROR_REGISTRY.CHANGE_REQUEST_FIELD_REQUIRED.message }
    }
    if (field === 'schedule') {
      if (startsAt === '' || endsAt === '') {
        return { target: 'value', message: ERROR_REGISTRY.EVENT_DATE_INCOMPLETE.message }
      }
      if (endsAt <= startsAt) {
        return { target: 'value', message: ERROR_REGISTRY.EVENT_END_BEFORE_START.message }
      }
    }
    if (field === 'expected_attendance' && !isPositiveWholeNumber(attendance)) {
      return { target: 'value', message: ERROR_REGISTRY.EVENT_ATTENDANCE_INVALID.message }
    }
    if (field === 'equipment') {
      if (equipment.some((row) => row.code === '')) {
        return { target: 'value', message: ERROR_REGISTRY.EVENT_EQUIPMENT_TYPE_REQUIRED.message }
      }
      if (equipment.some((row) => !isPositiveWholeNumber(row.quantity))) {
        return { target: 'value', message: ERROR_REGISTRY.EVENT_QUANTITY_INVALID.message }
      }
    }
    if (reason.trim() === '') {
      return { target: 'reason', message: ERROR_REGISTRY.CHANGE_REQUEST_REASON_REQUIRED.message }
    }
    return null
  }

  function inputFor(chosen: ChangeRequestField): ChangeRequestInput {
    const why = reason.trim()
    if (chosen === 'schedule') {
      return {
        field: chosen,
        proposed: { starts_at: inputToInstant(startsAt), ends_at: inputToInstant(endsAt) },
        reason: why,
      }
    }
    if (chosen === 'expected_attendance') {
      return { field: chosen, proposed: Number(attendance), reason: why }
    }
    if (chosen === 'venue_requirements') {
      return { field: chosen, proposed: requirements.map(requirementInputFrom), reason: why }
    }
    return { field: chosen, proposed: equipment.map(equipmentInputFrom), reason: why }
  }

  async function handleSend(submitted: FormEvent<HTMLFormElement>) {
    submitted.preventDefault()
    const found = findProblem()
    setProblem(found)
    if (found !== null) {
      if (found.target === 'reason') reasonInput.current?.focus()
      else if (found.target === 'field') fieldSelect.current?.focus()
      else valueInput.current?.focus()
      return
    }
    if (field === '') return
    setIsSending(true)
    setSendError(null)
    try {
      await raiseChangeRequest(event.id, inputFor(field), FIELD_LABELS[field].toLowerCase())
      setIsFormOpen(false)
      reloadRequests()
    } catch (err) {
      setSendError(describeRefusal(err))
      reloadRequests()
    } finally {
      setIsSending(false)
    }
  }

  function askToWithdraw(request: ChangeRequest) {
    setWithdrawError(null)
    setPendingWithdraw(request)
  }

  function cancelWithdraw() {
    setPendingWithdraw(null)
  }

  async function confirmWithdraw() {
    if (pendingWithdraw === null) return
    setIsWithdrawing(true)
    setWithdrawError(null)
    try {
      await withdrawChangeRequest(
        event.id,
        pendingWithdraw.id,
        FIELD_LABELS[pendingWithdraw.field].toLowerCase(),
      )
      setPendingWithdraw(null)
    } catch (err) {
      setWithdrawError(formatApiError(err))
    } finally {
      setIsWithdrawing(false)
      reloadRequests()
    }
  }

  const problemId = `${ids}-problem`
  const describedBy = (target: FormProblem['target']) =>
    problem?.target === target ? problemId : undefined
  const isInvalid = (target: FormProblem['target']) =>
    problem?.target === target ? true : undefined

  return (
    <section className="card stack" aria-labelledby={`${ids}-heading`}>
      <h2 id={`${ids}-heading`}>Change requests</h2>
      {listError && (
        <p role="alert" className="error">
          {listError}
        </p>
      )}
      {referencesError && (
        <p role="alert" className="error">
          {referencesError}
        </p>
      )}
      {requests !== null && requests.length === 0 && (
        <p className="muted">No change requests for this event.</p>
      )}
      {requests !== null && requests.length > 0 && (
        <ul className="check-list">
          {requests.map((request) => (
            <li key={request.id}>
              <span className="grow-text change-request-text">
                <strong>{FIELD_LABELS[request.field]}</strong>
                <br />
                <span className="small">
                  Now: {describeValue(request.field, request.current_value, references)}
                </span>
                <br />
                <span className="small">
                  Requested: {describeValue(request.field, request.proposed_value, references)}
                </span>
                <br />
                <span className="small muted wrap-anywhere">
                  “{request.reason}” · {request.requested_by_name},{' '}
                  {formatDateTime(request.created_at)}
                </span>
              </span>
              <StatusBadge status={request.status} label={STATUS_LABELS[request.status]} />
              {canWithdraw && request.status === 'PENDING' && (
                <button type="button" className="secondary" onClick={() => askToWithdraw(request)}>
                  Withdraw
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {canRaise && !isFormOpen && (
        <div className="page-actions">
          <button type="button" className="secondary" onClick={openForm}>
            Request a change
          </button>
        </div>
      )}

      {canRaise && isFormOpen && (
        <form className="stack" aria-label="Request a change" noValidate onSubmit={handleSend}>
          <p className="form-hint">
            Nothing changes until the coordinator decides. To update the point of contact, use
            Update point of contact above.
          </p>
          <label>
            What to change
            <select
              ref={fieldSelect}
              value={field}
              aria-invalid={isInvalid('field')}
              aria-describedby={describedBy('field')}
              onChange={(e) => chooseField(e.target.value as ChangeRequestField | '')}
            >
              <option value="">Choose a field</option>
              {FIELDS.map((option) => (
                <option key={option} value={option} disabled={pendingFields.has(option)}>
                  {FIELD_LABELS[option]}
                  {pendingFields.has(option) ? ' (waiting for a decision)' : ''}
                </option>
              ))}
            </select>
          </label>

          {field === 'schedule' && (
            <div className="form-grid">
              <label>
                New start
                <input
                  ref={valueInput}
                  type="datetime-local"
                  value={startsAt}
                  aria-invalid={isInvalid('value')}
                  aria-describedby={describedBy('value')}
                  onChange={(e) => setStartsAt(e.target.value)}
                />
              </label>
              <label>
                New end
                <input
                  type="datetime-local"
                  value={endsAt}
                  min={startsAt || undefined}
                  aria-invalid={isInvalid('value')}
                  aria-describedby={describedBy('value')}
                  onChange={(e) => setEndsAt(e.target.value)}
                />
              </label>
            </div>
          )}

          {field === 'expected_attendance' && (
            <label>
              New expected attendance
              <input
                ref={valueInput}
                type="number"
                inputMode="numeric"
                min={1}
                value={attendance}
                aria-invalid={isInvalid('value')}
                aria-describedby={describedBy('value')}
                onChange={(e) => setAttendance(e.target.value)}
              />
            </label>
          )}

          {field === 'venue_requirements' && (
            <div className="stack">
              {requirements.length === 0 && (
                <p className="muted">No venue requirements - the event will need no venue.</p>
              )}
              {requirements.map((row, index) => (
                <div key={row.key} className="stack">
                  <div className="form-grid">
                    <label>
                      Requirement {index + 1} name
                      <input
                        ref={index === 0 ? valueInput : undefined}
                        value={row.name}
                        maxLength={100}
                        onChange={(e) => updateRequirement(row.key, { name: e.target.value })}
                      />
                    </label>
                    <label>
                      Requirement {index + 1} number of people
                      <input
                        type="number"
                        inputMode="numeric"
                        min={1}
                        value={row.capacity}
                        onChange={(e) => updateRequirement(row.key, { capacity: e.target.value })}
                      />
                    </label>
                    <label>
                      Requirement {index + 1} room layout
                      <select
                        value={row.layoutCode}
                        onChange={(e) => updateRequirement(row.key, { layoutCode: e.target.value })}
                      >
                        <option value="">Any layout</option>
                        {(references?.layouts ?? []).map((layout) => (
                          <option key={layout.code} value={layout.code}>
                            {layout.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div className="page-actions">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => removeRequirement(row.key)}
                    >
                      Remove requirement {index + 1}
                    </button>
                  </div>
                </div>
              ))}
              <div className="page-actions">
                <button type="button" className="secondary" onClick={addRequirement}>
                  Add a venue requirement
                </button>
              </div>
            </div>
          )}

          {field === 'equipment' && (
            <div className="stack">
              {equipment.length === 0 && (
                <p className="muted">No equipment - the event will need none.</p>
              )}
              {equipment.map((row, index) => (
                <div key={row.key} className="form-grid">
                  <label>
                    Item {index + 1} type
                    <select
                      value={row.code}
                      onChange={(e) => updateEquipment(row.key, { code: e.target.value })}
                    >
                      <option value="">Choose a type</option>
                      {(references?.equipment_types ?? []).map((type) => (
                        <option key={type.code} value={type.code}>
                          {type.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Item {index + 1} quantity
                    <input
                      type="number"
                      inputMode="numeric"
                      min={1}
                      value={row.quantity}
                      onChange={(e) => updateEquipment(row.key, { quantity: e.target.value })}
                    />
                  </label>
                  <div className="page-actions">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => removeEquipment(row.key)}
                    >
                      Remove item {index + 1}
                    </button>
                  </div>
                </div>
              ))}
              <div className="page-actions">
                <button type="button" className="secondary" onClick={addEquipment}>
                  Add equipment
                </button>
              </div>
            </div>
          )}

          <label>
            Reason for the change
            <textarea
              ref={reasonInput}
              rows={3}
              maxLength={CHANGE_REASON_MAX_LENGTH}
              placeholder="Why does the event need this change?"
              value={reason}
              aria-invalid={isInvalid('reason')}
              aria-describedby={describedBy('reason')}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          {problem !== null && (
            <span id={problemId} className="field-error">
              {problem.message}
            </span>
          )}
          {sendError && (
            <p role="alert" className="error">
              {sendError}
            </p>
          )}
          <div className="page-actions">
            <button type="submit" disabled={isSending}>
              {isSending ? 'Sending…' : 'Send change request'}
            </button>
            <button type="button" className="secondary" disabled={isSending} onClick={closeForm}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {pendingWithdraw && (
        <ConfirmDialog
          title="Withdraw this change request?"
          confirmLabel="Withdraw"
          isBusy={isWithdrawing}
          error={withdrawError}
          onConfirm={confirmWithdraw}
          onCancel={cancelWithdraw}
        >
          <p>
            Your request to change the {FIELD_LABELS[pendingWithdraw.field].toLowerCase()} will be
            withdrawn, and the coordinator told. You can ask again afterwards.
          </p>
        </ConfirmDialog>
      )}
    </section>
  )
}
