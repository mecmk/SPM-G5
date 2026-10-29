import type { AttendeeDetails, GuestInput } from '../api/registrations'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { AttendeeDetailsFields } from './AttendeeDetailsFields'
import { GuestFields } from './GuestFields'
import { useAttendeeDetailsForm } from './useAttendeeDetailsForm'
import { useGuestsForm } from './useGuestsForm'

interface AttendeeDetailsDialogProps {
  /** What the fields start with: the details on the attendee's profile, or blank before their
   *  first registration (the name aside, which their account already has). */
  initial: AttendeeDetails
  /** The event being registered for. */
  eventName: string
  /** The attendee has never given their details, so they are asked for, not confirmed (AC2). */
  isFirstTime: boolean
  isBusy: boolean
  /** Why the details were refused, shown in the dialog so nothing typed is lost. */
  error: string | null
  onConfirm: (details: AttendeeDetails, guests: GuestInput[]) => void
  onCancel: () => void
}

/**
 * Story 18.4 - "Confirm your details", opened by every Register on Upcoming events; confirming
 * registers, and nothing is registered until then. AC2: the first time, the details are asked for.
 * AC3: after that they are filled in from the attendee's profile, to check before registering
 * (CL-167); a change made here is saved to My profile with the registration.
 * AC1/AC7: a missing name, or a missing or wrong phone number, stops the confirm before anything
 * is sent, announced and tied to its field. 18.1 AC6: Confirm and register is disabled while the
 * registration is on its way, so a double-click sends one. On a phone the dialog fits the screen
 * and its buttons are at least 44px tall (App.css `.attendee-details-dialog`).
 * Story 18.5 AC1: the guests the attendee brings are added here and registered with them, as one
 * group; AC7: a guest with no name stops the confirm too, before anything is sent.
 */
export function AttendeeDetailsDialog({
  initial,
  eventName,
  isFirstTime,
  isBusy,
  error,
  onConfirm,
  onCancel,
}: AttendeeDetailsDialogProps) {
  const form = useAttendeeDetailsForm(initial)
  const guestsForm = useGuestsForm([])

  function handleConfirm() {
    // The attendee's own details first, so focus goes to the first problem in the dialog.
    if (form.canSend() && guestsForm.canSend()) onConfirm(form.details, guestsForm.guests)
  }

  return (
    <ConfirmDialog
      title="Confirm your details"
      confirmLabel="Confirm and register"
      tone="primary"
      isBusy={isBusy}
      error={error}
      onConfirm={handleConfirm}
      onCancel={onCancel}
      className="attendee-details-dialog"
    >
      <p>
        {isFirstTime
          ? `Before you register for ${eventName}, give the name, phone number and dietary requirements the organiser should have. They are saved to My profile and filled in next time.`
          : `Check your details before you register for ${eventName}. Any change you make is saved to My profile.`}
      </p>
      <AttendeeDetailsFields form={form} />
      <GuestFields form={guestsForm} />
    </ConfirmDialog>
  )
}
