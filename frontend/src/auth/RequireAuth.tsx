import { Navigate, Outlet, useLocation } from 'react-router'
import { LoadingState } from '../layout/LoadingState'
import { LOGIN_PATH } from '../routes'
import { useAuth } from './authContext'

/** Story 1.1 AC4: send signed-out visitors to sign-in, remembering where they were headed. */
export function RequireAuth() {
  const { user, isLoading } = useAuth()
  const location = useLocation()
  if (isLoading) return <LoadingState label="Checking your session…" />
  if (!user) return <Navigate to={LOGIN_PATH} replace state={{ from: location.pathname }} />
  return <Outlet />
}
