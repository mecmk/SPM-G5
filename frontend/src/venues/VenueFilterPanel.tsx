import { useCallback, useEffect, useId, useState, type ReactNode } from 'react'
import { fetchVenueReferenceData, type ReferenceItem } from '../api/venues'
import { Icon } from '../components/Icon'
import type { VenueSearch } from '../routes'
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

function wholeNumberOrUndefined(value: string): number | undefined {
  const parsed = Number(value)
  return value.trim() === '' || !Number.isInteger(parsed) ? undefined : parsed
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
 * group names the empty state's "Try removing" suggestions use (AC8), so the two can be matched.
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
 * Story 8.1 AC9: ticks shown as chips, every ticked one required. A group packs into a few lines
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
  /** Story 8.1 AC13: Venue Staff may list withdrawn venues too. */
  canShowWithdrawn: boolean
  /** Why the latest search could not be run (AC7), shown beside the panel. */
  error: string | null
}

/**
 * Story 8.1 AC2 (10.1 merged in, built as s8.1): the catalogue's one filter panel - name or
 * location, a capacity range, a period, a layout, facilities and accessibility features, every
 * ticked one required (AC9). It shows the search the page address holds and writes changes back
 * to it (AC4): typed values once typing pauses, choices at once. Opened from an event's Find a
 * venue, it therefore starts filled in from the event (AC3).
 *
 * The dates go into the search only once both are filled in; a search the server cannot run says
 * why here and leaves the results as they were (AC7).
 *
 * Each range - capacity from and to, the dates from and to - sits together as one filter, and the
 * header counts the filters in use. On a phone the panel starts folded under that header, so the
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
  const capacity = useFilterValue(
    search.capacity?.toString() ?? '',
    useCallback(
      (value: string) => onChange({ capacity: wholeNumberOrUndefined(value) }),
      [onChange],
    ),
    TYPING_PAUSE_MS,
  )
  const capacityMax = useFilterValue(
    search.capacityMax?.toString() ?? '',
    useCallback(
      (value: string) => onChange({ capacityMax: wholeNumberOrUndefined(value) }),
      [onChange],
    ),
    TYPING_PAUSE_MS,
  )
  const from = useFilterValue(
    search.from ?? '',
    useCallback((value: string) => onChange({ from: textOrUndefined(value) }), [onChange]),
    TYPING_PAUSE_MS,
  )
  const to = useFilterValue(
    search.to ?? '',
    useCallback((value: string) => onChange({ to: textOrUndefined(value) }), [onChange]),
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
                value={capacity.value}
                onChange={(e) => capacity.setValue(e.target.value)}
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
                value={capacityMax.value}
                onChange={(e) => capacityMax.setValue(e.target.value)}
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
                value={from.value}
                onChange={(e) => from.setValue(e.target.value)}
              />
            </label>
            <label>
              To
              <input
                type="datetime-local"
                value={to.value}
                onChange={(e) => to.setValue(e.target.value)}
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
