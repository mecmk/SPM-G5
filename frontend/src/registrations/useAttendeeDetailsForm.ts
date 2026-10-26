import { useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react'
import type { AttendeeDetails } from '../api/registrations'
import { findNameProblem, findPhoneProblem } from './attendeeDetails'

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

/** Story 18.4: the state of a form of the attendee's details. */
export function useAttendeeDetailsForm(initial: AttendeeDetails): AttendeeDetailsForm {
  const nameInput = useRef<HTMLInputElement>(null)
  const phoneInput = useRef<HTMLInputElement>(null)
  const [details, setDetails] = useState(initial)
  const [isChecked, setIsChecked] = useState(false)

  function canSend(): boolean {
    setIsChecked(true)
    if (findNameProblem(details.full_name) !== null) {
      nameInput.current?.focus()
      return false
    }
    if (findPhoneProblem(details.phone) !== null) {
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
    nameProblem: isChecked ? findNameProblem(details.full_name) : null,
    phoneProblem: isChecked ? findPhoneProblem(details.phone) : null,
    nameInput,
    phoneInput,
    canSend,
    reset,
  }
}
