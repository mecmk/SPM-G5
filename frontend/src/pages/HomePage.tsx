import { useAuth } from '../auth/authContext'
import { PageHeader } from '../components/PageHeader'

/** Story 1.1 AC4: the page a user lands on after signing in. */
export function HomePage() {
  const { user } = useAuth()
  if (!user) return null

  return (
    <div className="page">
      <p className="eyebrow">
        {user.role_name}
        {user.organisation_name ? ` · ${user.organisation_name}` : ''}
      </p>
      <PageHeader
        title={`Welcome, ${user.full_name}`}
        subtitle="You are signed in to ConnectSphere."
      />
    </div>
  )
}
