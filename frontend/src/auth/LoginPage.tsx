import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router'
import { formatApiError } from '../api/client'
import { getHealth } from '../api/health'
import { LoadingState } from '../layout/LoadingState'
import { useAuth } from './authContext'
import { homeFor } from './homeFor'

const SAMPLE_PASSWORD = 'Password123!'

/** Seed accounts from backend/db/seed/020_sample_data.sql, offered in development builds only. */
const SAMPLE_ACCOUNTS: { role: string; email: string }[] = [
  { role: 'Event Organiser', email: 'organiser@acme.example' },
  { role: 'Event Coordinator', email: 'coordinator@connectsphere.example' },
  { role: 'Venue Staff', email: 'venue@connectsphere.example' },
  { role: 'Technical Support', email: 'tech@connectsphere.example' },
  { role: 'Attendee', email: 'attendee@example.com' },
]

const PLATFORM_FEATURES = [
  'Event requests and approvals',
  'Venue catalogue and bookings',
  'Equipment reservations',
  'Attendee registration',
  'Change requests',
  'Notifications for every update',
]

interface LocationState {
  from?: string
}

/** Story 1.1: sign in with an email and password. */
export function LoginPage() {
  const { user, isLoading, signIn } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [backendStatus, setBackendStatus] = useState('checking…')

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then((health) => {
        if (!cancelled) setBackendStatus(health.status)
      })
      .catch(() => {
        if (!cancelled) setBackendStatus('unreachable')
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Until `/auth/me` answers the session is unknown, so show the check instead of flashing the
  // sign-in form at someone who is already signed in. RequireAuth guards the same way.
  if (isLoading) return <LoadingState label="Checking your session…" />

  // Story 1.1 AC4: once signed in, continue to the requested page or the main page.
  if (user) {
    const requestedPath = (location.state as LocationState | null)?.from
    return <Navigate to={homeFor(requestedPath)} replace />
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await signIn(email.trim(), password)
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  function fillSampleAccount(sampleEmail: string) {
    setEmail(sampleEmail)
    setPassword(SAMPLE_PASSWORD)
  }

  return (
    <div className="login-page">
      <aside className="login-brand" aria-label="About ConnectSphere">
        <div>
          <p className="wordmark login-wordmark">
            Connect<em>Sphere</em>
          </p>
          <p className="wordmark-tagline">Event Management System</p>
        </div>
        <div className="login-brand-body">
          <p>
            One place to plan, coordinate and run events, from the first request to the day itself.
          </p>
          <ul className="login-feature-list">
            {PLATFORM_FEATURES.map((feature) => (
              <li key={feature}>{feature}</li>
            ))}
          </ul>
        </div>
        <p className="wordmark-tagline login-footnote">SMU IS212 · Team G5</p>
      </aside>

      <main className="login-panel">
        <div className="login-card">
          <h1>Sign in</h1>
          <p className="page-subtitle login-intro">Use the email and password for your account.</p>

          <form onSubmit={handleSubmit} aria-label="Sign in">
            <label>
              Email
              <input
                type="email"
                name="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label>
              Password
              <input
                type="password"
                name="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <p role="alert" className="error login-error">
                {error}
              </p>
            )}
            <button type="submit" className="button-block login-submit" disabled={isSubmitting}>
              {isSubmitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {import.meta.env.DEV && (
            <details className="sample-accounts">
              <summary>Sample accounts for local testing</summary>
              <p className="small muted">
                Every account uses the password <code>{SAMPLE_PASSWORD}</code>.
              </p>
              <ul className="sample-account-list">
                {SAMPLE_ACCOUNTS.map((account) => (
                  <li key={account.email}>
                    <button
                      type="button"
                      className="link"
                      onClick={() => fillSampleAccount(account.email)}
                    >
                      {account.role}
                    </button>
                    <span className="small muted"> · {account.email}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <p className="small muted login-status">
            Backend status: <strong>{backendStatus}</strong>
          </p>
        </div>
      </main>
    </div>
  )
}
