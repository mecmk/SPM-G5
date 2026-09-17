import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fetchCurrentUser, login, logout, type CurrentUser } from '../api/auth'
import { AuthContext, type AuthContextValue } from './authContext'

/** Story 1.1: holds the signed-in user for the whole app. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Story 1.1 AC1: a reload keeps the session, because the HttpOnly cookie is still there.
  useEffect(() => {
    let cancelled = false
    fetchCurrentUser()
      .then((me) => {
        if (!cancelled) setUser(me)
      })
      .catch(() => {
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const me = await login(email, password)
    setUser(me)
    return me
  }, [])

  const signOut = useCallback(async () => {
    try {
      await logout()
    } finally {
      setUser(null)
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ user, isLoading, signIn, signOut }),
    [user, isLoading, signIn, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
