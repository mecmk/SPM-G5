import { HOME_PATH, LOGIN_PATH } from '../routes'

/**
 * Story 1.1 AC4: where a user goes after signing in. A visitor who was bounced to sign-in goes
 * back to the page they asked for; everyone else lands on the main page. To send a role somewhere
 * else, check one of its permissions here, never `role_code` (frontend/CLAUDE.md).
 */
export function homeFor(requestedPath: string | undefined): string {
  if (!requestedPath || requestedPath === LOGIN_PATH) return HOME_PATH
  const isInAppPath = requestedPath.startsWith('/') && !requestedPath.startsWith('//')
  return isInAppPath ? requestedPath : HOME_PATH
}
