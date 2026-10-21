import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router'
import { formatApiError } from '../api/client'
import {
  fetchUnreadCount,
  listNotifications,
  markNotificationRead,
  markNotificationsReadThrough,
  type ServerNotification,
} from '../api/notifications'
import { useAuth } from '../auth/authContext'
import {
  ServerNotificationContext,
  type ServerNotificationContextValue,
} from './serverNotificationContext'

/**
 * The user's server notifications and their unread count (story 20.2), held once for the signed-in
 * frame: the bell is drawn twice (the sidebar's and the phone's bar), and a fetch inside the bell
 * would send every request twice. Read when the frame opens, on every page change, when the tab
 * becomes visible again and when the notification panel opens (AC2) - never on a timer. An answer
 * that arrives after a newer request was sent is dropped, as `useLoaded` drops one for a `load` that
 * has changed.
 */
function ServerNotifications({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const [notifications, setNotifications] = useState<ServerNotification[] | null>(null)
  const [unreadCount, setUnreadCount] = useState(0)
  const [listError, setListError] = useState<string | null>(null)
  const latestCountRequest = useRef(0)
  const latestListRequest = useRef(0)
  // The newest notification of the list last shown: "mark all as read" goes through it, so one
  // that arrived since stays unread (AC1).
  const newestLoadedId = useRef<string | null>(null)
  // False once the frame has gone (sign-out), so an answer that lands after that is dropped.
  const isMounted = useRef(true)

  useEffect(() => {
    isMounted.current = true
    return () => {
      isMounted.current = false
    }
  }, [])

  const loadCount = useCallback(() => {
    latestCountRequest.current += 1
    const request = latestCountRequest.current
    fetchUnreadCount()
      .then((count) => {
        if (isMounted.current && request === latestCountRequest.current) setUnreadCount(count)
      })
      .catch(() => {
        // The badge keeps its last number; the list request reports a failure to the panel.
      })
  }, [])

  const loadList = useCallback(() => {
    latestListRequest.current += 1
    const request = latestListRequest.current
    listNotifications()
      .then((listed) => {
        if (!isMounted.current || request !== latestListRequest.current) return
        newestLoadedId.current = listed.length > 0 ? listed[0].id : null
        setNotifications(listed)
        setListError(null)
      })
      .catch((err) => {
        if (isMounted.current && request === latestListRequest.current) {
          setListError(formatApiError(err))
        }
      })
  }, [])

  const refresh = useCallback(() => {
    loadCount()
    loadList()
  }, [loadCount, loadList])

  useEffect(() => {
    refresh()
  }, [pathname, refresh])

  useEffect(() => {
    function refreshWhenVisible() {
      if (document.visibilityState === 'visible') refresh()
    }
    document.addEventListener('visibilitychange', refreshWhenVisible)
    return () => document.removeEventListener('visibilitychange', refreshWhenVisible)
  }, [refresh])

  const markRead = useCallback(
    async (notificationId: string) => {
      const marked = await markNotificationRead(notificationId)
      if (!isMounted.current) return
      setNotifications((current) =>
        current === null
          ? current
          : current.map((item) =>
              item.id === marked.id ? { ...item, read_at: marked.read_at } : item,
            ),
      )
      loadCount()
    },
    [loadCount],
  )

  const markAllRead = useCallback(async () => {
    const throughId = newestLoadedId.current
    if (throughId === null) return
    await markNotificationsReadThrough(throughId)
    refresh()
  }, [refresh])

  const value = useMemo<ServerNotificationContextValue>(
    () => ({ notifications, unreadCount, listError, refresh, markRead, markAllRead }),
    [notifications, unreadCount, listError, refresh, markRead, markAllRead],
  )

  return (
    <ServerNotificationContext.Provider value={value}>
      {children}
    </ServerNotificationContext.Provider>
  )
}

/** Keyed by the signed-in user, so one user's notifications are never shown to the next. */
export function ServerNotificationProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  return <ServerNotifications key={user?.id ?? 'signed-out'}>{children}</ServerNotifications>
}
