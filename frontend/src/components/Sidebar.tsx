import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router'
import { HOME_PATH } from '../routes'
import { Icon, type IconName } from './Icon'

export interface SidebarNavItem {
  label: string
  /** Route path. The link shows as active only on this exact path. */
  to: string
  /** Section heading this item is grouped under. Items without one render first, ungrouped. */
  group?: string
  icon?: IconName
  /** A short tag after the label, e.g. "soon". Hidden from screen readers. */
  hint?: string
}

export interface SidebarProps {
  navItems: SidebarNavItem[]
  userName: string
  userRole: string
  /** Omit to hide the sign-out control. */
  onSignOut?: () => void
  /** Icons only. Each link keeps its label as its accessible name. */
  isCollapsed?: boolean
  /** Shows the collapse control when given. */
  onToggleCollapsed?: () => void
  /** Called after a link is chosen, e.g. to close the phone drawer. */
  onNavigate?: () => void
  /** Extra controls beside the wordmark, e.g. the drawer's close button. */
  brandActions?: ReactNode
}

interface SidebarNavGroup {
  label: string | null
  items: SidebarNavItem[]
}

function groupNavItems(items: SidebarNavItem[]): SidebarNavGroup[] {
  const groups: SidebarNavGroup[] = []
  for (const item of items) {
    const label = item.group ?? null
    const existingGroup = groups.find((group) => group.label === label)
    if (existingGroup) {
      existingGroup.items.push(item)
    } else {
      groups.push({ label, items: [item] })
    }
  }
  return groups
}

/**
 * Story c3 - the prototype's sidebar shell. Presentational: the page assembling it decides which
 * items to pass.
 * Story 1.1 - links are router `NavLink`s, which mark the current page active, and the wordmark
 * links to the main page. The page's own `<h1>` is its heading, so the wordmark is not one.
 * Story 1.2 - it collapses to icons (team decision, 17 Sep 2026), and the same component fills
 * the phone drawer.
 */
export function Sidebar({
  navItems,
  userName,
  userRole,
  onSignOut,
  isCollapsed = false,
  onToggleCollapsed,
  onNavigate,
  brandActions,
}: SidebarProps) {
  const groups = groupNavItems(navItems)
  const toggleLabel = isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'

  return (
    <aside className={isCollapsed ? 'sidebar is-collapsed' : 'sidebar'}>
      <div className="sidebar-brand">
        {!isCollapsed && (
          <div>
            <Link to={HOME_PATH} className="wordmark" onClick={onNavigate}>
              Connect<em>Sphere</em>
            </Link>
            <span className="wordmark-tagline">Event Management</span>
          </div>
        )}
        {(brandActions || onToggleCollapsed) && (
          <div className="sidebar-brand-actions">
            {brandActions}
            {onToggleCollapsed && (
              <button
                type="button"
                className="icon-button"
                aria-label={toggleLabel}
                aria-expanded={!isCollapsed}
                title={toggleLabel}
                onClick={onToggleCollapsed}
              >
                <Icon name="sidebar" />
              </button>
            )}
          </div>
        )}
      </div>

      <nav className="sidebar-nav" aria-label="Main">
        {groups.map((group) => (
          <div key={group.label ?? '_ungrouped'} className="nav-group">
            {group.label &&
              (isCollapsed ? (
                <hr className="nav-group-divider" />
              ) : (
                <div className="nav-group-label">{group.label}</div>
              ))}
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                aria-label={isCollapsed ? item.label : undefined}
                title={isCollapsed ? item.label : undefined}
                onClick={onNavigate}
              >
                {item.icon && <Icon name={item.icon} />}
                {!isCollapsed && (
                  <span className="nav-label" title={item.label}>
                    {item.label}
                  </span>
                )}
                {!isCollapsed && item.hint && (
                  <span className="nav-hint" aria-hidden="true">
                    {item.hint}
                  </span>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        {!isCollapsed && (
          <div className="sidebar-user">
            <div className="user-name">{userName}</div>
            <div className="user-role">{userRole}</div>
          </div>
        )}
        {onSignOut && (
          <button
            type="button"
            className="sidebar-signout"
            aria-label={isCollapsed ? 'Sign out' : undefined}
            title={isCollapsed ? 'Sign out' : undefined}
            onClick={onSignOut}
          >
            {isCollapsed ? <Icon name="sign-out" /> : 'Sign out'}
          </button>
        )}
      </div>
    </aside>
  )
}
