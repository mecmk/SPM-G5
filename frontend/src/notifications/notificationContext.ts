import { createContext, useContext } from 'react'
import type { NotificationImportance } from '../api/client'

/** One entry in the log of the user's own recent actions (story 8.3's notification centre): the
 * outcome of a change they made. It has no read state; the bell's count is the server's (20.2). */
export interface AppNotification {
  id: number
  title: string
  message: string
  importance: NotificationImportance
  isSuccess: boolean
  createdAt: Date
}

export interface NotificationContextValue {
  /** Newest first. Cleared when the user signs out. */
  notifications: AppNotification[]
  /** Notifications still showing as a toast. */
  toasts: AppNotification[]
  dismissToast: (id: number) => void
}

export const NotificationContext = createContext<NotificationContextValue | null>(null)

const MISSING_PROVIDER_MESSAGE = 'useNotifications must be used inside <NotificationProvider>.'

export function useNotifications(): NotificationContextValue {
  const value = useContext(NotificationContext)
  if (!value) throw new Error(MISSING_PROVIDER_MESSAGE)
  return value
}
