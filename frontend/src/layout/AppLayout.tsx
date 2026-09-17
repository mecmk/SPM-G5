import { Outlet, useNavigate } from 'react-router'
import { useAuth } from '../auth/authContext'
import { Sidebar, type SidebarNavItem } from '../components/Sidebar'
import { HOME_PATH, LOGIN_PATH } from '../routes'

const NAV_ITEMS: SidebarNavItem[] = [{ label: 'Home', to: HOME_PATH }]

/**
 * Story 1.1: the signed-in frame. The sidebar shows who is signed in and a way to sign out (AC5).
 */
export function AppLayout() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  async function handleSignOut() {
    try {
      await signOut()
    } catch {
      // The local session is already cleared by signOut, so the browser is signed out either way.
    }
    navigate(LOGIN_PATH, { replace: true })
  }

  return (
    <div className="app-shell">
      <Sidebar
        navItems={NAV_ITEMS}
        userName={user?.full_name ?? ''}
        userRole={user?.role_name ?? ''}
        onSignOut={handleSignOut}
      />
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
