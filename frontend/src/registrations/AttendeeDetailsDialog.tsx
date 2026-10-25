import type { AttendeeDetails } from '../api/registrations'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { AttendeeDetailsFields } from './AttendeeDetailsFields'
import { useAttendeeDetailsForm } from './useAttendeeDetailsForm'

interface AttendeeDetailsDialogProps {
  /** What the fields start with: the saved details, or blank before the first registration. */
  initial: AttendeeDetails
  /** The event being registered for (AC2), or null when only the details change (AC3). */
  eventName: string | null
  isBusy: boolean
  /** Why the registration or the save was refused, shown in the dialog so nothing typed is lost. */
  error: string | null
  onConfirm: (details: AttendeeDetails) => void
  onCancel: () => void
}

/**
 * Story 18.4 - the attendee's details, asked for on Upcoming events. AC2: before their first
 * registration, confirming registers with them; nothing is registered until then. AC3: from "Change
 * details", confirming saves them. AC7: a wrong phone number stops the confirm before anything is
 * sent, announced and tied to its field. On a phone the dialog fits the screen and its buttons are
 * at least 44px tall (App.css `.attendee-details-dialog`).
 */
export function AttendeeDetailsDialog({
  initial,
  eventName,
  isBusy,
  error,
  onConfirm,
  onCancel,
}: AttendeeDetailsDialogProps) {
  const form = useAttendeeDetailsForm(initial)

  function handleConfirm() {
    if (form.canSend()) onConfirm(form.details)
  }

  return (
    <ConfirmDialog
      title="Your details"
      confirmLabel={eventName === null ? 'Save details' : 'Register'}
      tone="primary"
      isBusy={isBusy}
      error={error}
      onConfirm={handleConfirm}
      onCancel={onCancel}
      className="attendee-details-dialog"
    >
      {eventName !== null && (
        <p>
          Before you register for {eventName}, give the phone number and dietary requirements the
          organiser should have. They are saved to My profile, so you will not be asked again.
        </p>
      )}
      <AttendeeDetailsFields
        details={form.details}
        onChange={form.setDetails}
        phoneProblem={form.phoneProblem}
        phoneInput={form.phoneInput}
      />
    </ConfirmDialog>
  )
}
