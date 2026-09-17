/**
 * The single fetch wrapper every API module goes through.
 *
 * - Sends the session cookie on every call (story 1.1).
 * - Turns every failure into an `ApiError` carrying a registry code (src/errors/registry.ts), so
 *   pages show `formatApiError(error)` and can branch on `error.code`.
 * - Reports the outcome of every POST, PUT, PATCH and DELETE to the notification centre (team
 *   decision, 17 Sep 2026), through `subscribeToMutations`.
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

export type NotificationImportance = 'important' | 'routine'

/** What the notification centre says when a change succeeds. */
export interface MutationNotice {
  title: string
  message: string
  importance?: NotificationImportance
}

/** The result of one POST, PUT, PATCH or DELETE, as the notification centre receives it. */
export interface MutationOutcome {
  isSuccess: boolean
  title: string
  message: string
  importance: NotificationImportance
}

export interface RequestOptions {
  method?: HttpMethod
  body?: unknown
  /** Registry codes for statuses this endpoint gives a specific meaning. */
  errorCodes?: StatusErrorCodes
  /**
   * The notice for a successful change. `false` keeps the call out of the notification centre;
   * only sign-in and sign-out use it, because they change who is signed in.
   */
  notify?: MutationNotice | false
}

type MutationListener = (outcome: MutationOutcome) => void

const mutationListeners = new Set<MutationListener>()

const DEFAULT_SUCCESS_NOTICE: MutationNotice = {
  title: 'Change saved',
  message: 'Your change was saved.',
}

/** Receive the outcome of every change request. Returns the function that stops listening. */
export function subscribeToMutations(listener: MutationListener): () => void {
  mutationListeners.add(listener)
  return () => {
    mutationListeners.delete(listener)
  }
}

function reportMutation(outcome: MutationOutcome): void {
  mutationListeners.forEach((listener) => listener(outcome))
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

async function send<T>(
  path: string,
  method: HttpMethod,
  body: unknown,
  errorCodes: StatusErrorCodes | undefined,
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

export async function api<T>(
  path: string,
  { method = 'GET', body, errorCodes, notify }: RequestOptions = {},
): Promise<T> {
  const isReported = method !== 'GET' && notify !== false
  try {
    const result = await send<T>(path, method, body, errorCodes)
    if (isReported) {
      const notice = notify ?? DEFAULT_SUCCESS_NOTICE
      reportMutation({
        isSuccess: true,
        title: notice.title,
        message: notice.message,
        importance: notice.importance ?? 'routine',
      })
    }
    return result
  } catch (error) {
    if (isReported && error instanceof ApiError) {
      reportMutation({
        isSuccess: false,
        title: ERROR_REGISTRY[error.code].title,
        message: error.message,
        importance: 'important',
      })
    }
    throw error
  }
}
