/**
 * Error registry: every failure the frontend can show a user, in one place.
 *
 * Each entry has a stable code, a short title and a fallback message. When the backend sends a
 * sentence of its own in `detail` (its messages are complete sentences by rule, see
 * backend/STYLE.md), the UI shows that sentence, so the wording a test asserts on is owned by one
 * side only. The registry supplies the message when the backend sent none, such as a network
 * failure or an empty 500, and names every failure so pages can branch on `error.code` rather than
 * on status numbers or message text.
 *
 * Adding an error: add the code to `ErrorCode` and `ERROR_REGISTRY`, then map it to the status an
 * endpoint returns with the `errorCodes` option in `src/api/<feature>.ts`.
 */

export type ErrorCode =
  | 'NETWORK_UNAVAILABLE'
  | 'VALIDATION_FAILED'
  | 'NOT_SIGNED_IN'
  | 'NOT_PERMITTED'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'SERVER_ERROR'
  | 'UNEXPECTED'
  | 'INVALID_CREDENTIALS'

export interface ErrorEntry {
  title: string
  message: string
}

export const ERROR_REGISTRY: Record<ErrorCode, ErrorEntry> = {
  NETWORK_UNAVAILABLE: {
    title: 'Cannot reach ConnectSphere',
    message: 'The server could not be reached. Check your connection and try again.',
  },
  VALIDATION_FAILED: {
    title: 'Check your details',
    message: 'Some of the details you entered are not valid.',
  },
  NOT_SIGNED_IN: {
    title: 'Signed out',
    message: 'Your session has ended. Sign in again to continue.',
  },
  NOT_PERMITTED: {
    title: 'Not permitted',
    message: 'Your role does not permit this action.',
  },
  NOT_FOUND: {
    title: 'Not found',
    message: 'The record you asked for does not exist or was removed.',
  },
  CONFLICT: {
    title: 'Conflicting change',
    message: 'This change conflicts with an existing record.',
  },
  SERVER_ERROR: {
    title: 'Something went wrong',
    message: 'The server hit a problem. Try again in a moment.',
  },
  UNEXPECTED: {
    title: 'Something went wrong',
    message: 'An unexpected error occurred. Try again.',
  },
  /** Story 1.1 AC2: one message for a wrong password and an unknown email alike. */
  INVALID_CREDENTIALS: {
    title: 'Sign-in failed',
    message: 'Invalid email or password.',
  },
}

/** Registry codes an endpoint assigns to specific HTTP statuses, e.g. `{ 409: 'CONFLICT' }`. */
export type StatusErrorCodes = Partial<Record<number, ErrorCode>>

const STATUS_DEFAULTS: StatusErrorCodes = {
  400: 'VALIDATION_FAILED',
  401: 'NOT_SIGNED_IN',
  403: 'NOT_PERMITTED',
  404: 'NOT_FOUND',
  409: 'CONFLICT',
  422: 'VALIDATION_FAILED',
}

const FIRST_SERVER_ERROR_STATUS = 500

/** The registry code for an HTTP failure, preferring the endpoint's own mapping. */
export function errorCodeForStatus(
  status: number,
  endpointCodes: StatusErrorCodes = {},
): ErrorCode {
  const mapped = endpointCodes[status] ?? STATUS_DEFAULTS[status]
  if (mapped) return mapped
  return status >= FIRST_SERVER_ERROR_STATUS ? 'SERVER_ERROR' : 'UNEXPECTED'
}
