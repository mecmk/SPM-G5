import { useRef, useState, type RefObject } from 'react'
import { MAX_GUESTS, type Guest, type GuestInput } from '../api/registrations'
import { ERROR_REGISTRY } from '../errors/registry'

/** Story 18.5: the guests as a form holds them - those registered, or none. */
export function guestInputsFrom(guests: Guest[]): GuestInput[] {
  return guests.map((guest) => ({
    full_name: guest.full_name,
    dietary_requirements: guest.dietary_requirements ?? '',
  }))
}

/** Story 18.5 AC6: what is wrong with a guest's typed name, as a registry message, or null. */
export function findGuestNameProblem(name: string): string | null {
  return name.trim() === '' ? ERROR_REGISTRY.GUEST_NAME_REQUIRED.message : null
}

/** What a form of the attendee's guests holds, for the details dialog and Change guests alike. */
export interface GuestsForm {
  guests: GuestInput[]
  /** Story 18.5 AC2/AC3/AC6: false once the form holds as many guests as are allowed. */
  canAdd: boolean
  /** Story 18.5 AC2/AC3: the places left, not the 10-guest limit, are what stop more guests. */
  isLimitedByPlaces: boolean
  add: () => void
  remove: (index: number) => void
  change: (index: number, guest: GuestInput) => void
  /** Why each guest's name cannot be sent, once sending was tried; null where it can. */
  nameProblems: (string | null)[]
  /** Each guest's name field, in order, so the first with a problem can be focused. */
  nameInputs: RefObject<(HTMLInputElement | null)[]>
  /** Story 18.5 AC6: whether the guests may be sent. When they may not, every problem is shown and
   *  the first name with one is focused, before anything is sent. */
  canSend: () => boolean
}

/** Story 18.5: the state of a form of the attendee's guests, holding at most `maxGuests` of them -
 *  MAX_GUESTS (AC6), or fewer when there are not the places for them (AC2/AC3). */
export function useGuestsForm(initial: GuestInput[], maxGuests: number): GuestsForm {
  const nameInputs = useRef<(HTMLInputElement | null)[]>([])
  const [guests, setGuests] = useState(initial)
  const [isChecked, setIsChecked] = useState(false)

  function add() {
    setGuests((current) =>
      current.length >= maxGuests
        ? current
        : [...current, { full_name: '', dietary_requirements: '' }],
    )
  }

  function remove(index: number) {
    setGuests((current) => current.filter((_, n) => n !== index))
  }

  function change(index: number, guest: GuestInput) {
    setGuests((current) => current.map((each, n) => (n === index ? guest : each)))
  }

  function canSend(): boolean {
    setIsChecked(true)
    const first = guests.findIndex((guest) => findGuestNameProblem(guest.full_name) !== null)
    if (first === -1) return true
    nameInputs.current[first]?.focus()
    return false
  }

  return {
    guests,
    canAdd: guests.length < maxGuests,
    isLimitedByPlaces: maxGuests < MAX_GUESTS,
    add,
    remove,
    change,
    // Worked out from what is typed now, so they follow every keystroke once sending was tried.
    nameProblems: guests.map((guest) => (isChecked ? findGuestNameProblem(guest.full_name) : null)),
    nameInputs,
    canSend,
  }
}
