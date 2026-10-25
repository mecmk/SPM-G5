import { useId, type RefObject } from 'react'
import { DIETARY_REQUIREMENTS_MAX_LENGTH, type AttendeeDetails } from '../api/registrations'
import { PHONE_MAX_LENGTH } from '../shared/phone'

interface AttendeeDetailsFieldsProps {
  details: AttendeeDetails
  onChange: (details: AttendeeDetails) => void
  /** Why the phone number cannot be saved, once a save was tried; null when it can. */
  phoneProblem: string | null
  /** Where focus goes when a save is stopped by the phone number. */
  phoneInput: RefObject<HTMLInputElement | null>
}

/**
 * Story 18.4 - the phone number and dietary requirements, on My profile and in the registration
 * dialog alike. Each field has its label above it and spans the form (App.css `label > input`).
 * AC7: the phone field brings up a phone keypad, and a wrong number is announced (`role="alert"`)
 * and tied to its field (`aria-describedby`). AC6: dietary requirements stop at 500 characters;
 * left blank they are recorded as "None".
 */
export function AttendeeDetailsFields({
  details,
  onChange,
  phoneProblem,
  phoneInput,
}: AttendeeDetailsFieldsProps) {
  const problemId = useId()
  return (
    <>
      <p className="small muted">
        Both are optional. Leave dietary requirements blank if you have none.
      </p>
      <label>
        Phone number
        <input
          ref={phoneInput}
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          maxLength={PHONE_MAX_LENGTH}
          value={details.phone}
          aria-invalid={phoneProblem !== null ? true : undefined}
          aria-describedby={phoneProblem !== null ? problemId : undefined}
          onChange={(e) => onChange({ ...details, phone: e.target.value })}
        />
        {phoneProblem !== null && (
          <span id={problemId} role="alert" className="field-error">
            {phoneProblem}
          </span>
        )}
      </label>
      <label>
        Dietary requirements
        <textarea
          rows={3}
          maxLength={DIETARY_REQUIREMENTS_MAX_LENGTH}
          value={details.dietary_requirements}
          onChange={(e) => onChange({ ...details, dietary_requirements: e.target.value })}
        />
      </label>
    </>
  )
}
