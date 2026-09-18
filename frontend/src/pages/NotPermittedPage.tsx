import { Link } from 'react-router'
import { Icon } from '../components/Icon'
import { ERROR_REGISTRY } from '../errors/registry'
import { HOME_PATH } from '../routes'

/** Story 1.2 AC4: what a direct URL to a page outside the role shows instead of the page. */
export function NotPermittedPage() {
  return (
    <div className="page">
      <div className="card notice-block">
        <span className="notice-icon">
          <Icon name="lock" size={28} />
        </span>
        <h1>{ERROR_REGISTRY.NOT_PERMITTED.title}</h1>
        <p className="muted">{ERROR_REGISTRY.NOT_PERMITTED.message}</p>
        <Link to={HOME_PATH} className="button secondary button-sm">
          Back to your main page
        </Link>
      </div>
    </div>
  )
}
