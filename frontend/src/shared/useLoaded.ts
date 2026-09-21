import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import { formatApiError } from '../api/client'

/** What a page holds while it loads one thing from the API when it opens. */
export interface LoadedState<T> {
  /** Null until the first load succeeds. The last good value stays while a changed `load` runs. */
  data: T | null
  /** The message to show when the latest load failed, otherwise null. */
  error: string | null
  /** True until the first load has either succeeded or failed. */
  isLoading: boolean
  /** For a page that changes what it loaded: removing a deleted row, adding a further page. */
  setData: Dispatch<SetStateAction<T | null>>
}

/**
 * Load once when the page opens, and again whenever `load` changes. `load` must keep its identity
 * between renders unless what it fetches has changed - a module-level function, or a `useCallback`
 * over the values it reads - or the page would load on every render. The `cancelled` flag stops a
 * slow answer for an old `load`, or for a page that has gone, from being set (frontend/STYLE.md).
 */
export function useLoaded<T>(load: () => Promise<T>): LoadedState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    load()
      .then((result) => {
        if (cancelled) return
        setData(result)
        setError(null)
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err))
      })
    return () => {
      cancelled = true
    }
  }, [load])

  return { data, error, isLoading: data === null && error === null, setData }
}
