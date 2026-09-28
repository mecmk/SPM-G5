import { useCallback, useEffect, useId, useState, type ReactNode } from 'react'
import { fetchVenueReferenceData, type ReferenceItem } from '../api/venues'
import { Icon } from '../components/Icon'
import { capacityLimit, type VenueSearch } from '../routes'
import { inputToInstant, instantToInput } from '../shared/format'
import { useLoaded } from '../shared/useLoaded'
import { countFilters } from './useVenueSearch'

/** How long typing must pause before a typed filter goes into the address (story 8.1 AC4). */
const TYPING_PAUSE_MS = 400
/** A choice - a select or a tick - goes into the address at once. */
const AT_ONCE_MS = 0

interface FilterValue<T> {
  value: T
  setValue: (value: T) => void
}

/**
 * One filter as the panel shows it. A change shows at once and goes into the address after
 * `delayMs`; a change the address gets from elsewhere - Clear filters, a suggestion to remove a
 * filter, Back - replaces what is shown. The panel cannot show the address directly: react-router
 * applies a navigation in a transition, so a control bound to it flicks back until that lands.
 */
function useFilterValue<T>(
  committed: T,
  commit: (value: T) => void,
  delayMs: number,
): FilterValue<T> {
  const committedKey = JSON.stringify(committed)
  const [value, setValue] = useState(committed)
  const [lastCommittedKey, setLastCommittedKey] = useState(committedKey)
  if (committedKey !== lastCommittedKey) {
    setLastCommittedKey(committedKey)
    setValue(committed)
  }

  const valueKey = JSON.stringify(value)
  useEffect(() => {
    if (valueKey === committedKey) return
    const timer = setTimeout(() => commit(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, valueKey, committedKey, commit, delayMs])

  return { value, setValue }
}

function textOrUndefined(value: string): string | undefined {
  return value === '' ? undefined : value
}

/** A capacity range as the panel shows it: what is typed in each box. */
interface CapacityRange {
  min: string
  max: string
}

/** A period as the panel shows it: each end a Singapore `datetime-local` value, or ''. */
interface Period {
  from: string
  to: string
}

/** How long a period moved by its start lasts when it had no length of its own to keep. */
const DEFAULT_PERIOD_MS = 60 * 60 * 1000

/**
 * Story 8.1 AC3: a new Capacity from. Raised past Capacity to, it takes Capacity to up to match,
 * so the range does not run backwards. Lowering Capacity to never moves Capacity from - "200" is
 * typed through "2" - so AC8's refusal stays as the failsafe for a Capacity to typed below it.
 */
function withCapacityFrom(range: CapacityRange, min: string): CapacityRange {
  const newMin = capacityLimit(min)
  const max = capacityLimit(range.max)
  const isPastMax = newMin !== undefined && max !== undefined && newMin > max
  return { min, max: isPastMax ? min : range.max }
}

function inputToMs(inputValue: string): number | undefined {
  const ms = Date.parse(inputToInstant(inputValue))
  return Number.isNaN(ms) ? undefined : ms
}

/**
 * Story 8.1 AC3: a new From. Moved to or past To, it takes To along and the period keeps its
 * length - an hour if it had none - the way a calendar moves an event's end with its start. Moving
 * To never moves From, so AC8's refusal stays as the failsafe for a To set before From.
 */
function withFrom(period: Period, from: string): Period {
  const start = inputToMs(from)
  const end = inputToMs(period.to)
  if (start === undefined || end === undefined || end > start) return { from, to: period.to }
  const earlierStart = inputToMs(period.from)
  const length =
    earlierStart !== undefined && end > earlierStart ? end - earlierStart : DEFAULT_PERIOD_MS
  return { from, to: instantToInput(new Date(start + length).toISOString()) }
}

function toggled(codes: readonly string[], code: string, isOn: boolean): string[] {
  const others = codes.filter((other) => other !== code)
  return isOn ? [...others, code] : others
}

function loadReferenceData() {
  return fetchVenueReferenceData()
}

interface FilterSectionProps {
  title: string
  /** How many of the section's choices are ticked, shown beside the title when there are any. */
  tickedCount?: number
  children: ReactNode
}

/**
 * One titled group of the panel, named by its title for assistive technology. The titles are the
 * group names the empty state's "Try removing" suggestions use (AC9), so the two can be matched.
 */
function FilterSection({ title, tickedCount = 0, children }: FilterSectionProps) {
  const titleId = useId()
  return (
    <div className="filter-section" role="group" aria-labelledby={titleId}>
      <div className="filter-section-title">
        <span id={titleId}>{title}</span>
        {tickedCount > 0 && (
          <span className="filter-section-count">
            {tickedCount}
            <span className="visually-hidden"> ticked</span>
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

interface FilterChipsProps {
  title: string
  items: ReferenceItem[]
  filter: FilterValue<readonly string[]>
}

/**
 * Story 8.1 AC10: ticks shown as chips, every ticked one required. A group packs into a few lines
 * rather than one line per choice, and each chip is a real checkbox, so it still works from the
 * keyboard.
 */
function FilterChips({ title, items, filter }: FilterChipsProps) {
  return (
    <FilterSection title={title} tickedCount={filter.value.length}>
      <div className="choice-chips">
        {items.map((item) => (
          <label key={item.code} className="choice-chip">
            <input
              type="checkbox"
              checked={filter.value.includes(item.code)}
              onChange={(e) => filter.setValue(toggled(filter.value, item.code, e.target.checked))}
            />
            {item.name}
          </label>
        ))}
      </div>
    </FilterSection>
  )
}

export interface VenueFilterPanelProps {
  search: VenueSearch
  onChange: (change: Partial<VenueSearch>) => void
  onClear: () => void
  /** Story 8.1 AC12: Venue Staff may list withdrawn venues too. */
  canShowWithdrawn: boolean
  /** Why the latest search could not be run (AC8), shown beside the panel. */
  error: string | null
}

/**
 * Story 8.1 AC3 (10.1 merged in, built as s8.1): the catalogue's one filter panel - name or
 * location, a capacity range, a period, a layout, facilities and accessibility features, every
 * ticked one required (AC10). It shows the search the page address holds and writes changes back
 * to it (AC4): typed values once typing pauses, choices at once. Opened from an event's Find a
 * venue, it therefore starts filled in from the event (AC4).
 *
 * The dates go into the search only once both are filled in; a search the server cannot run says
 * why here and leaves the results as they were (AC8).
 *
 * Each range - capacity from and to, the dates from and to - sits together as one filter and goes
 * into the address as one change, so raising its lower end past the upper one, which takes the
 * upper one along, never sends a backwards search. The header counts the filters in use. On a phone the panel starts folded under that header, so the
 * venues come first.
 */
export function VenueFilterPanel({
  search,
  onChange,
  onClear,
  canShowWithdrawn,
  error,
}: VenueFilterPanelProps) {
  const { data: reference, error: referenceError } = useLoaded(loadReferenceData)
  const [isExpanded, setIsExpanded] = useState(false)
  const bodyId = useId()

  const name = useFilterValue(
    search.search ?? '',
    useCallback((value: string) => onChange({ search: textOrUndefined(value) }), [onChange]),
    TYPING_PAUSE_MS,
  )
  const capacity = useFilterValue<CapacityRange>(
    { min: search.capacity?.toString() ?? '', max: search.capacityMax?.toString() ?? '' },
    useCallback(
      (range: CapacityRange) =>
        onChange({
          capacity: capacityLimit(range.min),
          capacityMax: capacityLimit(range.max),
        }),
      [onChange],
    ),
    TYPING_PAUSE_MS,
  )
  const period = useFilterValue<Period>(
    { from: search.from ?? '', to: search.to ?? '' },
    useCallback(
      (dates: Period) =>
        onChange({ from: textOrUndefined(dates.from), to: textOrUndefined(dates.to) }),
      [onChange],
    ),
    TYPING_PAUSE_MS,
  )
  const layout = useFilterValue(
    search.layout ?? '',
    useCallback((value: string) => onChange({ layout: textOrUndefined(value) }), [onChange]),
    AT_ONCE_MS,
  )
  const facilities = useFilterValue<readonly string[]>(
    search.facilities ?? [],
    useCallback((codes: readonly string[]) => onChange({ facilities: codes }), [onChange]),
    AT_ONCE_MS,
  )
  const accessibility = useFilterValue<readonly string[]>(
    search.accessibilityFeatures ?? [],
    useCallback(
      (codes: readonly string[]) => onChange({ accessibilityFeatures: codes }),
      [onChange],
    ),
    AT_ONCE_MS,
  )
  const withdrawn = useFilterValue(
    search.includeWithdrawn ?? false,
    useCallback((isShown: boolean) => onChange({ includeWithdrawn: isShown }), [onChange]),
    AT_ONCE_MS,
  )

  const filterCount = countFilters(search)
  const isFiltered = filterCount > 0 || Boolean(search.includeWithdrawn)

  function toggleExpanded() {
    setIsExpanded((wasExpanded) => !wasExpanded)
  }

  return (
    <aside className={`filter-panel${isExpanded ? '' : ' is-collapsed'}`} aria-label="Filters">
      <div className="filter-panel-header">
        <h2 className="filter-panel-title">
          Filters
          {filterCount > 0 && (
            <span className="filter-count">
              {filterCount}
              <span className="visually-hidden"> in use</span>
            </span>
          )}
        </h2>
        {isFiltered && (
          <button type="button" className="link" aria-label="Clear all filters" onClick={onClear}>
            Clear all
          </button>
        )}
        <button
          type="button"
          className="ghost button-sm filter-panel-toggle"
          aria-expanded={isExpanded}
          aria-controls={bodyId}
          onClick={toggleExpanded}
        >
          {isExpanded ? 'Hide' : 'Show'}
          <span className="visually-hidden"> filters</span>
        </button>
      </div>
      {error && (
        <p role="alert" className="error filter-panel-alert">
          {error}
        </p>
      )}
      <div id={bodyId} className="filter-panel-body">
        <div className="filter-section">
          <label>
            Name or location
            <span className="input-with-icon">
              <Icon name="search" size={16} />
              <input
                type="search"
                placeholder="Any"
                value={name.value}
                onChange={(e) => name.setValue(e.target.value)}
              />
            </span>
          </label>
        </div>
        <FilterSection title="Capacity">
          <div className="range-fields">
            <label>
              <span className="visually-hidden">Capacity from</span>
              <input
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                placeholder="Min"
                value={capacity.value.min}
                onChange={(e) =>
                  capacity.setValue(withCapacityFrom(capacity.value, e.target.value))
                }
              />
            </label>
            <span className="range-fields-dash" aria-hidden="true">
              –
            </span>
            <label>
              <span className="visually-hidden">Capacity to</span>
              <input
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                placeholder="Max"
                value={capacity.value.max}
                onChange={(e) => capacity.setValue({ ...capacity.value, max: e.target.value })}
              />
            </label>
          </div>
        </FilterSection>
        <FilterSection title="Dates">
          <div className="date-fields">
            <label>
              From
              <input
                type="datetime-local"
                value={period.value.from}
                onChange={(e) => period.setValue(withFrom(period.value, e.target.value))}
              />
            </label>
            <label>
              To
              <input
                type="datetime-local"
                value={period.value.to}
                onChange={(e) => period.setValue({ ...period.value, to: e.target.value })}
              />
            </label>
          </div>
        </FilterSection>
        {referenceError && (
          <div className="filter-section">
            <p role="alert" className="error">
              {referenceError}
            </p>
          </div>
        )}
        {reference && (
          <>
            <div className="filter-section">
              <label>
                Layout
                <select value={layout.value} onChange={(e) => layout.setValue(e.target.value)}>
                  <option value="">Any</option>
                  {reference.layouts.map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <FilterChips title="Facilities" items={reference.facilities} filter={facilities} />
            <FilterChips
              title="Accessibility"
              items={reference.accessibility_features}
              filter={accessibility}
            />
          </>
        )}
        {canShowWithdrawn && (
          <div className="filter-section">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={withdrawn.value}
                onChange={(e) => withdrawn.setValue(e.target.checked)}
              />
              Show withdrawn venues
            </label>
          </div>
        )}
      </div>
    </aside>
  )
}
