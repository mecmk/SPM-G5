import { Link, NavLink } from 'react-router'
import { HOME_PATH } from '../routes'

export interface SidebarNavItem {
  label: string
  /** Route path. The link shows as active only on this exact path. */
  to: string
  /** Section heading this item is grouped under. Items without one render first, ungrouped. */
  group?: string
}

export interface SidebarProps {
  navItems: SidebarNavItem[]
  userName: string
  userRole: string
  /** Omit to hide the sign-out control. */
  onSignOut?: () => void
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
 * items to pass. Story 1.1 - links are router `NavLink`s, which mark the current page active, and
 * the wordmark links to the main page. The page's own `<h1>` is its heading, so the wordmark is
 * not one.
 */
export function Sidebar({ navItems, userName, userRole, onSignOut }: SidebarProps) {
  const groups = groupNavItems(navItems)

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <Link to={HOME_PATH} className="wordmark">
          Connect<em>Sphere</em>
        </Link>
        <span className="wordmark-tagline">Event Management</span>
      </div>

      <nav className="sidebar-nav" aria-label="Main">
        {groups.map((group) => (
          <div key={group.label ?? '_ungrouped'} className="nav-group">
            {group.label && <div className="nav-group-label">{group.label}</div>}
            {group.items.map((item) => (
              <NavLink key={item.to} to={item.to} end>
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-user">
          <div className="user-name">{userName}</div>
          <div className="user-role">{userRole}</div>
        </div>
        {onSignOut && (
          <button type="button" className="sidebar-signout" onClick={onSignOut}>
            Sign out
          </button>
        )}
      </div>
    </aside>
  )
}
