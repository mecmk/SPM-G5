/**
 * The phone number rule, shared by an event's point of contact (story 2.1 AC13) and an attendee's
 * details (story 18.4 AC7). Mirrored from backend/app/common/phone.py - keep the limits in step.
 */
const PHONE_NUMBER = /^\+?[\d -]+$/
export const PHONE_MAX_LENGTH = 50
const PHONE_MIN_DIGITS = 8
const PHONE_MAX_DIGITS = 15

/** Blank is fine, since a phone number is optional; anything typed must be 8 to 15 digits, with
 *  an optional leading "+", and spaces and dashes allowed, in at most 50 characters. */
export function isBlankOrPhoneNumber(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === '') return true
  const digitCount = trimmed.replace(/\D/g, '').length
  return (
    trimmed.length <= PHONE_MAX_LENGTH &&
    PHONE_NUMBER.test(trimmed) &&
    digitCount >= PHONE_MIN_DIGITS &&
    digitCount <= PHONE_MAX_DIGITS
  )
}
