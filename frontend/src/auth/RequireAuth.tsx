import { Navigate, Outlet, useLocation } from 'react-router'
import { LoadingState } from '../layout/LoadingState'
import { NotPermittedPage } from '../pages/NotPermittedPage'
import { LOGIN_PATH } from '../routes'
import { useAuth } from './authContext'
import type { Permission } from './permissions'

/** Story 1.1 AC4: send signed-out visitors to sign-in, remembering where they were headed. */
export function RequireAuth() {
  const { user, isLoading, hasSignedOut } = useAuth()
  const location = useLocation()
  if (isLoading) return <LoadingState label="Checking your session…" />
  if (!user) {
    // Chore c18: after a sign-out the next sign-in, maybe by another role, starts at the main page.
    const state = hasSignedOut ? undefined : { from: location.pathname }
    return <Navigate to={LOGIN_PATH} replace state={state} />
  }
  return <Outlet />
}

/**
 * Story 1.2 AC3/AC4: a direct URL to a page outside the role shows "Not permitted" instead of the
 * page. This is a courtesy; the backend refuses the page's API calls regardless.
 */
export function RequirePermission({ permission }: { permission: Permission }) {
  const { can } = useAuth()
  if (!can(permission)) return <NotPermittedPage />
  return <Outlet />
}
