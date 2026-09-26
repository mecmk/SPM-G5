import { api } from './client'

/** Mirrors `UserOut` in backend/app/auth/schemas.py. */
export interface CurrentUser {
  id: string
  email: string
  full_name: string
  role_code: string
  role_name: string
  is_internal: boolean
  organisation_id: string | null
  organisation_name: string | null
  /** Permission codes from backend/app/auth/permissions.py, e.g. "venues:manage". */
  permissions: string[]
}

/**
 * Story 1.1 AC1/AC2: start a session. A 401 is the registry's INVALID_CREDENTIALS; a 429 is
 * LOGIN_LOCKED (AC6), whose `retryAfterSeconds` is the time left before sign-in reopens.
 */
export function login(email: string, password: string): Promise<CurrentUser> {
  return api<CurrentUser>('/auth/login', {
    method: 'POST',
    body: { email, password },
    errorCodes: { 401: 'INVALID_CREDENTIALS', 429: 'LOGIN_LOCKED' },
    notify: false,
  })
}

/** Story 1.1 AC5: revoke the server-side session. */
export function logout(): Promise<void> {
  return api<void>('/auth/logout', { method: 'POST', notify: false })
}

/** The user behind the session cookie; rejects with NOT_SIGNED_IN when there is none. */
export function fetchCurrentUser(): Promise<CurrentUser> {
  return api<CurrentUser>('/auth/me')
}
