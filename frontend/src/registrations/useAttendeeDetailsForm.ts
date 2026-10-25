import { useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react'
import type { AttendeeDetails } from '../api/registrations'
import { findPhoneProblem } from './attendeeDetails'

/** What a form of the attendee's details holds, for My profile and the details dialog alike. */
export interface AttendeeDetailsForm {
  details: AttendeeDetails
  setDetails: Dispatch<SetStateAction<AttendeeDetails>>
  /** Why the phone number cannot be saved, once a save was tried; null when it can. */
  phoneProblem: string | null
  phoneInput: RefObject<HTMLInputElement | null>
  /** Story 18.4 AC7: whether the details may be sent. When they may not, the phone field is
   *  focused and its problem shown, before anything is sent. */
  canSend: () => boolean
  /** Start again from `details`, with no problem shown: after a save. */
  reset: (details: AttendeeDetails) => void
}

/** Story 18.4: the state of a form of the attendee's details. */
export function useAttendeeDetailsForm(initial: AttendeeDetails): AttendeeDetailsForm {
  const phoneInput = useRef<HTMLInputElement>(null)
  const [details, setDetails] = useState(initial)
  const [isChecked, setIsChecked] = useState(false)

  function canSend(): boolean {
    setIsChecked(true)
    if (findPhoneProblem(details.phone) === null) return true
    phoneInput.current?.focus()
    return false
  }

  function reset(next: AttendeeDetails) {
    setDetails(next)
    setIsChecked(false)
  }

  return {
    details,
    setDetails,
    // Worked out from what is typed now, so it follows every keystroke once a save was tried.
    phoneProblem: isChecked ? findPhoneProblem(details.phone) : null,
    phoneInput,
    canSend,
    reset,
  }
}
