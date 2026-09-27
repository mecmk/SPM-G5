import { useCallback, useEffect, useState } from 'react'
import { fetchVenueReferenceData, type ReferenceItem } from '../api/venues'
import type { VenueSearch } from '../routes'
import { useLoaded } from '../shared/useLoaded'
import { hasFilters } from './useVenueSearch'

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

interface FilterChecksProps {
  legend: string
  items: ReferenceItem[]
  filter: FilterValue<readonly string[]>
}

/** Story 8.1 AC9: a list of ticks, every ticked one required. */
function FilterChecks({ legend, items, filter }: FilterChecksProps) {
  return (
    <fieldset className="filter-checks">
      <legend>{legend}</legend>
      {items.map((item) => (
        <label key={item.code} className="checkbox">
          <input
            type="checkbox"
            checked={filter.value.includes(item.code)}
            onChange={(e) => filter.setValue(toggled(filter.value, item.code, e.target.checked))}
          />
          {item.name}
        </label>
      ))}
    </fieldset>
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
 */
export function VenueFilterPanel({
  search,
  onChange,
  onClear,
  canShowWithdrawn,
  error,
}: VenueFilterPanelProps) {
  const { data: reference, error: referenceError } = useLoaded(loadReferenceData)

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

  const isFiltered = hasFilters(search) || Boolean(search.includeWithdrawn)

  return (
    <aside className="filter-column" aria-label="Filters">
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <label>
        Name or location
        <input
          type="search"
          placeholder="Any"
          value={name.value}
          onChange={(e) => name.setValue(e.target.value)}
        />
      </label>
      <label>
        Capacity from
        <input
          type="number"
          min={1}
          step={1}
          inputMode="numeric"
          placeholder="Any"
          value={capacity.value}
          onChange={(e) => capacity.setValue(e.target.value)}
        />
      </label>
      <label>
        Capacity to
        <input
          type="number"
          min={1}
          step={1}
          inputMode="numeric"
          placeholder="Any"
          value={capacityMax.value}
          onChange={(e) => capacityMax.setValue(e.target.value)}
        />
      </label>
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
      {referenceError && (
        <p role="alert" className="error">
          {referenceError}
        </p>
      )}
      {reference && (
        <>
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
          <FilterChecks legend="Facilities" items={reference.facilities} filter={facilities} />
          <FilterChecks
            legend="Accessibility"
            items={reference.accessibility_features}
            filter={accessibility}
          />
        </>
      )}
      {canShowWithdrawn && (
        <label className="checkbox">
          <input
            type="checkbox"
            checked={withdrawn.value}
            onChange={(e) => withdrawn.setValue(e.target.checked)}
          />
          Show withdrawn venues
        </label>
      )}
      {isFiltered && (
        <button type="button" className="link" onClick={onClear}>
          Clear all filters
        </button>
      )}
    </aside>
  )
}
