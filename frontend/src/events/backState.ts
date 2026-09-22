import type { EventCardBackState } from '../components/EventCard'

/**
 * The page a person came from, when the link that brought them here said so (story 7.1's
 * `EventCardBackState`), so a back link can return there. Anything else in a history entry's
 * `state`, or a `from` that is not a path inside the app, is ignored.
 */
export function readBackState(state: unknown): EventCardBackState | null {
  if (typeof state !== 'object' || state === null) return null
  if (!('from' in state) || !('fromLabel' in state)) return null
  const { from, fromLabel } = state
  if (typeof from !== 'string' || typeof fromLabel !== 'string') return null
  if (!from.startsWith('/') || from.startsWith('//')) return null
  return { from, fromLabel }
}
