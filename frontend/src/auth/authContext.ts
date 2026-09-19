import { createContext, useContext } from 'react'
import type { CurrentUser } from '../api/auth'
import type { Permission } from './permissions'

export interface AuthContextValue {
  /** The signed-in user, or null when signed out. */
  user: CurrentUser | null
  /** True until the first session lookup finishes, so a reload does not bounce to sign-in. */
  isLoading: boolean
  /** Story 1.1 AC1: start a session and remember who signed in. */
  signIn: (email: string, password: string) => Promise<CurrentUser>
  /** Story 1.1 AC5: end the session on the server, then forget the user. */
  signOut: () => Promise<void>
  /** Story 1.2 AC2: whether the signed-in role holds a permission, to hide what it cannot use. */
  can: (permission: Permission) => boolean
}

export const AuthContext = createContext<AuthContextValue | null>(null)

const MISSING_PROVIDER_MESSAGE = 'useAuth must be used inside <AuthProvider>.'

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error(MISSING_PROVIDER_MESSAGE)
  return value
}
