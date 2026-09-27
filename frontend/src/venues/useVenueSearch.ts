import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { RelaxFilter } from '../api/venues'
import { readVenueSearch, venueSearchParams, type VenueSearch } from '../routes'

/** The catalogue's search, as the page address holds it. */
export interface VenueSearchState {
  search: VenueSearch
  /** Change some filters. The new address replaces the current one, so the Back button is not
   *  one history entry per keystroke. */
  updateSearch: (change: Partial<VenueSearch>) => void
  /** Every filter back to Any. The event stays, so f12.1.1's banner and Request this venue do. */
  clearFilters: () => void
}

/** Story 8.1 AC8: what removing each filter group the search suggests clears. */
export const RELAX_CHANGES: Record<RelaxFilter, Partial<VenueSearch>> = {
  search: { search: undefined },
  capacity: { capacity: undefined, capacityMax: undefined },
  dates: { from: undefined, to: undefined },
  layout: { layout: undefined },
  facilities: { facilities: [] },
  accessibility: { accessibilityFeatures: [] },
}

/** Whether `search` narrows the catalogue at all. Showing withdrawn venues widens it instead. */
export function hasFilters(search: VenueSearch): boolean {
  return Boolean(
    search.search ||
    search.capacity !== undefined ||
    search.capacityMax !== undefined ||
    search.from ||
    search.to ||
    search.layout ||
    search.facilities?.length ||
    search.accessibilityFeatures?.length,
  )
}

/**
 * The search the address holds this moment. react-router applies a navigation in a transition,
 * so an earlier change can already be in the address but not yet in the rendered `searchParams`;
 * building on those would drop it when two filters change in quick succession.
 */
function currentVenueSearch(): VenueSearch {
  return readVenueSearch(new URLSearchParams(window.location.search))
}

/**
 * Story 8.1 AC4/AC10: the catalogue's filters live in the page address, so a search can be
 * bookmarked, survives a reload, and comes back with the Back button or a venue record's back
 * link. The page loads from the address; the filter panel writes to it.
 */
export function useVenueSearch(): VenueSearchState {
  const [searchParams, setSearchParams] = useSearchParams()
  const search = useMemo(() => readVenueSearch(searchParams), [searchParams])

  const updateSearch = useCallback(
    (change: Partial<VenueSearch>) =>
      setSearchParams(venueSearchParams({ ...currentVenueSearch(), ...change }), { replace: true }),
    [setSearchParams],
  )

  const clearFilters = useCallback(
    () =>
      setSearchParams(venueSearchParams({ eventId: currentVenueSearch().eventId }), {
        replace: true,
      }),
    [setSearchParams],
  )

  return { search, updateSearch, clearFilters }
}
