import { Link } from 'react-router'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import type { NavItem } from '../layout/navigation'
import { HOME_PATH } from '../routes'

/**
 * Story 1.2 AC2: a section the role can use whose page another story is still building. It keeps
 * the sidebar complete and says which story delivers the page.
 */
export function ComingSoonPage({ item }: { item: NavItem }) {
  return (
    <div className="page">
      <p className="eyebrow">Story {item.story}</p>
      <PageHeader title={item.label} subtitle={item.description} />
      <div className="card notice-block">
        <span className="notice-icon">
          <Icon name={item.icon} size={28} />
        </span>
        <p className="notice-title">This page is on its way.</p>
        <p className="muted">
          It arrives with backlog story {item.story}. Your role already has access to it.
        </p>
        <Link to={HOME_PATH} className="button secondary button-sm">
          Back to your main page
        </Link>
      </div>
    </div>
  )
}
