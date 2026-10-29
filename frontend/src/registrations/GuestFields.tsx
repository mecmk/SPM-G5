import { useId } from 'react'
import { DIETARY_REQUIREMENTS_MAX_LENGTH, FULL_NAME_MAX_LENGTH } from '../api/registrations'
import { RequiredMark } from '../components/RequiredMark'
import { PHONE_MAX_LENGTH } from '../shared/phone'
import type { AttendeeDetailsForm } from './useAttendeeDetailsForm'

interface GuestFieldsProps {
  /** The guest's form: their details, their problems and where focus goes. */
  form: AttendeeDetailsForm
  /** A registration is on its way, so the guest is not to be taken off meanwhile. */
  isBusy: boolean
  onRemove: () => void
}

/**
 * Story 18.4 AC12 (fix f18.4.1) - the one guest an attendee brings, below their own details in
 * "Confirm your details": the guest's name and phone number, required and marked *, and their
 * dietary requirements. The attendee types them in, so nothing is filled in, nor offered by the
 * browser's autofill, which would give the attendee's own. As on the attendee's own fields
 * (AttendeeDetailsFields), a problem is announced and tied to its field, and each field is named
 * by its label's words alone. Remove guest takes the guest off before confirming.
 */
export function GuestFields({ form, isBusy, onRemove }: GuestFieldsProps) {
  const { details, setDetails, nameProblem, phoneProblem, nameInput, phoneInput } = form
  const ids = useId()
  const nameLabelId = `${ids}-name-label`
  const nameProblemId = `${ids}-name-problem`
  const phoneLabelId = `${ids}-phone-label`
  const phoneProblemId = `${ids}-phone-problem`
  return (
    <fieldset className="guest-fields">
      <legend>Your guest</legend>
      <label>
        <span id={nameLabelId}>Guest&apos;s name</span> <RequiredMark />
        <input
          ref={nameInput}
          aria-labelledby={nameLabelId}
          type="text"
          autoComplete="off"
          required
          aria-required="true"
          maxLength={FULL_NAME_MAX_LENGTH}
          value={details.full_name}
          aria-invalid={nameProblem !== null ? true : undefined}
          aria-describedby={nameProblem !== null ? nameProblemId : undefined}
          onChange={(e) => setDetails({ ...details, full_name: e.target.value })}
        />
        {nameProblem !== null && (
          <span id={nameProblemId} role="alert" className="field-error">
            {nameProblem}
          </span>
        )}
      </label>
      <label>
        <span id={phoneLabelId}>Guest&apos;s phone number</span> <RequiredMark />
        <input
          ref={phoneInput}
          aria-labelledby={phoneLabelId}
          type="tel"
          inputMode="tel"
          autoComplete="off"
          required
          aria-required="true"
          maxLength={PHONE_MAX_LENGTH}
          value={details.phone}
          aria-invalid={phoneProblem !== null ? true : undefined}
          aria-describedby={phoneProblem !== null ? phoneProblemId : undefined}
          onChange={(e) => setDetails({ ...details, phone: e.target.value })}
        />
        {phoneProblem !== null && (
          <span id={phoneProblemId} role="alert" className="field-error">
            {phoneProblem}
          </span>
        )}
      </label>
      <label>
        Guest&apos;s dietary requirements
        <textarea
          rows={2}
          maxLength={DIETARY_REQUIREMENTS_MAX_LENGTH}
          value={details.dietary_requirements}
          onChange={(e) => setDetails({ ...details, dietary_requirements: e.target.value })}
        />
      </label>
      <div className="guest-fields-actions">
        <button type="button" className="secondary" disabled={isBusy} onClick={onRemove}>
          Remove guest
        </button>
      </div>
    </fieldset>
  )
}
