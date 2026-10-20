import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import {
  CHANGE_REASON_MAX_LENGTH,
  listChangeRequests,
  raiseChangeRequest,
  withdrawChangeRequest,
  type ChangeRequest,
  type ChangeRequestField,
  type ChangeRequestInput,
  type ChangeRequestWindow,
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
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { ERROR_REGISTRY } from '../errors/registry'
import { CHANGE_RETURNS_TO_PLANNING_STATUSES } from '../shared/eventStatus'
import { formatDateTime, inputToInstant, instantToInput } from '../shared/format'
import { ChangeRequestDecisionDialog } from './ChangeRequestDecisionDialog'
import { ChangeRequestChanges } from './ChangeRequestChanges'
import { ChangeRequestDecision } from './ChangeRequestDecision'
import { ChangeRequestImpactToggle } from './ChangeRequestImpact'
import { changeTitle, FIELD_LABELS, OUT_OF_DATE_NOTE, STATUS_LABELS } from './changeRequestValues'
import { LAST_VENUE_REQUIREMENT_HINT } from './eventRequestForm'

/** AC12 (team decision on the review of #125): why an approved event offers no change request any
 *  more - the backend's `CLOSED_BEFORE_SETUP_MESSAGE`, word for word. */
const CLOSED_NOTE = 'Change requests for this event closed 24 hours before its set-up time.'
/** Fix f19.1.1 (19.1 AC11, 19.2 AC8): what the organiser is told when asking to change an event
 *  that approval would send back to Planning - a Confirmed one. */
const BACK_TO_PLANNING_NOTE =
  'If this change is approved, the event goes back to Planning and needs a new safety check before it is confirmed again.'

const FIELDS = Object.keys(FIELD_LABELS) as ChangeRequestField[]
const WHOLE_NUMBER = /^\d+$/

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

/** Story 19.1 AC1, story 2.7 AC18 (fix f2.7.4): a blank venue requirement row - one the organiser
 *  adds, or the one an event with none starts with. */
function newRequirementDraft(): RequirementDraft {
  return { key: newDraftKey(), source: null, name: '', capacity: '', layoutCode: '' }
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
  /** AC1/AC5/AC7/AC11/AC12: the owning organiser, while the event is in Planning or Confirmed and
   *  more than 24 hours before its set-up time. */
  canRaise: boolean
  /** AC12: when change requests close, shown to the organiser of a Planning or Confirmed event;
   *  null for anyone else, or while it loads. */
  requestWindow: ChangeRequestWindow | null
  /** AC12: reading when change requests close failed, so none are offered; null otherwise. */
  requestWindowError: string | null
  /** AC9: the owning organiser may withdraw their pending requests. */
  canWithdraw: boolean
  /** Story 19.2 AC6: the assigned coordinator decides pending requests. */
  canDecide: boolean
  /** Story 19.2 AC2/AC7: an approval changed the event, or a refusal found it changed meanwhile,
   *  so the page loads it again. */
  onDecided: () => void
}

/** The decision dialog open on the event page: which request, and approving or rejecting it. */
interface OpenDecision {
  request: ChangeRequest
  outcome: 'APPROVED' | 'REJECTED'
}

/**
 * Story 19.1: the event's change requests, on the event page. The organiser and the assigned
 * coordinator see each one with what is there now, what is asked for, why, and its status (AC1).
 * While the event is in Planning or Confirmed (fix f19.1.1, AC11) the organiser asks for one field
 * to change - date and time, expected attendance, venue requirements or equipment - with a reason
 * (AC1, AC4), at most one pending per field (AC5), and withdraws a pending request after
 * confirming (AC9). On a Confirmed event the form says that approving the change sends the event
 * back to Planning for a new safety check (19.2 AC8). Nothing changes on the event until the
 * coordinator decides. The form checks the reason and the simple value rules before sending; the
 * server re-checks every rule (AC3, AC4).
 * Story 2.7 AC18 (fix f2.7.4): a change cannot leave the event without a venue requirement, so the
 * venue requirements editor keeps at least one row - the last one's Remove is disabled, with a hint
 * saying why - and an event with none starts it with one blank row to fill in.
 *
 * Story 19.2: the assigned coordinator approves or rejects each pending request here too, through
 * the dialog the queue shares (AC2, AC3). A decided request shows who decided and when, and a
 * rejection its reason, to the organiser as well.
 *
 * Story 19.3 AC1/AC6: the assigned coordinator alone can show, on each pending request, what
 * approving it would affect.
 */
export function ChangeRequestsSection({
  event,
  canRaise,
  requestWindow,
  requestWindowError,
  canWithdraw,
  canDecide,
  onDecided,
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
  const [isChecked, setIsChecked] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  const [pendingWithdraw, setPendingWithdraw] = useState<ChangeRequest | null>(null)
  const [isWithdrawing, setIsWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<string | null>(null)
  const [openDecision, setOpenDecision] = useState<OpenDecision | null>(null)

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
    setIsChecked(false)
    setSendError(null)
    setIsFormOpen(true)
  }

  function closeForm() {
    setIsFormOpen(false)
  }

  /**
   * AC1: choosing a field starts its new value from the event's current one. Story 2.7 AC18 (fix
   * f2.7.4): an event with no venue requirement - one approved before the fix - starts with one
   * blank row instead, since a change cannot leave it with none.
   */
  function chooseField(chosen: ChangeRequestField | '') {
    setField(chosen)
    setStartsAt(event.starts_at ? instantToInput(event.starts_at) : '')
    setEndsAt(event.ends_at ? instantToInput(event.ends_at) : '')
    setAttendance(event.expected_attendance === null ? '' : String(event.expected_attendance))
    setRequirements(
      event.venue_requirements.length > 0
        ? event.venue_requirements.map(requirementDraftFrom)
        : [newRequirementDraft()],
    )
    // An item kept, Cancelled, after an approved change removed it is no longer the event's
    // (story 19.2 AC5), as the backend's current value leaves it out.
    setEquipment(
      event.equipment
        .filter((line) => line.status !== 'CANCELLED')
        .map((line) => ({
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
    setRequirements((rows) => [...rows, newRequirementDraft()])
  }

  /** Story 2.7 AC18 (fix f2.7.4): never the last row - a change cannot leave the event without a
   *  venue requirement, so its Remove is disabled, and this leaves it be. */
  function removeRequirement(key: number) {
    setRequirements((rows) => (rows.length > 1 ? rows.filter((row) => row.key !== key) : rows))
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
    if (
      field === 'venue_requirements' &&
      requirements.some((row) => !isPositiveWholeNumber(row.capacity))
    ) {
      return {
        target: 'value',
        message: ERROR_REGISTRY.CHANGE_REQUEST_REQUIREMENT_PEOPLE_INVALID.message,
      }
    }
    if (field === 'equipment') {
      if (equipment.some((row) => row.code === '')) {
        return { target: 'value', message: ERROR_REGISTRY.EVENT_EQUIPMENT_TYPE_REQUIRED.message }
      }
      const codes = equipment.map((row) => row.code)
      if (new Set(codes).size !== codes.length) {
        return { target: 'value', message: ERROR_REGISTRY.EVENT_EQUIPMENT_DUPLICATE.message }
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
    setIsChecked(true)
    const found = findProblem()
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

  function closeDecision() {
    setOpenDecision(null)
  }

  /** Story 19.2 AC2/AC3: the click handler that opens the decision dialog on `request`, for
   *  `outcome`. */
  function openDecisionOn(request: ChangeRequest, outcome: OpenDecision['outcome']) {
    return function openDecisionDialog() {
      setOpenDecision({ request, outcome })
    }
  }

  /** Story 19.2 AC2/AC3: the decision is saved - list it as decided, and load the event again so
   *  an approved change shows on the page. */
  function finishDecision() {
    setOpenDecision(null)
    reloadRequests()
    onDecided()
  }

  /** Story 19.2 AC7: a decision refused because the request or its event moved on meanwhile -
   *  load both again, so the page shows what happened. */
  function refreshAfterRefusal() {
    reloadRequests()
    onDecided()
  }

  // Worked out from what is typed now, so it clears as soon as it is fixed once Send was pressed.
  const problem = isChecked ? findProblem() : null
  const problemId = `${ids}-problem`
  const describedBy = (target: FormProblem['target']) =>
    problem?.target === target ? problemId : undefined
  const isInvalid = (target: FormProblem['target']) =>
    problem?.target === target ? true : undefined
  // Story 2.7 AC18 (fix f2.7.4): the only row left cannot be removed, and a hint says why.
  const isOnlyRequirement = requirements.length === 1
  const lastRequirementHintId = `${ids}-last-requirement`

  return (
    <section className="card stack change-requests-section" aria-labelledby={`${ids}-heading`}>
      <div>
        <h2 id={`${ids}-heading`}>{canWithdraw ? 'Your change requests' : 'Change requests'}</h2>
        <p className="muted">
          {canWithdraw
            ? 'Requests you have submitted to change this event. You can withdraw a pending request if needed.'
            : 'Changes the organiser has asked for on this event.'}
          {canDecide && ' Approve or reject each pending one.'}
        </p>
      </div>
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
        <ul className="stack queue-list">
          {requests.map((request) => {
            const isPending = request.status === 'PENDING'
            const canDecideThis = canDecide && isPending
            const isOwnRequest = canWithdraw && request.requested_by_id === event.organiser_id
            return (
              <li key={request.id} className="card card-tight stack">
                <div className="item-card-header">
                  <div>
                    <h3 className="change-request-title">{changeTitle(request.field)}</h3>
                    <p className="small muted">
                      Requested on {formatDateTime(request.created_at)} by{' '}
                      {isOwnRequest ? 'you' : request.requested_by_name}
                    </p>
                  </div>
                  <StatusBadge status={request.status} label={STATUS_LABELS[request.status]} />
                </div>

                <ChangeRequestChanges request={request} references={references} />

                <div className="change-request-footer">
                  <div className="change-note">
                    <span className="change-note-icon">
                      <Icon name="message" />
                    </span>
                    <div>
                      <p className="change-note-label">
                        {isOwnRequest ? 'Your reason' : "Organiser's reason"}
                      </p>
                      <p className="wrap-anywhere">{request.reason}</p>
                    </div>
                  </div>
                  {isPending && (canWithdraw || canDecide) && (
                    <div className="cluster">
                      {canWithdraw && (
                        <button
                          type="button"
                          className="secondary button-with-icon"
                          onClick={() => askToWithdraw(request)}
                        >
                          <Icon name="trash" size={16} />
                          Withdraw request
                        </button>
                      )}
                      {canDecideThis && !request.is_out_of_date && (
                        <button
                          type="button"
                          className="brand button-with-icon"
                          onClick={openDecisionOn(request, 'APPROVED')}
                        >
                          <Icon name="check-circle" size={16} />
                          Approve
                        </button>
                      )}
                      {canDecideThis && (
                        <button
                          type="button"
                          className="danger-solid button-with-icon"
                          onClick={openDecisionOn(request, 'REJECTED')}
                        >
                          <Icon name="x-circle" size={16} />
                          Reject
                        </button>
                      )}
                    </div>
                  )}
                </div>

                <ChangeRequestDecision request={request} />

                {canDecideThis && request.is_out_of_date && (
                  <p className="warning">{OUT_OF_DATE_NOTE}</p>
                )}

                {canDecideThis && !request.is_out_of_date && (
                  <ChangeRequestImpactToggle request={request} />
                )}
              </li>
            )
          })}
        </ul>
      )}

      {requestWindowError && (
        <p role="alert" className="error">
          {requestWindowError}
        </p>
      )}
      {requestWindow?.is_open === false && <p className="form-hint">{CLOSED_NOTE}</p>}
      {requestWindow?.is_open && requestWindow.closes_at && (
        <p className="form-hint">
          Change requests close 24 hours before set-up, on {formatDateTime(requestWindow.closes_at)}
          .
        </p>
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
          {CHANGE_RETURNS_TO_PLANNING_STATUSES.includes(event.status) && (
            <p className="warning">{BACK_TO_PLANNING_NOTE}</p>
          )}
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
                      disabled={isOnlyRequirement}
                      aria-describedby={isOnlyRequirement ? lastRequirementHintId : undefined}
                      onClick={() => removeRequirement(row.key)}
                    >
                      Remove requirement {index + 1}
                    </button>
                  </div>
                </div>
              ))}
              {isOnlyRequirement && (
                <p id={lastRequirementHintId} className="form-hint">
                  {LAST_VENUE_REQUIREMENT_HINT}
                </p>
              )}
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

      {openDecision !== null && (
        <ChangeRequestDecisionDialog
          request={openDecision.request}
          outcome={openDecision.outcome}
          references={references}
          eventStatus={event.status}
          onCancel={closeDecision}
          onDecided={finishDecision}
          onRefused={refreshAfterRefusal}
        />
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
