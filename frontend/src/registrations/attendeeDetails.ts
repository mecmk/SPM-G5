import type { AttendeeDetails, Profile } from '../api/registrations'
import { ERROR_REGISTRY } from '../errors/registry'
import { isBlankOrPhoneNumber } from '../shared/phone'

/** Story 18.4: the attendee's details as a form holds them - what was saved, or blank. */
export function detailsFrom(profile: Profile | null): AttendeeDetails {
  return {
    phone: profile?.phone ?? '',
    dietary_requirements: profile?.dietary_requirements ?? '',
  }
}

/** Story 18.4 AC7: what is wrong with the typed phone number, as a registry message, or null.
 *  Blank is fine: the phone number is optional. */
export function findPhoneProblem(phone: string): string | null {
  return isBlankOrPhoneNumber(phone) ? null : ERROR_REGISTRY.ATTENDEE_PHONE_INVALID.message
}
