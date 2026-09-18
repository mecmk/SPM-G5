import type { ReactNode } from 'react'

export interface EmptyStateProps {
  children: ReactNode
}

/** Story c3 - the "nothing here yet" message for an empty list, distinct from loading or error. */
export function EmptyState({ children }: EmptyStateProps) {
  return <p className="empty">{children}</p>
}
