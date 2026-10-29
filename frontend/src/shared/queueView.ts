import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'

/** Story 13.3 AC5: the longest search either queue takes; the search box takes no more. Keep in
 * step by hand with QUEUE_SEARCH_MAX_LENGTH in backend/app/common/search.py. */
export const QUEUE_SEARCH_MAX_LENGTH = 100

/** Story 13.3 AC7: the names a queue's view goes by in the page address. */
const QUEUE_VIEW_PARAMS = {
  tab: 'status',
  search: 'search',
  order: 'order',
  page: 'page',
} as const

/** Story 13.3 AC3: one choice in a queue's Order by list. */
export interface QueueOrderOption<TOrder extends string> {
  key: TOrder
  label: string
}

/** Story 13.3 AC3: the orders both queues offer, as the backend's `BookingQueueOrder` and
 * `EquipmentQueueOrder` both name them. */
type CommonQueueOrder = 'date' | 'date_desc' | 'requested' | 'requested_desc' | 'event_name'

/** Story 13.3 AC3: the order a queue opens in - date, soonest first, as before there was a choice. */
export const DEFAULT_QUEUE_ORDER: CommonQueueOrder = 'date'

/** Story 13.3 AC3: the orders both queues offer, in the order their Order by lists show them. Each
 * queue adds its own last: its venue's or its equipment type's name, A to Z. */
export const COMMON_QUEUE_ORDERS: readonly QueueOrderOption<CommonQueueOrder>[] = [
  { key: DEFAULT_QUEUE_ORDER, label: 'Date: soonest first' },
  { key: 'date_desc', label: 'Date: latest first' },
  { key: 'requested', label: 'Requested: oldest first' },
  { key: 'requested_desc', label: 'Requested: newest first' },
  { key: 'event_name', label: 'Event name: A to Z' },
]

/** What a queue shows: its tab, what it is searched for, its order and which page (from 1). */
export interface QueueView<TTab extends string, TOrder extends string> {
  tab: TTab
  search: string
  order: TOrder
  page: number
}

/** The tabs and orders a queue's address may name, and the view it opens on when it names none. */
export interface QueueViewOptions<TTab extends string, TOrder extends string> {
  tabs: readonly TTab[]
  orders: readonly TOrder[]
  defaults: QueueView<TTab, TOrder>
}

function oneOf<T extends string>(value: string | null, allowed: readonly T[]): T | undefined {
  return allowed.find((candidate) => candidate === value)
}

/**
 * Story 13.3 AC7: the view an address holds. What it cannot use - a tab or order the queue does
 * not offer, a page that is not a whole number from 1 - is the queue's default instead, and a
 * search is cut to the longest one the queue takes (AC5), so a mangled address still opens a list.
 */
function readQueueView<TTab extends string, TOrder extends string>(
  params: URLSearchParams,
  options: QueueViewOptions<TTab, TOrder>,
): QueueView<TTab, TOrder> {
  const page = Number(params.get(QUEUE_VIEW_PARAMS.page))
  return {
    tab: oneOf(params.get(QUEUE_VIEW_PARAMS.tab), options.tabs) ?? options.defaults.tab,
    search: (params.get(QUEUE_VIEW_PARAMS.search) ?? '').slice(0, QUEUE_SEARCH_MAX_LENGTH),
    order: oneOf(params.get(QUEUE_VIEW_PARAMS.order), options.orders) ?? options.defaults.order,
    page: Number.isInteger(page) && page >= 1 ? page : options.defaults.page,
  }
}

/** The address query for `view`, holding only what differs from the queue's default view, so the
 * plain queue address is the view a queue opens on. A blank search is no search (AC5). */
function queueViewParams<TTab extends string, TOrder extends string>(
  view: QueueView<TTab, TOrder>,
  options: QueueViewOptions<TTab, TOrder>,
): URLSearchParams {
  const params = new URLSearchParams()
  if (view.tab !== options.defaults.tab) params.set(QUEUE_VIEW_PARAMS.tab, view.tab)
  if (view.search.trim() !== '') params.set(QUEUE_VIEW_PARAMS.search, view.search)
  if (view.order !== options.defaults.order) params.set(QUEUE_VIEW_PARAMS.order, view.order)
  if (view.page !== options.defaults.page) params.set(QUEUE_VIEW_PARAMS.page, String(view.page))
  return params
}

/** A queue page's view, as its address holds it. */
interface QueueViewState<TTab extends string, TOrder extends string> {
  view: QueueView<TTab, TOrder>
  /** The view's address query, for a link that should lead back to this list. */
  query: string
  /** Change part of the view. A new tab, search or order starts again at page 1 (AC4), unless the
   * change names a page. The new address replaces the current one, so the Back button is not one
   * history entry per keystroke. */
  changeView: (change: Partial<QueueView<TTab, TOrder>>) => void
}

/**
 * Story 13.3 AC7: a queue's tab, search, order and page live in the page address, so switching
 * tabs keeps the search and order, and a refresh or a link back returns to the same list. The
 * page's controls write to the address and the page loads the view it holds. `options` must keep
 * its identity between renders: a module-level constant.
 *
 * A change shows at once, as a tab did before it was in the address, so the old view's requests
 * are hidden the moment it is chosen; react-router updates the address in a transition, which
 * catches up after. A change the address gets from elsewhere (Back, a link) replaces the view. The
 * same approach as 5.5's `useShownFilter` in `events/AssignmentOverviewPage.tsx`.
 */
export function useQueueView<TTab extends string, TOrder extends string>(
  options: QueueViewOptions<TTab, TOrder>,
): QueueViewState<TTab, TOrder> {
  const [searchParams, setSearchParams] = useSearchParams()
  const fromAddress = readQueueView(searchParams, options)
  const addressQuery = queueViewParams(fromAddress, options).toString()
  const [view, setView] = useState(fromAddress)
  const [lastAddressQuery, setLastAddressQuery] = useState(addressQuery)
  const query = useMemo(() => queueViewParams(view, options).toString(), [view, options])
  if (addressQuery !== lastAddressQuery) {
    setLastAddressQuery(addressQuery)
    // The address catching up with a change shown already keeps the view as it is, so nothing that
    // depends on it - the page's load - runs twice.
    if (addressQuery !== query) setView(fromAddress)
  }

  // The address already holds every change made before, even one react-router has not rendered
  // yet, so building on it keeps each one.
  const changeView = useCallback(
    (change: Partial<QueueView<TTab, TOrder>>) => {
      const current = readQueueView(new URLSearchParams(window.location.search), options)
      const next = { ...current, page: options.defaults.page, ...change }
      setView(next)
      setSearchParams(queueViewParams(next, options), { replace: true })
    },
    [setSearchParams, options],
  )

  return { view, query, changeView }
}

/** A queue's address with `query`, its view. */
export function queuePath(path: string, query: string): string {
  return query === '' ? path : `${path}?${query}`
}

/**
 * Story 13.3 AC7: where a request's page leads back to - the queue as the link that opened it left
 * it (the `from` of story 7.1's back state), or the plain queue when the page was opened another
 * way. Only an address of that queue is followed.
 */
export function queueBackPath(state: unknown, path: string): string {
  if (typeof state !== 'object' || state === null || !('from' in state)) return path
  const { from } = state
  if (typeof from !== 'string') return path
  return from === path || from.startsWith(`${path}?`) ? from : path
}
