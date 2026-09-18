import type { ReactNode } from 'react'
import { Link } from 'react-router'

export interface PageHeaderProps {
  title: string
  subtitle?: ReactNode
  action?: ReactNode
  /** Route path for the back link above the title. */
  backTo?: string
  backLabel?: string
}

/** Story c3 - the title block at the top of a page, with an optional back link and action button. */
export function PageHeader({ title, subtitle, action, backTo, backLabel }: PageHeaderProps) {
  return (
    <div>
      {backTo && (
        <Link to={backTo} className="back-link">
          ← {backLabel ?? 'Back'}
        </Link>
      )}
      <div className="page-header">
        <div>
          <h1>{title}</h1>
          {subtitle && <p className="page-subtitle">{subtitle}</p>}
        </div>
        {action && <div className="page-actions">{action}</div>}
      </div>
    </div>
  )
}
