import { Link } from 'react-router'
import { useAuth } from '../auth/authContext'
import { Chip } from '../components/Chip'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { visibleNavSections } from '../layout/navigation'

/**
 * Story 1.1 AC4: the page a user lands on after signing in.
 * Story 1.2 AC2: it lists every section the role can use, the same set as the sidebar.
 */
export function HomePage() {
  const { user, can } = useAuth()
  if (!user) return null
  const sections = visibleNavSections(can)

  return (
    <div className="page page-wide">
      <p className="eyebrow">
        {user.role_name}
        {user.organisation_name ? ` · ${user.organisation_name}` : ''}
      </p>
      <PageHeader
        title={`Welcome, ${user.full_name}`}
        subtitle="Everything your role can do in ConnectSphere is listed here and in the sidebar."
      />

      <div className="stack">
        {sections.map((section) => (
          <section key={section.label} aria-label={section.label}>
            <h2 className="eyebrow">{section.label}</h2>
            <div className="tile-grid">
              {section.items.map((item) => (
                <Link key={item.to} to={item.to} className="tile">
                  <span className="tile-icon">
                    <Icon name={item.icon} size={20} />
                  </span>
                  <h3 className="tile-title">{item.label}</h3>
                  <p className="tile-text">{item.description}</p>
                  {item.isAvailable ? (
                    <Chip label="Open" tone="success" />
                  ) : (
                    <Chip label={`Coming with story ${item.story}`} />
                  )}
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
