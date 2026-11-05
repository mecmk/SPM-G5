import { useCallback, useId, useMemo, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  listEquipmentHolds,
  type EquipmentHoldFilters,
  type EquipmentHoldGroup,
  type EquipmentHoldType,
} from '../api/equipment'
import { EmptyState } from '../components/EmptyState'
import type { EventCardBackState } from '../components/EventCard'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { ERROR_REGISTRY } from '../errors/registry'
import { LoadingState } from '../layout/LoadingState'
import {
  EQUIPMENT_HOLDS_PARAMS,
  EQUIPMENT_HOLDS_PATH,
  EQUIPMENT_HOLDS_TITLE,
  equipmentRequestPath,
} from '../routes'
import {
  HOLD_LENGTH_SENTENCE,
  describeItemShort,
  equipmentStatusLabel,
} from '../shared/equipmentStatus'
import { formatDateTime, isReadableDate, todayAsDateInput } from '../shared/format'
import { queuePath } from '../shared/queueView'
import { useLoaded } from '../shared/useLoaded'
import { ErrorToast } from '../components/ErrorToast'

/** The type filter's value for every type. */
const ALL_TYPES = ''

/** AC3: the filters the page address holds; blank for one not set. */
function readFilters(params: URLSearchParams): EquipmentHoldFilters {
  return {
    type: params.get(EQUIPMENT_HOLDS_PARAMS.type) ?? ALL_TYPES,
    from: params.get(EQUIPMENT_HOLDS_PARAMS.from) ?? '',
    to: params.get(EQUIPMENT_HOLDS_PARAMS.to) ?? '',
  }
}

/** The page address's query for `filters`, holding only the ones set. */
function filtersQuery(filters: EquipmentHoldFilters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.type !== ALL_TYPES) params.set(EQUIPMENT_HOLDS_PARAMS.type, filters.type)
  if (filters.from !== '') params.set(EQUIPMENT_HOLDS_PARAMS.from, filters.from)
  if (filters.to !== '') params.set(EQUIPMENT_HOLDS_PARAMS.to, filters.to)
  return params
}

interface Problems {
  from: string | null
  to: string | null
}

/** Which dates hold one started but not finished. The picker reports such a date as blank, which
 *  would leave that side of the range open, so only the input itself can tell
 *  (`validity.badInput`). */
interface UnfinishedDates {
  from: boolean
  to: boolean
}

const NO_UNFINISHED_DATES: UnfinishedDates = { from: false, to: false }

/** The form's two dates, in the order their problems are announced and focused. */
type DateField = keyof UnfinishedDates
const DATE_FIELDS: readonly DateField[] = ['from', 'to']

/** One of the form's date inputs, by its name. */
function dateInput(form: HTMLFormElement, field: DateField): HTMLInputElement {
  return form.elements.namedItem(field) as HTMLInputElement
}

/** Which of the form's dates hold one started but not finished, as the inputs report it now. */
function unfinishedDatesOf(form: HTMLFormElement): UnfinishedDates {
  return {
    from: dateInput(form, 'from').validity.badInput,
    to: dateInput(form, 'to').validity.badInput,
  }
}

/**
 * AC3: what is wrong with the range before anything is sent - a date not finished or not readable,
 * a start before today, an end before the start, or with no start an end before today. The server
 * refuses the same ranges with the same sentences. Dates compare as text: each is `YYYY-MM-DD`.
 */
function problemsOf(
  values: EquipmentHoldFilters,
  unfinished: UnfinishedDates,
  today: string,
): Problems {
  let from: string | null = null
  if (unfinished.from) from = ERROR_REGISTRY.EQUIPMENT_HOLDS_DATE_INCOMPLETE.message
  else if (values.from !== '' && !isReadableDate(values.from)) {
    from = ERROR_REGISTRY.EQUIPMENT_HOLDS_DATE_INVALID.message
  } else if (values.from !== '' && values.from < today) {
    from = ERROR_REGISTRY.EQUIPMENT_HOLDS_START_BEFORE_TODAY.message
  }
  let to: string | null = null
  if (unfinished.to) to = ERROR_REGISTRY.EQUIPMENT_HOLDS_DATE_INCOMPLETE.message
  else if (values.to !== '' && !isReadableDate(values.to)) {
    to = ERROR_REGISTRY.EQUIPMENT_HOLDS_DATE_INVALID.message
  } else if (values.to !== '' && isReadableDate(values.from) && values.to < values.from) {
    to = ERROR_REGISTRY.EQUIPMENT_HOLDS_END_BEFORE_START.message
  } else if (values.to !== '' && values.from === '' && values.to < today) {
    to = ERROR_REGISTRY.EQUIPMENT_HOLDS_END_BEFORE_TODAY.message
  }
  return { from, to }
}

