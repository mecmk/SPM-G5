import type { InputEvent } from 'react'

/**
 * Guards for `onBeforeInput` that refuse a character a field can never hold, so the mistake is
 * rarely made rather than reported on save. React builds `onBeforeInput` from the browser's
 * `textInput` event where it has one (Chromium, Safari: typing and pasting) and from key presses
 * where it does not, so in Firefox a paste or a drop can get past it. The form's own checks still
 * run on save, for that and for what a guard cannot stop (an empty field, a value out of range).
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
