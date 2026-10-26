import { useId, type RefObject } from 'react'
import {
  DIETARY_REQUIREMENTS_MAX_LENGTH,
  FULL_NAME_MAX_LENGTH,
  type AttendeeDetails,
} from '../api/registrations'
import { RequiredMark } from '../components/RequiredMark'
import { PHONE_MAX_LENGTH } from '../shared/phone'

interface AttendeeDetailsFieldsProps {
  details: AttendeeDetails
  onChange: (details: AttendeeDetails) => void
  /** Why the name cannot be saved, once a save was tried; null when it can. */
  nameProblem: string | null
  /** Why the phone number cannot be saved, once a save was tried; null when it can. */
  phoneProblem: string | null
  /** Where focus goes when a save is stopped by the name. */
  nameInput: RefObject<HTMLInputElement | null>
  /** Where focus goes when a save is stopped by the phone number. */
  phoneInput: RefObject<HTMLInputElement | null>
}

/**
 * Story 18.4 - the attendee's name, phone number and dietary requirements, on My profile and in
 * the registration dialog alike. Each field has its label above it and spans the form (App.css
 * `label > input`). AC1/AC7 (as changed, 25 Oct 2026): the name and phone number are required,
 * marked * (story 2.1's mark) and `aria-required`. A missing or wrong value is announced
 * (`role="alert"`) and tied to its field (`aria-describedby`); each field is named by its label's
 * words alone (`aria-labelledby`), so a problem is read once, as the field's description, not as
 * part of its name. The phone field brings up a phone keypad. AC6: dietary requirements stop at
 * 500 characters; left blank they are recorded as "None".
 */
export function AttendeeDetailsFields({
  details,
  onChange,
  nameProblem,
  phoneProblem,
  nameInput,
  phoneInput,
}: AttendeeDetailsFieldsProps) {
  const ids = useId()
  const nameLabelId = `${ids}-name-label`
  const nameProblemId = `${ids}-name-problem`
  const phoneLabelId = `${ids}-phone-label`
  const phoneProblemId = `${ids}-phone-problem`
  return (
    <>
      <p className="small muted">
        Fields marked <RequiredMark /> are required. Leave dietary requirements blank if you have
        none.
      </p>
      <label>
        <span id={nameLabelId}>Name</span> <RequiredMark />
        <input
          ref={nameInput}
          aria-labelledby={nameLabelId}
          type="text"
          autoComplete="name"
          required
          aria-required="true"
          maxLength={FULL_NAME_MAX_LENGTH}
          value={details.full_name}
          aria-invalid={nameProblem !== null ? true : undefined}
          aria-describedby={nameProblem !== null ? nameProblemId : undefined}
          onChange={(e) => onChange({ ...details, full_name: e.target.value })}
        />
        {nameProblem !== null && (
          <span id={nameProblemId} role="alert" className="field-error">
            {nameProblem}
          </span>
        )}
      </label>
      <label>
        <span id={phoneLabelId}>Phone number</span> <RequiredMark />
        <input
          ref={phoneInput}
          aria-labelledby={phoneLabelId}
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          required
          aria-required="true"
          maxLength={PHONE_MAX_LENGTH}
          value={details.phone}
          aria-invalid={phoneProblem !== null ? true : undefined}
          aria-describedby={phoneProblem !== null ? phoneProblemId : undefined}
          onChange={(e) => onChange({ ...details, phone: e.target.value })}
        />
        {phoneProblem !== null && (
          <span id={phoneProblemId} role="alert" className="field-error">
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
