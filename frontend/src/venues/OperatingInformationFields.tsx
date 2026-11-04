import { useId } from 'react'
import { RequiredMark } from '../components/RequiredMark'
import { ERROR_REGISTRY } from '../errors/registry'
import { refuseNonDigits } from '../shared/inputGuards'
import {
  digitsOnly,
  MINUTES_MAX_DIGITS,
  type OperatingField,
  type OperatingProblems,
  type VenueFormState,
} from './venueForm'

interface OperatingInformationFieldsProps {
  form: VenueFormState
  /** The problems to show now, one per field; null where a field has none, or none to show yet. */
  problems: OperatingProblems
  onChange: (field: OperatingField | 'operatingNotes', value: string) => void
  onLeave: (field: OperatingField) => void
}

/**
 * Story 8.3 AC13-AC15 (fix f8.3.4): the venue form's Operating information card. Opens, Closes,
 * Setup and Teardown are required and each names its own problem beneath it; the closing time
 * cannot be picked before the opening time, and the minutes boxes keep digits only, five at most.
 */
export function OperatingInformationFields({
  form,
  problems,
  onChange,
  onLeave,
}: OperatingInformationFieldsProps) {
  const ids = useId()
  const problemId = (field: OperatingField) => `${ids}-${field}-problem`

  /** The attributes and message that tie `field` to its problem, when it has one to show. */
  function problemOf(field: OperatingField) {
    const code = problems[field]
    return {
      inputProps: {
        'aria-invalid': code ? true : undefined,
        'aria-describedby': code ? problemId(field) : undefined,
        onBlur: () => onLeave(field),
      },
      message: code && (
        <span id={problemId(field)} role="alert" className="field-error">
          {ERROR_REGISTRY[code].message}
        </span>
      ),
    }
  }

  const opens = problemOf('opensAt')
  const closes = problemOf('closesAt')
  const setup = problemOf('setupMinutes')
  const teardown = problemOf('teardownMinutes')

  return (
    <fieldset className="card">
      <legend>Operating information</legend>
      <div className="form-grid form-grid-4">
        <label>
          Opens <RequiredMark />
          <input
            type="time"
            required
            value={form.opensAt}
            onChange={(e) => onChange('opensAt', e.target.value)}
            {...opens.inputProps}
          />
          {opens.message}
        </label>
        <label>
          Closes <RequiredMark />
          <input
            type="time"
            required
            min={form.opensAt || undefined}
            value={form.closesAt}
            onChange={(e) => onChange('closesAt', e.target.value)}
            {...closes.inputProps}
          />
          {closes.message}
        </label>
        <label>
          Setup (minutes) <RequiredMark />
          <input
            onBeforeInput={refuseNonDigits}
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={MINUTES_MAX_DIGITS}
            required
            value={form.setupMinutes}
            onChange={(e) => onChange('setupMinutes', digitsOnly(e.target.value))}
            {...setup.inputProps}
          />
          {setup.message}
        </label>
        <label>
          Teardown (minutes) <RequiredMark />
          <input
            onBeforeInput={refuseNonDigits}
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={MINUTES_MAX_DIGITS}
            required
            value={form.teardownMinutes}
            onChange={(e) => onChange('teardownMinutes', digitsOnly(e.target.value))}
            {...teardown.inputProps}
          />
          {teardown.message}
        </label>
        <label className="span-all">
          Operating notes
          <textarea
            rows={2}
            placeholder="For example, closed on public holidays"
            value={form.operatingNotes}
            onChange={(e) => onChange('operatingNotes', e.target.value)}
          />
        </label>
      </div>
    </fieldset>
  )
}
