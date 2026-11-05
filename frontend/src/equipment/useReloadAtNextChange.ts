import { useEffect } from 'react'
import type { OutOfServiceRecord } from '../api/equipment'

/** How long after a record starts or ends the figures are read again, so the server's own clock has
 *  passed the moment and the units now count, or no longer count, as out. */
const RELOAD_DELAY_MS = 1000

/** The longest wait a timer can hold; a change further off is found by the reload after it. */
const LONGEST_WAIT_MS = 2 ** 31 - 1

/**
 * Fix f16.2.5 (16.2 AC2): the moment, after `loadedAt`, that the next record in `records` starts
 * or ends - when "out of service now" changes with nothing done on the page - or null when none
 * will.
 */
export function nextChangeAfter(records: OutOfServiceRecord[], loadedAt: number): number | null {
  const moments = records
    .flatMap((record) => [record.starts_at, record.ends_at])
    .flatMap((instant) => (instant === null ? [] : [Date.parse(instant)]))
    .filter((moment) => moment > loadedAt)
  return moments.length === 0 ? null : Math.min(...moments)
}

/**
 * Fix f16.2.5 (16.2 AC2): calls `reload` when the next of `records` starts or ends, so a record
 * scheduled for later takes its units out of "out of service now" as its time arrives, and its
 * label changes from Scheduled to In force, without the page being refreshed. `reload` is called
 * again after each change, since `records` and `loadedAt` are then new.
 */
export function useReloadAtNextChange(
  records: OutOfServiceRecord[] | null,
  loadedAt: number,
  reload: () => void,
) {
  useEffect(() => {
    if (records === null) return
    const next = nextChangeAfter(records, loadedAt)
    if (next === null) return
    const wait = Math.min(Math.max(next - Date.now(), 0) + RELOAD_DELAY_MS, LONGEST_WAIT_MS)
    const timer = setTimeout(reload, wait)
    return () => clearTimeout(timer)
  }, [records, loadedAt, reload])
}
