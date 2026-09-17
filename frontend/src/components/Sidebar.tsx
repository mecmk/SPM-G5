export interface SidebarNavItem {
  label: string
  href: string
  /** Section heading this item is grouped under. Items without one render first, ungrouped. */
  group?: string
  isActive?: boolean
}

export interface SidebarProps {
  navItems: SidebarNavItem[]
  userName: string
  userRole: string
  /** Omit to hide the sign-out control (e.g. while auth doesn't exist yet). */
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
 * Story c3 - the prototype's sidebar shell. Presentational only: it takes plain nav items and
 * knows nothing about routing or permissions - the page assembling it decides what to pass and
 * which item is active. Plain `<a>` tags for now; swap for `NavLink` once react-router is added
 * (`frontend/CLAUDE.md`). The wordmark is the page's site heading (accessible name
 * "ConnectSphere"), which `tests/e2e/health.spec.ts` looks for.
 */
export function Sidebar({ navItems, userName, userRole, onSignOut }: SidebarProps) {
  const groups = groupNavItems(navItems)

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <h1 className="wordmark">
          Connect<em>Sphere</em>
        </h1>
        <span className="wordmark-tagline">Event Management</span>
      </div>

      <nav className="sidebar-nav" aria-label="Main">
        {groups.map((group) => (
          <div key={group.label ?? '_ungrouped'} className="nav-group">
            {group.label && <div className="nav-group-label">{group.label}</div>}
            {group.items.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className={item.isActive ? 'active' : undefined}
                aria-current={item.isActive ? 'page' : undefined}
              >
                {item.label}
              </a>
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
