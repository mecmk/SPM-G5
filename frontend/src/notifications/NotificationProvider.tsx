import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { subscribeToMutations, type MutationOutcome } from '../api/client'
import {
  NotificationContext,
  type AppNotification,
  type NotificationContextValue,
} from './notificationContext'

const TOAST_LIFETIME_MS = 5000
const MAX_NOTIFICATIONS = 50

/**
 * The notification centre (team decision, 17 Sep 2026): every change a user makes, successful or
 * not, is listed here and briefly shown as a toast. It lives inside the signed-in frame, so
 * signing out clears it.
 */
export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<AppNotification[]>([])
  const [toasts, setToasts] = useState<AppNotification[]>([])
  const nextId = useRef(1)
  const timers = useRef(new Map<number, number>())

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
    const timer = timers.current.get(id)
    if (timer !== undefined) window.clearTimeout(timer)
    timers.current.delete(id)
  }, [])

  const markAllRead = useCallback(() => {
    setNotifications((current) => current.map((item) => ({ ...item, isRead: true })))
  }, [])

  useEffect(() => {
    const pendingTimers = timers.current

    function addNotification(outcome: MutationOutcome) {
      const notification: AppNotification = {
        ...outcome,
        id: nextId.current,
        createdAt: new Date(),
        isRead: false,
      }
      nextId.current += 1
      setNotifications((current) => [notification, ...current].slice(0, MAX_NOTIFICATIONS))
      setToasts((current) => [...current, notification])
      const timer = window.setTimeout(() => dismissToast(notification.id), TOAST_LIFETIME_MS)
      pendingTimers.set(notification.id, timer)
    }

    const unsubscribe = subscribeToMutations(addNotification)
    return () => {
      unsubscribe()
      pendingTimers.forEach((timer) => window.clearTimeout(timer))
      pendingTimers.clear()
    }
  }, [dismissToast])

  const unreadCount = notifications.filter((item) => !item.isRead).length

  const value = useMemo<NotificationContextValue>(
    () => ({ notifications, toasts, unreadCount, markAllRead, dismissToast }),
    [notifications, toasts, unreadCount, markAllRead, dismissToast],
  )

  return <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>
}
