/**
 * The single fetch wrapper every API module goes through.
 *
 * - Sends the session cookie on every call (story 1.1).
 * - Turns every failure into an `ApiError` carrying a registry code (src/errors/registry.ts), so
 *   pages show `formatApiError(error)` and can branch on `error.code`.
 */
import {
  ERROR_REGISTRY,
  errorCodeForStatus,
  type ErrorCode,
  type StatusErrorCodes,
} from '../errors/registry'

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const JSON_HEADERS = { 'Content-Type': 'application/json' }
const NO_CONTENT_STATUS = 204
const REQUEST_BODY_LOCATION = 'body'

/** A FastAPI validation issue: `{ loc: ['body', 'capacity'], msg: '...' }`. */
interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

function describeValidationIssues(issues: ValidationIssue[]): string {
  return issues
    .map((issue) => {
      const field = (issue.loc ?? []).filter((part) => part !== REQUEST_BODY_LOCATION).join('.')
      const problem = issue.msg ?? ERROR_REGISTRY.VALIDATION_FAILED.message
      return field ? `${field}: ${problem}` : problem
    })
    .join('; ')
}

/** The backend's own sentence when it sent one, otherwise the registry's message for the code. */
function messageFor(code: ErrorCode, detail: unknown): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail) && detail.length > 0) return describeValidationIssues(detail)
  return ERROR_REGISTRY[code].message
}

export class ApiError extends Error {
  readonly status: number | null
  readonly code: ErrorCode
  readonly detail: unknown

  constructor(status: number | null, code: ErrorCode, detail: unknown) {
    super(messageFor(code, detail))
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

/** Text to show a user for any thrown value; non-API errors never leak their internals. */
export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return ERROR_REGISTRY.UNEXPECTED.message
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface RequestOptions {
  method?: HttpMethod
  body?: unknown
  /** Registry codes for statuses this endpoint gives a specific meaning. */
  errorCodes?: StatusErrorCodes
}

async function readPayload(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function detailOf(payload: unknown): unknown {
  if (payload && typeof payload === 'object' && 'detail' in payload) return payload.detail
  return payload
}

export async function api<T>(
  path: string,
  { method = 'GET', body, errorCodes }: RequestOptions = {},
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      credentials: 'include',
      headers: body === undefined ? undefined : JSON_HEADERS,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(null, 'NETWORK_UNAVAILABLE', null)
  }
  if (response.status === NO_CONTENT_STATUS) return undefined as T
  const payload = await readPayload(response)
  if (!response.ok) {
    throw new ApiError(
      response.status,
      errorCodeForStatus(response.status, errorCodes),
      detailOf(payload),
    )
  }
  return payload as T
}
