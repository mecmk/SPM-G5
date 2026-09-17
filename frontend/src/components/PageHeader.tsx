import type { ReactNode } from 'react'

export interface PageHeaderProps {
  title: string
  subtitle?: ReactNode
  action?: ReactNode
  /** Plain `<a>` for now; swap for a router `Link` once react-router is added. */
  backHref?: string
  backLabel?: string
}

/** Story c3 - the title block at the top of a page, with an optional back link and action button. */
export function PageHeader({ title, subtitle, action, backHref, backLabel }: PageHeaderProps) {
  return (
    <div>
      {backHref && (
        <a href={backHref} className="back-link">
          ← {backLabel ?? 'Back'}
        </a>
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
