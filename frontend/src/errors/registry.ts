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
  | 'VENUE_NOT_FOUND'
  | 'VENUE_NAME_TAKEN'
  | 'VENUE_IN_USE'
  | 'VENUE_NAME_REQUIRED'
  | 'VENUE_LOCATION_REQUIRED'
  | 'VENUE_CAPACITY_INVALID'
  | 'VENUE_FLOOR_AREA_INVALID'
  | 'VENUE_HOURS_INCOMPLETE'
  | 'VENUE_HOURS_OUT_OF_ORDER'
  | 'VENUE_TURNAROUND_INVALID'
  | 'VENUE_QUANTITY_INVALID'
  | 'VENUE_LAYOUT_CAPACITY_INVALID'

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

  // Story 8.3: venue records. These API codes usually arrive with the backend's own sentence.
  VENUE_NOT_FOUND: {
    title: 'Venue not found',
    message: 'This venue no longer exists. It may have been deleted.',
  },
  VENUE_NAME_TAKEN: {
    title: 'Venue name already used',
    message: 'Another venue already has this name. Choose a different one.',
  },
  VENUE_IN_USE: {
    title: 'Venue has bookings',
    message: 'You cannot delete a venue that has bookings. Withdraw it from service instead.',
  },

  // Story 8.3: checks the venue form makes before anything is sent.
  VENUE_NAME_REQUIRED: {
    title: 'Venue name needed',
    message: 'Enter a name for the venue.',
  },
  VENUE_LOCATION_REQUIRED: {
    title: 'Location needed',
    message: 'Enter where the venue is.',
  },
  /** Story 8.3 AC3. */
  VENUE_CAPACITY_INVALID: {
    title: 'Check the capacity',
    message: 'Capacity must be a positive whole number.',
  },
  VENUE_FLOOR_AREA_INVALID: {
    title: 'Check the floor area',
    message: 'Floor area must be a number above zero, with at most two decimal places.',
  },
  VENUE_HOURS_INCOMPLETE: {
    title: 'Check the operating hours',
    message: 'Enter both an opening and a closing time, or leave both empty.',
  },
  VENUE_HOURS_OUT_OF_ORDER: {
    title: 'Check the operating hours',
    message: 'The closing time must be after the opening time.',
  },
  VENUE_TURNAROUND_INVALID: {
    title: 'Check setup and teardown',
    message: 'Setup and teardown times must be whole numbers of minutes, zero or more.',
  },
  VENUE_QUANTITY_INVALID: {
    title: 'Check facility quantities',
    message: 'A facility quantity must be a positive whole number, or left empty.',
  },
  VENUE_LAYOUT_CAPACITY_INVALID: {
    title: 'Check layout capacities',
    message: 'A layout capacity must be a positive whole number, or left empty.',
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