interface HoldFiltersFormProps {
  /** The filters the page shows now. The page keys the form on them, so it starts from them. */
  applied: EquipmentHoldFilters
  /** Every active type, for the type filter. */
  types: EquipmentHoldType[]
  onApply: (filters: EquipmentHoldFilters) => void
  onClear: () => void
}

/**
 * Story 17.3 AC3 - the schedule's filters: a type, and a range of days from and to. Show holds
 * applies them, once the form's own checks pass: each problem is announced (`role="alert"`) and
 * tied to its date, focus goes to the first, and nothing is sent. Clear filters shows every hold.
 * A type the address names but the list does not offer - one the server refused, or any while the
 * types load - is still what Show holds sends, so the box offers it, by its code.
 */
function HoldFiltersForm({ applied, types, onApply, onClear }: HoldFiltersFormProps) {
  const ids = useId()
  const [values, setValues] = useState(applied)
  const [unfinished, setUnfinished] = useState(NO_UNFINISHED_DATES)
  const [isChecked, setIsChecked] = useState(false)
  const today = todayAsDateInput()
  const problems = isChecked ? problemsOf(values, unfinished, today) : null
  const problemId = (field: keyof Problems) => `${ids}-${field}-problem`
  const isTypeOffered = values.type === ALL_TYPES || types.some((kind) => kind.code === values.type)

  function set(field: keyof EquipmentHoldFilters, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
  }

  /** A date the picker has changed: finished, cleared or still being typed. */
  function setDate(field: DateField, input: HTMLInputElement) {
    set(field, input.value)
    setUnfinished((current) => ({ ...current, [field]: input.validity.badInput }))
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    setIsChecked(true)
    // Typing part of a date changes nothing the form is told of, so look again now.
    const unfinishedNow = unfinishedDatesOf(form)
    setUnfinished(unfinishedNow)
    const found = problemsOf(values, unfinishedNow, today)
    const firstProblem = DATE_FIELDS.find((field) => found[field] !== null)
    if (firstProblem !== undefined) {
      dateInput(form, firstProblem).focus()
      return
    }
    onApply(values)
  }

  return (
    <form
      className="filter-bar equipment-hold-filters"
      aria-label="Filter holds"
      onSubmit={handleSubmit}
      noValidate
    >
      <label>
        Equipment type
        <select value={values.type} onChange={(e) => set('type', e.target.value)}>
          <option value={ALL_TYPES}>All types</option>
          {!isTypeOffered && <option value={values.type}>{values.type}</option>}
          {types.map((kind) => (
            <option key={kind.code} value={kind.code}>
              {kind.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        From date
        <input
          name="from"
          type="date"
          min={today}
          value={values.from}
          aria-invalid={problems?.from ? true : undefined}
          aria-describedby={problems?.from ? problemId('from') : undefined}
          onChange={(e) => setDate('from', e.target)}
        />
        {problems?.from && (
          <span id={problemId('from')} role="alert" className="field-error">
            {problems.from}
          </span>
        )}
      </label>
      <label>
        To date
        <input
          name="to"
          type="date"
          min={isReadableDate(values.from) ? values.from : today}
          value={values.to}
          aria-invalid={problems?.to ? true : undefined}
          aria-describedby={problems?.to ? problemId('to') : undefined}
          onChange={(e) => setDate('to', e.target)}
        />
        {problems?.to && (
          <span id={problemId('to')} role="alert" className="field-error">
            {problems.to}
          </span>
        )}
      </label>
      <div className="cluster">
        <button type="submit" className="brand">
          Show holds
        </button>
        <button type="button" className="secondary" onClick={onClear}>
          Clear filters
        </button>
      </div>
    </form>
  )
}

interface HoldGroupSectionProps {
  group: EquipmentHoldGroup
  /** Whether a date range is applied, which the empty message names. */
  isRanged: boolean
  /** Story 17.3 AC4: what a request page's back link returns to - the schedule as filtered. */
  backToSchedule: EventCardBackState
}

/**
 * Story 17.3 AC1 - one equipment type's holds, soonest first (the server's order): the event, the
 * quantity still held, from and to, and the item's status as the event page words it. AC4: each
 * hold opens its request's page. AC6: no holds says so.
 */
function HoldGroupSection({ group, isRanged, backToSchedule }: HoldGroupSectionProps) {
  const headingId = useId()
  return (
    <section className="card stack equipment-hold-group" aria-labelledby={headingId}>
      <h2 id={headingId}>{group.equipment_type_name}</h2>
      {group.holds.length === 0 ? (
        <EmptyState>{isRanged ? 'No holds in this range.' : 'No current holds.'}</EmptyState>
      ) : (
        <div className="table-wrap">
          <table aria-label={`${group.equipment_type_name} holds`} className="equipment-holds">
            <thead>
              <tr>
                <th>Event</th>
                <th>Quantity</th>
                <th>From</th>
                <th>To</th>
                <th>Status</th>
                <th>
                  <span className="visually-hidden">Request</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {group.holds.map((hold) => (
                <tr key={hold.id}>
                  <td>{hold.event_name}</td>
                  <td className="mono">{hold.quantity}</td>
                  <td>{formatDateTime(hold.starts_at)}</td>
                  <td>{formatDateTime(hold.ends_at)}</td>
                  <td>
                    <StatusBadge
                      status={hold.status}
                      label={equipmentStatusLabel(hold.status, hold.units_short > 0)}
                    />
                    {hold.units_short > 0 && (
                      <>
                        <br />
                        <span className="small item-short">
                          {describeItemShort(hold.units_short, hold.quantity)}
                        </span>
                      </>
                    )}
                  </td>
                  <td>
                    <Link
                      to={equipmentRequestPath(hold.item_id)}
                      state={backToSchedule}
                      className="link"
                    >
                      View request →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/**
 * Story 17.3 - Technical Support's schedule of every equipment hold, grouped by equipment type.
 * AC1: every active type, by name, each with its current holds soonest first. AC2 (fix f17.3.2):
 * an item not yet sent to Technical Support is not listed, though its hold still takes units.
 * AC3: filtered by type and by a range of days, the filters kept in the page address, so a reload
 * and a request page's link back keep them; a
 * range the form refuses sends nothing. AC4: read-only - a hold opens its request's page,
 * where any decision is made (16.1). AC5: the server lists only holds still reserved and not yet
 * ended. AC6: a type with no holds says so. AC7: App.tsx guards the route with equipment:manage,
 * and the backend refuses everyone else.
 * Story 16.2 AC9 (fix f16.2.2): a hold that units out of service leave short is marked as on its
 * event's page, and an accepted one reads Accepted, not Accepted (reserved).
 */
export function EquipmentHoldsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const query = filtersQuery(readFilters(searchParams)).toString()
  const applied = useMemo(() => readFilters(new URLSearchParams(query)), [query])
  const loadSchedule = useCallback(() => listEquipmentHolds(applied), [applied])
  const { data: schedule, error, isLoading, isStale } = useLoaded(loadSchedule)
  const isRanged = applied.from !== '' || applied.to !== ''
  const backToSchedule: EventCardBackState = {
    from: queuePath(EQUIPMENT_HOLDS_PATH, query),
    fromLabel: EQUIPMENT_HOLDS_TITLE,
  }

  function applyFilters(filters: EquipmentHoldFilters) {
    setSearchParams(filtersQuery(filters))
  }

  function clearFilters() {
    setSearchParams(new URLSearchParams())
  }

  return (
    <div className="page page-wide">
      <p className="eyebrow">Equipment</p>
      <PageHeader
        title={EQUIPMENT_HOLDS_TITLE}
        subtitle="Every unit held for an event, by equipment type: which event, how many, and from when to when."
      />
      {/* Fix f17.3.1 (AC8): a hold has no expiry, so say what ends one. */}
      <p className="muted">{HOLD_LENGTH_SENTENCE}</p>

      <div className="stack">
        <HoldFiltersForm
          key={query}
          applied={applied}
          types={schedule?.types ?? []}
          onApply={applyFilters}
          onClear={clearFilters}
        />

        {error && <ErrorToast message={error} />}
        {(isLoading || (isStale && error === null)) && (
          <LoadingState label="Loading equipment holds…" />
        )}

        {schedule !== null &&
          !isStale &&
          schedule.groups.map((group) => (
            <HoldGroupSection
              key={group.equipment_type_code}
              group={group}
              isRanged={isRanged}
              backToSchedule={backToSchedule}
            />
          ))}
      </div>
    </div>
  )
}
