import { useState } from 'react'
import { Link, Outlet, useNavigate } from 'react-router'
import { useAuth } from '../auth/authContext'
import { Icon } from '../components/Icon'
import { Sidebar, type SidebarNavItem } from '../components/Sidebar'
import { NotificationBell } from '../notifications/NotificationBell'
import { ToastStack } from '../notifications/ToastStack'
import { HOME_PATH, LOGIN_PATH } from '../routes'
import { visibleNavSections, type NavSection } from './navigation'

const SIDEBAR_COLLAPSED_KEY = 'connectsphere.sidebarCollapsed'
const COMING_SOON_HINT = 'soon'

function readCollapsedPreference(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

function saveCollapsedPreference(isCollapsed: boolean): void {
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(isCollapsed))
  } catch {
    // Storage can be unavailable (private windows); the choice then lasts for this visit only.
  }
}

function sidebarItems(sections: NavSection[]): SidebarNavItem[] {
  const home: SidebarNavItem = { label: 'Home', to: HOME_PATH, icon: 'home' }
  const sectionItems = sections.flatMap((section) =>
    section.items.map((item) => ({
      label: item.label,
      to: item.to,
      group: section.label,
      icon: item.icon,
      hint: item.isAvailable ? undefined : COMING_SOON_HINT,
    })),
  )
  return [home, ...sectionItems]
}

/**
 * The signed-in frame.
 * Story 1.1: the sidebar shows who is signed in and a way to sign out (AC5).
 * Story 1.2 AC2: the sidebar lists only the role's sections. It collapses to icons on a wide
 * screen and becomes a drawer on a phone (team decision, 17 Sep 2026).
 * Story 8.3: the notification centre's bell sits beside the wordmark, and toasts appear bottom
 * right.
 */
export function AppLayout() {
  const { user, can, signOut } = useAuth()
  const navigate = useNavigate()
  const [isCollapsed, setIsCollapsed] = useState(readCollapsedPreference)
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)
  const navItems = sidebarItems(visibleNavSections(can))
  const userName = user?.full_name ?? ''
  const userRole = user?.role_name ?? ''

  function toggleCollapsed() {
    const nextIsCollapsed = !isCollapsed
    setIsCollapsed(nextIsCollapsed)
    saveCollapsedPreference(nextIsCollapsed)
  }

  function openDrawer() {
    setIsDrawerOpen(true)
  }

  function closeDrawer() {
    setIsDrawerOpen(false)
  }

  async function handleSignOut() {
    try {
      await signOut()
    } catch {
      // The local session is already cleared by signOut, so the browser is signed out either way.
    }
    navigate(LOGIN_PATH, { replace: true })
  }

  return (
    <div className="app-shell has-mobile-bar">
      <Sidebar
        navItems={navItems}
        userName={userName}
        userRole={userRole}
        onSignOut={handleSignOut}
        isCollapsed={isCollapsed}
        onToggleCollapsed={toggleCollapsed}
        brandActions={<NotificationBell />}
      />

      <header className="mobile-bar">
        <button
          type="button"
          className="icon-button"
          aria-label="Open menu"
          aria-expanded={isDrawerOpen}
          onClick={openDrawer}
        >
          <Icon name="menu" />
        </button>
        <Link to={HOME_PATH} className="wordmark">
          Connect<em>Sphere</em>
        </Link>
        <div className="mobile-bar-actions">
          <NotificationBell />
          <button type="button" className="secondary button-sm" onClick={handleSignOut}>
            Sign out
          </button>
        </div>
      </header>

      {isDrawerOpen && (
        <>
          <div className="drawer-backdrop" onClick={closeDrawer} />
          <div className="drawer" role="dialog" aria-modal="true" aria-label="Menu">
            <Sidebar
              navItems={navItems}
              userName={userName}
              userRole={userRole}
              onNavigate={closeDrawer}
              brandActions={
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Close menu"
                  onClick={closeDrawer}
                >
                  <Icon name="close" />
                </button>
              }
            />
          </div>
        </>
      )}

      <main className="app-main">
        <Outlet />
      </main>
      <ToastStack />
    </div>
  )
}
