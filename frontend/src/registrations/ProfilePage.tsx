import { useState, type FormEvent } from 'react'
import { formatApiError } from '../api/client'
import { fetchProfile, updateProfile, type Profile } from '../api/registrations'
import { useAuth } from '../auth/authContext'
import { PageHeader } from '../components/PageHeader'
import { LoadingState } from '../layout/LoadingState'
import { useLoaded } from '../shared/useLoaded'
import { AttendeeDetailsFields } from './AttendeeDetailsFields'
import { detailsFrom } from './attendeeDetails'
import { useAttendeeDetailsForm } from './useAttendeeDetailsForm'

interface ProfileFormProps {
  profile: Profile
  onSaved: (profile: Profile) => void
}

/**
 * Story 18.4 AC1: the email as fixed text - ConnectSphere sets up attendees' accounts (AC8), so it
 * is not offered to change - and the name and details in a form (AC1 as changed, 25 Oct 2026: the
 * name is the attendee's to change). AC4: saving changes them everywhere they are shown - the
 * frame's own name among them, at once. AC1/AC7: a missing name, or a missing or wrong phone
 * number, stops the save before anything is sent. AC11: each save sends the whole form, so the
 * later of two saves wins.
 */
function ProfileForm({ profile, onSaved }: ProfileFormProps) {
  const { setFullName } = useAuth()
  const form = useAttendeeDetailsForm(detailsFrom(profile))
  const [saveError, setSaveError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  async function handleSave(submitted: FormEvent<HTMLFormElement>) {
    submitted.preventDefault()
    if (!form.canSend()) return
    setIsSaving(true)
    setSaveError(null)
    try {
      const saved = await updateProfile(form.details)
      form.reset(detailsFrom(saved))
      setFullName(saved.full_name)
      onSaved(saved)
    } catch (err) {
      setSaveError(formatApiError(err))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <section className="card stack profile-card">
      <dl className="attendee-details-list">
        <div>
          <dt>Email</dt>
          <dd>{profile.email}</dd>
        </div>
      </dl>
      <p className="small muted">Your email is set by ConnectSphere and cannot be changed here.</p>
      <form className="stack" aria-label="Your details" noValidate onSubmit={handleSave}>
        <AttendeeDetailsFields
          details={form.details}
          onChange={form.setDetails}
          nameProblem={form.nameProblem}
          phoneProblem={form.phoneProblem}
          nameInput={form.nameInput}
          phoneInput={form.phoneInput}
        />
        {saveError && (
          <p role="alert" className="error">
            {saveError}
          </p>
        )}
        <div className="page-actions">
          <button type="submit" disabled={isSaving}>
            {isSaving ? 'Saving…' : 'Save details'}
          </button>
        </div>
      </form>
    </section>
  )
}

/**
 * Story 18.4 - My profile: the attendee's email, and the name, phone number and dietary
 * requirements filled in for them whenever they register (AC1, AC3). Attendees only: App.tsx
 * guards the route, and the backend refuses everyone else (AC10).
 */
export function ProfilePage() {
  const { data: profile, error, isLoading, setData: setProfile } = useLoaded(fetchProfile)

  return (
    <div className="page profile-page">
      <p className="eyebrow">Attend</p>
      <PageHeader
        title="My profile"
        subtitle="Your details, filled in for you whenever you register for an event."
      />
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {isLoading && <LoadingState label="Loading your profile…" />}
      {profile !== null && <ProfileForm profile={profile} onSaved={setProfile} />}
    </div>
  )
}
