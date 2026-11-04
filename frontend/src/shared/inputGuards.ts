import type { InputEvent } from 'react'

/**
 * Guards for `onBeforeInput` that refuse a character a field can never hold, as it is typed or
 * pasted, so the mistake is never made rather than reported on save. The form's own checks still
 * run on save, for what a guard cannot stop (an empty field, a value out of range).
 */

const NOT_DIGIT = /\D/
const NOT_DECIMAL = /[^\d.]/
const NOT_PHONE = /[^\d +-]/

function refuse(pattern: RegExp) {
  return (event: InputEvent<HTMLInputElement>) => {
    if (event.data && pattern.test(event.data)) event.preventDefault()
  }
}

/** A whole number: digits only, so no sign, decimal point or exponent. */
export const refuseNonDigits = refuse(NOT_DIGIT)

/** A decimal number: digits and a point. */
export const refuseNonDecimal = refuse(NOT_DECIMAL)

/** A phone number: digits, spaces, dashes and a +, as `shared/phone.ts` accepts. */
export const refuseNonPhone = refuse(NOT_PHONE)
