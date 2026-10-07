import { useEffect, useState } from 'react'
import { formatApiError } from '../api/client'
import type { VenueUnavailableWindow } from '../api/venues'
import { instantToInput, inputToInstant } from './format'

/** One venue's `getVenueCalendar`, bound to it: the windows overlapping `startsAt`-`endsAt`. */
export type VenueCalendarLoader = (
  startsAt: string,
  endsAt: string,
) => Promise<VenueUnavailableWindow[]>

/** What a page holds for the month of a venue's calendar on screen (story 9.1). */
export interface VenueCalendarState {
  /** The first day of the month shown. */
  month: Date
  setMonth: (month: Date) => void
  /** Empty while the first load runs, and after a failed one (see `error`). */
  windows: VenueUnavailableWindow[]
  /** The message to show when the latest month failed to load, otherwise null. */
  error: string | null
  isLoading: boolean
}

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

const ISO_DATE_LENGTH = 'YYYY-MM-DD'.length

/** The Singapore day (`YYYY-MM-DD`) `stamp` falls on (see shared/format.ts). */
export function singaporeDateOf(stamp: string): string {
  return instantToInput(stamp).slice(0, ISO_DATE_LENGTH)
}

/** The first day of the Singapore month `stamp` falls in. */
export function startOfMonthOf(stamp: string): Date {
  const [year, month] = singaporeDateOf(stamp).split('-').map(Number)
  return new Date(year, month - 1, 1)
}

/** Singapore-midnight instant for the first day of `month`. */
function monthBoundary(month: Date): string {
  const monthNumber = String(month.getMonth() + 1).padStart(2, '0')
  return inputToInstant(`${month.getFullYear()}-${monthNumber}-01T00:00`)
}

/**
 * Story 9.1 AC1: a venue's calendar one month at a time, loaded again whenever the month or
 * `loadWindows` changes. `loadWindows` must keep its identity between renders unless the venue
 * changed - a `useCallback` over the venue's id - or the calendar would load on every render.
 *
 * Windows are not cleared when `loadWindows` changes: no page swaps one venue's calendar for
 * another's today, so this can't be observed yet. If that ever becomes possible, this needs to go
 * back to clearing them (or the page keying the calendar on the venue) so a new venue never shows
 * a moment of the previous one's availability.
 */
export function useVenueCalendar(
  loadWindows: VenueCalendarLoader,
  initialMonth: Date,
): VenueCalendarState {
  const [month, setMonth] = useState(() => startOfMonth(initialMonth))
  const [windows, setWindows] = useState<VenueUnavailableWindow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    // Clears a previous month's failure immediately, so it cannot sit on screen describing a
    // month that is no longer the one being loaded.
    setError(null)
    const rangeStart = monthBoundary(month)
    const rangeEnd = monthBoundary(new Date(month.getFullYear(), month.getMonth() + 1, 1))
    loadWindows(rangeStart, rangeEnd)
      .then((data) => {
        if (cancelled) return
        setWindows(data)
        setError(null)
        setIsLoading(false)
      })
      .catch((err) => {
        if (cancelled) return
        // Falls back to "everything available" rather than leaving stale data on screen or
        // hiding the calendar - a deliberate choice, not a neutral default (see f9.1.1 PR notes).
        setWindows([])
        setError(formatApiError(err))
        setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [loadWindows, month])

  return { month, setMonth, windows, error, isLoading }
}
