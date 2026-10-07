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

/** The first problem with the typed details, as a registry message, or null. */
function findContactProblem(email: string, phone: string): string | null {
  if (email.trim() === '' || phone.trim() === '') {
    return ERROR_REGISTRY.EVENT_CONTACT_REQUIRED.message
  }
  if (!isBlankOrEmailAddress(email)) return ERROR_REGISTRY.EVENT_CONTACT_EMAIL_INVALID.message
  if (!isBlankOrPhoneNumber(phone)) return ERROR_REGISTRY.EVENT_CONTACT_PHONE_INVALID.message
  return null
}

/**
 * Story 19.1 AC2: the organiser updates the point of contact of their approved event directly,
 * from the event page, with no change request. Checked here by story 2.1 AC13's rules before
 * anything is sent (AC4); the server re-checks and logs the old and new values.
 */
export function PointOfContactEditor({ event, onSaved }: PointOfContactEditorProps) {
  const ids = useId()
  const emailInput = useRef<HTMLInputElement>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  function startEditing() {
    setEmail(event.contact_email ?? '')
    setPhone(event.contact_phone ?? '')
    setProblem(null)
    setSaveError(null)
    setIsEditing(true)
  }

  function stopEditing() {
    setIsEditing(false)
  }

  async function handleSave(submitted: FormEvent<HTMLFormElement>) {
    submitted.preventDefault()
    const found = findContactProblem(email, phone)
    setProblem(found)
    if (found !== null) {
      emailInput.current?.focus()
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
            aria-invalid={problem !== null ? true : undefined}
            aria-describedby={problem !== null ? `${ids}-problem` : undefined}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Contact phone number
          <input
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            maxLength={CONTACT_PHONE_MAX_LENGTH}
            value={phone}
            aria-invalid={problem !== null ? true : undefined}
            aria-describedby={problem !== null ? `${ids}-problem` : undefined}
            onChange={(e) => setPhone(e.target.value)}
          />
        </label>
      </div>
      {problem !== null && (
        <span id={`${ids}-problem`} className="field-error">
          {problem}
        </span>
      )}
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
