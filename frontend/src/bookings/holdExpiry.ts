import { ERROR_REGISTRY } from '../errors/registry'
import { inputToInstant } from '../shared/format'

/** Story 12.7 AC5: what the server would refuse in an expiry Venue Staff give a hold - as they
 * approve the request, or when they change it - so it is refused before anything is sent: none
 * given, not in the future, or after the booked period starts (`heldFrom`). Null when it may be
 * sent. `input` is a `datetime-local` value, read as Singapore time. */
export function holdExpiryRefusal(input: string, heldFrom: string): string | null {
  if (input === '') return ERROR_REGISTRY.BOOKING_HOLD_EXPIRY_REQUIRED.message
  const expiresAt = Date.parse(inputToInstant(input))
  if (expiresAt <= Date.now()) return ERROR_REGISTRY.BOOKING_HOLD_EXPIRY_IN_PAST.message
  if (expiresAt > Date.parse(heldFrom)) {
    return ERROR_REGISTRY.BOOKING_HOLD_EXPIRY_AFTER_START.message
  }
  return null
}
