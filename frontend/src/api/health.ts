import { API_BASE_URL } from './client'

export interface HealthResponse {
  status: string
}

/**
 * Reachability check shown on the sign-in page. It needs no session, so it is the one call that
 * uses a bare `fetch` instead of `api()` (frontend/CLAUDE.md).
 */
export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`)
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`)
  }
  return response.json()
}
