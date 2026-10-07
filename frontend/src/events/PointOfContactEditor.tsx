import { useId, useRef, useState, type FormEvent } from 'react'
import { formatApiError } from '../api/client'
import { updatePointOfContact, type EventDetail, type PointOfContactInput } from '../api/events'
import { ERROR_REGISTRY } from '../errors/registry'
import {
  CONTACT_EMAIL_MAX_LENGTH,
  CONTACT_PHONE_MAX_LENGTH,
  isBlankOrEmailAddress,
  isBlankOrPhoneNumber,
} from './eventRequestForm'

export interface PointOfContactEditorProps {
  event: EventDetail
  /** Receives the event as saved, so the page shows the new details at once. */
  onSaved: (event: EventDetail) => void
}

/** What is wrong with the typed email, as a registry message, or null. A submitted event keeps
 *  its point of contact, so an empty one is wrong too. */
function findEmailProblem(email: string): string | null {
  if (email.trim() === '' || !isBlankOrEmailAddress(email)) {
    return ERROR_REGISTRY.EVENT_CONTACT_EMAIL_INVALID.message
  }
  return null
}

/** What is wrong with the typed phone number, as a registry message, or null. */
function findPhoneProblem(phone: string): string | null {
  if (phone.trim() === '' || !isBlankOrPhoneNumber(phone)) {
    return ERROR_REGISTRY.EVENT_CONTACT_PHONE_INVALID.message
  }
  return null
}

/**
 * Story 19.1 AC2: the organiser updates the point of contact of their approved event directly,
 * from the event page, with no change request. Checked here by story 2.1 AC13's rules before
 * anything is sent (AC4); the server re-checks and logs the old and new values. Once Save has been
 * pressed, each field is re-checked as it is typed in, so a problem clears as soon as it is fixed.
 */
export function PointOfContactEditor({ event, onSaved }: PointOfContactEditorProps) {
  const ids = useId()
  const emailInput = useRef<HTMLInputElement>(null)
  const phoneInput = useRef<HTMLInputElement>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [isChecked, setIsChecked] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  function startEditing() {
    setEmail(event.contact_email ?? '')
    setPhone(event.contact_phone ?? '')
    setIsChecked(false)
    setSaveError(null)
    setIsEditing(true)
  }

  function stopEditing() {
    setIsEditing(false)
  }

  // Worked out from what is typed now, so they follow every keystroke once Save was pressed.
  const emailProblem = isChecked ? findEmailProblem(email) : null
  const phoneProblem = isChecked ? findPhoneProblem(phone) : null

  async function handleSave(submitted: FormEvent<HTMLFormElement>) {
    submitted.preventDefault()
    setIsChecked(true)
    if (findEmailProblem(email) !== null) {
      emailInput.current?.focus()
      return
    }
    if (findPhoneProblem(phone) !== null) {
      phoneInput.current?.focus()
      return
    }
    // Only what changed travels, so an unchanged field is never re-judged.
    const input: PointOfContactInput = {}
    if (email.trim() !== event.contact_email) input.contact_email = email.trim()
    if (phone.trim() !== event.contact_phone) input.contact_phone = phone.trim()
    setIsSaving(true)
    setSaveError(null)
    try {
      const saved = await updatePointOfContact(event.id, input)
      setIsEditing(false)
      onSaved(saved)
    } catch (err) {
      setSaveError(formatApiError(err))
    } finally {
      setIsSaving(false)
    }
  }

  if (!isEditing) {
    return (
      <div className="page-actions">
        <button type="button" className="secondary" onClick={startEditing}>
          Update point of contact
        </button>
      </div>
    )
  }

  return (
    <form className="stack" aria-label="Update point of contact" noValidate onSubmit={handleSave}>
      <div className="form-grid">
        <label>
          Contact email
          <input
            ref={emailInput}
            type="email"
            inputMode="email"
            autoComplete="email"
            maxLength={CONTACT_EMAIL_MAX_LENGTH}
            value={email}
            aria-invalid={emailProblem !== null ? true : undefined}
            aria-describedby={emailProblem !== null ? `${ids}-email-problem` : undefined}
            onChange={(e) => setEmail(e.target.value)}
          />
          {emailProblem !== null && (
            <span id={`${ids}-email-problem`} className="field-error">
              {emailProblem}
            </span>
          )}
        </label>
        <label>
          Contact phone number
          <input
            ref={phoneInput}
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            maxLength={CONTACT_PHONE_MAX_LENGTH}
            value={phone}
            aria-invalid={phoneProblem !== null ? true : undefined}
            aria-describedby={phoneProblem !== null ? `${ids}-phone-problem` : undefined}
            onChange={(e) => setPhone(e.target.value)}
          />
          {phoneProblem !== null && (
            <span id={`${ids}-phone-problem`} className="field-error">
              {phoneProblem}
            </span>
          )}
        </label>
      </div>
      {saveError && (
        <p role="alert" className="error">
          {saveError}
        </p>
      )}
      <div className="page-actions">
        <button type="submit" disabled={isSaving}>
          {isSaving ? 'Saving…' : 'Save contact details'}
        </button>
        <button type="button" className="secondary" disabled={isSaving} onClick={stopEditing}>
          Cancel
        </button>
      </div>
    </form>
  )
}
