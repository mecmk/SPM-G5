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
  | 'LOGIN_LOCKED'
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
  | 'EVENT_NOT_FOUND'
  | 'EVENT_ALREADY_SUBMITTED'
  | 'EVENT_ROUTINE_EDIT_CLOSED'
  | 'EVENT_NOT_AWAITING_DECISION'
  | 'EVENT_REJECTION_REASON_REQUIRED'
  | 'EVENT_NAME_REQUIRED'
  | 'EVENT_END_BEFORE_START'
  | 'EVENT_DATE_IN_PAST'
  | 'EVENT_DATE_INVALID'
  | 'EVENT_DATE_INCOMPLETE'
  | 'EVENT_TOO_FAR_AHEAD'
  | 'EVENT_TOO_LONG'
  | 'EVENT_ATTENDANCE_INVALID'
  | 'EVENT_FACILITY_QUANTITY_INVALID'
  | 'EVENT_EQUIPMENT_TYPE_REQUIRED'
  | 'EVENT_EQUIPMENT_DUPLICATE'
  | 'EVENT_EQUIPMENT_UNAVAILABLE'
  | 'EVENT_QUANTITY_INVALID'
  | 'EVENT_CONTACT_EMAIL_INVALID'
  | 'EVENT_CONTACT_PHONE_INVALID'
  | 'EVENT_PICTURE_TYPE_INVALID'
  | 'EVENT_PICTURE_TOO_LARGE'
  | 'BOOKING_NOT_ALLOWED'
  | 'BOOKING_NOT_FOUND'
  | 'BOOKING_CONFLICT'
  | 'BOOKING_REJECT_REFUSED'
  | 'BOOKING_REASON_REQUIRED'

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
  /**
   * Story 1.1 AC6: keep in step with `LOGIN_LOCKED_MESSAGE` in backend/app/auth/router.py. Shown
   * only for a 429 carrying neither that sentence nor a Retry-After for `SignInLockedAlert`.
   */
  LOGIN_LOCKED: {
    title: 'Sign-in locked',
    message: 'Too many failed sign-in attempts. Try again later.',
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

  // Story 2.1: event requests. These API codes usually arrive with the backend's own sentence.
  EVENT_NOT_FOUND: {
    title: 'Request not found',
    message: 'This request does not exist, or it is not yours to open.',
  },
  EVENT_ALREADY_SUBMITTED: {
    title: 'Request already submitted',
    message: 'This request has been submitted and can no longer be changed.',
  },
  /** Story 7.2 AC3. */
  EVENT_ROUTINE_EDIT_CLOSED: {
    title: 'No longer editable',
    message: 'This event is completed, cancelled or rejected, so it can no longer be edited.',
  },
  /**
   * Stories 4.4/4.5: approving or rejecting a request that has already been decided, or is
   * still a draft. One code for both actions, same precedent as BOOKING_CONFLICT: the backend
   * gives each its own detail sentence naming which verb was refused and the request's current
   * status.
   */
  EVENT_NOT_AWAITING_DECISION: {
    title: 'Cannot decide this request',
    message: 'This request cannot be approved or rejected in its current state.',
  },
  /**
   * Story 4.5 AC1: the reject dialog's own pre-check before calling the API. Never wired into an
   * `errorCodes` map, same as `EVENT_NAME_REQUIRED` below - a blank/whitespace reason that did
   * reach the backend would be refused by `EventRejection`'s plain field validation before
   * `reject_event` runs, coming back as a raw validation 422 rather than a sentence.
   */
  EVENT_REJECTION_REASON_REQUIRED: {
    title: 'Reason needed',
    message: 'Enter a reason for rejecting this request.',
  },

  // Story 2.1: checks the request form makes before anything is sent.
  EVENT_NAME_REQUIRED: {
    title: 'Event name needed',
    message: 'Enter a name for the event.',
  },
  /** Story 2.1 AC2. */
  EVENT_END_BEFORE_START: {
    title: 'Check the dates',
    message: 'The proposed end date and time must be after the start date and time.',
  },
  /** Story 2.1 AC2. */
  EVENT_DATE_IN_PAST: {
    title: 'Check the dates',
    message: 'The proposed date and time cannot be in the past.',
  },
  /** Story 2.1 AC2: the backend allows a start at most 2 years ahead. */
  EVENT_TOO_FAR_AHEAD: {
    title: 'Check the dates',
    message: 'The proposed start cannot be more than 2 years from now.',
  },
  /** Story 2.1 AC2: the backend allows an event to run for at most 14 days. */
  EVENT_TOO_LONG: {
    title: 'Check the dates',
    message: 'An event cannot run for more than 14 days.',
  },
  EVENT_DATE_INCOMPLETE: {
    title: 'Check the dates',
    message:
      'Finish entering the date and time, including AM or PM. If every part is filled in, ' +
      'check the day exists in that month: 29 February is only valid in a leap year, and ' +
      'there is no 31st in April, June, September or November.',
  },
  EVENT_DATE_INVALID: {
    title: 'Check the dates',
    message: 'Enter a valid date and time, with a four-digit year.',
  },
  /** Story 2.1 AC3. */
  EVENT_ATTENDANCE_INVALID: {
    title: 'Check the attendance',
    message: 'Expected attendance must be a positive whole number.',
  },
  /** Story 2.1 AC3. */
  EVENT_FACILITY_QUANTITY_INVALID: {
    title: 'Check the quantity',
    message: 'A facility quantity must be a positive whole number, or left empty.',
  },
  EVENT_EQUIPMENT_TYPE_REQUIRED: {
    title: 'Choose the equipment',
    message: 'Choose a type for every equipment item, or remove it.',
  },
  /** Story 2.1 AC6: the backend refuses more than is free for the dates. */
  EVENT_EQUIPMENT_UNAVAILABLE: {
    title: 'Not enough equipment',
    message: 'Request no more than is available for these dates.',
  },
  EVENT_EQUIPMENT_DUPLICATE: {
    title: 'Check the equipment',
    message: 'Each equipment type can appear only once on a request.',
  },
  /** Story 2.1 AC3. */
  EVENT_QUANTITY_INVALID: {
    title: 'Check the quantity',
    message: 'Equipment quantity must be a positive whole number.',
  },
  /** Story 2.1 AC13: worded as the backend words it. */
  EVENT_CONTACT_EMAIL_INVALID: {
    title: 'Check the contact email',
    message: 'Enter an email address like name@example.com.',
  },
  /** Story 2.1 AC13. */
  EVENT_CONTACT_PHONE_INVALID: {
    title: 'Check the contact phone number',
    message: 'Enter a phone number with 8 to 15 digits.',
  },
  /** Story 2.1 AC14. */
  EVENT_PICTURE_TYPE_INVALID: {
    title: 'Check the picture',
    message: 'Choose a JPEG, PNG or WebP picture.',
  },
  /** Story 2.1 AC14: the backend answers 413 to the same limit. */
  EVENT_PICTURE_TOO_LARGE: {
    title: 'Check the picture',
    message: 'The picture must be 5 MB or smaller.',
  },

  /**
   * Story 12.1 AC1: the event is not approved, or the venue has been withdrawn. The backend
   * names which in its own sentence, so this is only the fallback and the notification title.
   */
  BOOKING_NOT_ALLOWED: {
    title: 'Venue cannot be requested',
    message: 'A venue booking can only be requested for an approved event.',
  },

  // Story 13.2: approving a venue booking request. Both usually arrive with the backend's own
  // sentence - BOOKING_CONFLICT covers a double-booking and a request already decided alike,
  // since the backend gives each its own detail message under the same 409 status.
  BOOKING_NOT_FOUND: {
    title: 'Booking not found',
    message: 'This booking request no longer exists.',
  },
  BOOKING_CONFLICT: {
    title: 'Cannot approve this request',
    message: 'This request cannot be approved in its current state.',
  },

  // Story 13.2.1: rejecting a venue booking request. Rejection never runs the venue-conflict
  // check (only an approval can double-book), so its only 409 cause is "not pending" - named
  // for the reject endpoint specifically (rather than a generic BOOKING_NOT_PENDING) so its
  // reject-only wording can't end up on approve's toast if that 409 is ever mapped here too.
  BOOKING_REJECT_REFUSED: {
    title: 'Cannot reject this request',
    message: 'This request cannot be rejected in its current state.',
  },

  // Story 13.2.1: checks the reject dialog makes before anything is sent.
  BOOKING_REASON_REQUIRED: {
    title: 'Reason needed',
    message: 'Enter a reason for rejecting this request.',
  },
}

/** Registry codes an endpoint assigns to specific HTTP statuses, e.g. `{ 409: 'CONFLICT' }`. */
/**
 * Story 1.1 AC6: the sign-in page's live lock message. `lead` is followed by the minutes left
 * (`formatTimeLeft`), counting down; `ended` replaces it once the time is up.
 */
export const LOGIN_LOCKED_COUNTDOWN = {
  lead: 'Too many failed sign-in attempts. Try again in',
  ended: 'You can try signing in again now.',
} as const

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
