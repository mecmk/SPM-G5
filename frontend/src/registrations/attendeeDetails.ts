import type { AttendeeDetails, Profile } from '../api/registrations'
import { ERROR_REGISTRY } from '../errors/registry'
import { isBlankOrPhoneNumber } from '../shared/phone'

/** Story 18.4: the attendee's details as a form holds them - what was saved, or blank. */
export function detailsFrom(profile: Profile | null): AttendeeDetails {
  return {
    full_name: profile?.full_name ?? '',
    phone: profile?.phone ?? '',
    dietary_requirements: profile?.dietary_requirements ?? '',
  }
}

/**
 * Story 18.4 AC3: the profile as a registration just saved it, before it is read again: the
 * details confirmed with it, trimmed, and blank dietary requirements as no value, as the server
 * stores them. So the next dialog - and the frame's name - shows what was confirmed, even when
 * reading the profile again is slow or fails (review of #129).
 */
export function withConfirmedDetails(profile: Profile, details: AttendeeDetails): Profile {
  const dietaryRequirements = details.dietary_requirements.trim()
  return {
    ...profile,
    full_name: details.full_name.trim(),
    phone: details.phone.trim(),
    dietary_requirements: dietaryRequirements === '' ? null : dietaryRequirements,
    has_confirmed_details: true,
  }
}

/** Story 18.4 AC1: what is wrong with the typed name, as a registry message, or null. */
export function findAttendeeNameProblem(name: string): string | null {
  return name.trim() === '' ? ERROR_REGISTRY.ATTENDEE_NAME_REQUIRED.message : null
}

/** Story 18.4 AC7: what is wrong with the typed phone number, as a registry message, or null.
 *  It is required, and follows the event contact phone's rule (2.1 AC13). */
export function findAttendeePhoneProblem(phone: string): string | null {
  if (phone.trim() === '') return ERROR_REGISTRY.ATTENDEE_PHONE_REQUIRED.message
  return isBlankOrPhoneNumber(phone) ? null : ERROR_REGISTRY.ATTENDEE_PHONE_INVALID.message
}
