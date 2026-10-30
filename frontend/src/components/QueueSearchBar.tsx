import { useEffect, useState, type ChangeEvent } from 'react'
import { QUEUE_SEARCH_MAX_LENGTH, type QueueOrderOption } from '../shared/queueView'

/** How long typing must pause before the search goes into the address (story 13.3 AC2), as the
 * venue catalogue's search does (story 8.1 AC4). */
const TYPING_PAUSE_MS = 400

export interface QueueSearchBarProps<TOrder extends string> {
  /** The search the page address holds. */
  search: string
  placeholder: string
  onSearch: (search: string) => void
  order: TOrder
  orders: readonly QueueOrderOption<TOrder>[]
  onOrder: (order: TOrder) => void
}

/**
 * Story 13.3 AC1 - a queue's search box and Order by list, beside its tabs.
 * AC2: the list follows the box as the user types, once typing pauses; no button is pressed. AC5:
 * the box takes no more than the longest search the queue takes, and spaces around the text are no
 * change. AC3: an order is chosen from the queue's own list and goes into the address at once.
 *
 * A search the page gets from elsewhere (Clear search, Back) replaces what the box shows; the page
 * taking up what was typed does not, so a space typed after a word is kept.
 */
export function QueueSearchBar<TOrder extends string>({
  search,
  placeholder,
  onSearch,
  order,
  orders,
  onOrder,
}: QueueSearchBarProps<TOrder>) {
  const [typed, setTyped] = useState(search)
  const [lastSearch, setLastSearch] = useState(search)
  if (search !== lastSearch) {
    setLastSearch(search)
    if (search !== typed.trim()) setTyped(search)
  }

  useEffect(() => {
    const text = typed.trim()
    if (text === search.trim()) return undefined
    const timer = setTimeout(() => onSearch(text), TYPING_PAUSE_MS)
    return () => clearTimeout(timer)
  }, [typed, search, onSearch])

  function handleType(change: ChangeEvent<HTMLInputElement>) {
    setTyped(change.target.value)
  }

  function handleOrder(change: ChangeEvent<HTMLSelectElement>) {
    const chosen = orders.find((option) => option.key === change.target.value)
    if (chosen === undefined) return
    onOrder(chosen.key)
  }

  return (
    <div className="filter-bar">
      <label className="filter-grow">
        Search requests
        <input
          type="search"
          placeholder={placeholder}
          value={typed}
          maxLength={QUEUE_SEARCH_MAX_LENGTH}
          onChange={handleType}
        />
      </label>
      <label>
        Order by
        <select value={order} onChange={handleOrder}>
          {orders.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
