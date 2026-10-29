import { useId } from 'react'
import { DIETARY_REQUIREMENTS_MAX_LENGTH, FULL_NAME_MAX_LENGTH } from '../api/registrations'
import { RequiredMark } from '../components/RequiredMark'
import { ERROR_REGISTRY } from '../errors/registry'
import type { GuestsForm } from './useGuestsForm'

interface GuestFieldsProps {
  /** The form the fields show and change: its guests, their problems and where focus goes. */
  form: GuestsForm
}

/**
 * Story 18.5 - the guests an attendee brings, in the registration dialog and in Change guests
 * alike: a "Guests" group holding one "Guest n" group per guest, each with its name and dietary
 * requirements and nothing else (AC7), and a button to remove them. AC6: "Add a guest" is
 * disabled once there are ten, and the form says why. AC7: a guest's name is required, marked *
 * and announced when missing, tied to its field as the attendee's own are (18.4); their dietary
 * requirements stop at 500 characters, and left blank are recorded as "None".
 */
export function GuestFields({ form }: GuestFieldsProps) {
  const { guests, canAdd, add, remove, change, nameProblems, nameInputs } = form
  const ids = useId()
  return (
    <fieldset className="guest-fields stack">
      <legend>Guests</legend>
      <p className="small muted">
        Each guest takes a place at the event. Leave a guest&apos;s dietary requirements blank if
        they have none.
      </p>
      {guests.map((guest, index) => {
        const number = index + 1
        const labelId = `${ids}-guest-${number}-name-label`
        const problemId = `${ids}-guest-${number}-name-problem`
        const problem = nameProblems[index]
        return (
          <fieldset key={index} className="guest-entry stack">
            <legend>Guest {number}</legend>
            <label>
              <span id={labelId}>Guest&apos;s name</span> <RequiredMark />
              <input
                ref={(input) => {
                  nameInputs.current[index] = input
                }}
                aria-labelledby={labelId}
                type="text"
                required
                aria-required="true"
                maxLength={FULL_NAME_MAX_LENGTH}
                value={guest.full_name}
                aria-invalid={problem !== null ? true : undefined}
                aria-describedby={problem !== null ? problemId : undefined}
                onChange={(e) => change(index, { ...guest, full_name: e.target.value })}
              />
              {problem !== null && (
                <span id={problemId} role="alert" className="field-error">
                  {problem}
                </span>
              )}
            </label>
            <label>
              Guest&apos;s dietary requirements
              <textarea
                rows={2}
                maxLength={DIETARY_REQUIREMENTS_MAX_LENGTH}
                value={guest.dietary_requirements}
                onChange={(e) => change(index, { ...guest, dietary_requirements: e.target.value })}
              />
            </label>
            <button
              type="button"
              className="button-sm secondary"
              aria-label={`Remove guest ${number}`}
              onClick={() => remove(index)}
            >
              Remove
            </button>
          </fieldset>
        )
      })}
      {!canAdd && <p className="small muted">{ERROR_REGISTRY.GUESTS_TOO_MANY.message}</p>}
      <button type="button" className="button-sm secondary" disabled={!canAdd} onClick={add}>
        Add a guest
      </button>
    </fieldset>
  )
}
