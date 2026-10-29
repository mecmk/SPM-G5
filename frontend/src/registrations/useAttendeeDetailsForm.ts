import { useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react'
import type { AttendeeDetails } from '../api/registrations'
import { ATTENDEE_CHECKS, type DetailsChecks } from './attendeeDetails'

/** What a form of the attendee's details holds, for My profile and the details dialog alike. */
export interface AttendeeDetailsForm {
  details: AttendeeDetails
  setDetails: Dispatch<SetStateAction<AttendeeDetails>>
  /** Why the name cannot be saved, once a save was tried; null when it can. */
  nameProblem: string | null
  /** Why the phone number cannot be saved, once a save was tried; null when it can. */
  phoneProblem: string | null
  nameInput: RefObject<HTMLInputElement | null>
  phoneInput: RefObject<HTMLInputElement | null>
  /** Story 18.4 AC1/AC7: whether the details may be sent. When they may not, every problem is
   *  shown and the first field with one is focused, before anything is sent. */
  canSend: () => boolean
  /** Start again from `details`, with no problem shown: after a save. */
  reset: (details: AttendeeDetails) => void
}

/** Story 18.4: the state of a form of the attendee's details - or, AC12 (fix f18.4.1), with
 *  `GUEST_CHECKS`, of their guest's, which have the same three fields and rules. */
export function useAttendeeDetailsForm(
  initial: AttendeeDetails,
  checks: DetailsChecks = ATTENDEE_CHECKS,
): AttendeeDetailsForm {
  const nameInput = useRef<HTMLInputElement>(null)
  const phoneInput = useRef<HTMLInputElement>(null)
  const [details, setDetails] = useState(initial)
  const [isChecked, setIsChecked] = useState(false)

  function canSend(): boolean {
    setIsChecked(true)
    if (checks.findNameProblem(details.full_name) !== null) {
      nameInput.current?.focus()
      return false
    }
    if (checks.findPhoneProblem(details.phone) !== null) {
      phoneInput.current?.focus()
      return false
    }
    return true
  }

  function reset(next: AttendeeDetails) {
    setDetails(next)
    setIsChecked(false)
  }

  return {
    details,
    setDetails,
    // Worked out from what is typed now, so they follow every keystroke once a save was tried.
    nameProblem: isChecked ? checks.findNameProblem(details.full_name) : null,
    phoneProblem: isChecked ? checks.findPhoneProblem(details.phone) : null,
    nameInput,
    phoneInput,
    canSend,
    reset,
  }
}
