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

const POINT = '.'
const refuseNotDecimal = refuse(NOT_DECIMAL)

/**
 * A decimal number: digits and one point. A second point is refused once the value shows one
 * (`1.2`); a number field reads a trailing point (`1.`) as `1`, so `1..` is left to the save check.
 */
export function refuseNonDecimal(event: InputEvent<HTMLInputElement>) {
  refuseNotDecimal(event)
  const points = (event.data ?? '').split(POINT).length - 1
  if (points > 1 || (points === 1 && event.currentTarget.value.includes(POINT))) {
    event.preventDefault()
  }
}

/** A phone number: digits, spaces, dashes and a +, as `shared/phone.ts` accepts. */
export const refuseNonPhone = refuse(NOT_PHONE)
