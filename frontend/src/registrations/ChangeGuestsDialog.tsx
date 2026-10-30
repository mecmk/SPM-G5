import type { GuestInput, MyRegistration } from '../api/registrations'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { GuestFields } from './GuestFields'
import { guestInputsFrom, useGuestsForm } from './useGuestsForm'

interface ChangeGuestsDialogProps {
  /** The registration whose guests are changed. */
  registration: MyRegistration
  isBusy: boolean
  /** Why the guests were not saved, shown in the dialog so nothing typed is lost. */
  error: string | null
  onSave: (guests: GuestInput[]) => void
  onCancel: () => void
}

/**
 * Story 18.5 AC3 - "Change your guests", opened from a registration on My registrations: the
 * guests registered with it, filled in, to add to, rename or remove. Saving replaces them all;
 * nothing changes until then. AC7: a guest with no name stops the save before anything is sent.
 * AC12: no more guests than there are places for, as the server works it out (`max_guests`).
 * Save guests is disabled while the save is on its way, so a double-click sends one.
 */
export function ChangeGuestsDialog({
  registration,
  isBusy,
  error,
  onSave,
  onCancel,
}: ChangeGuestsDialogProps) {
  const form = useGuestsForm(guestInputsFrom(registration.guests), registration.max_guests)

  function handleSave() {
    if (form.canSend()) onSave(form.guests)
  }

  return (
    <ConfirmDialog
      title="Change your guests"
      confirmLabel="Save guests"
      tone="primary"
      isBusy={isBusy}
      error={error}
      onConfirm={handleSave}
      onCancel={onCancel}
      className="attendee-details-dialog"
    >
      <p>
        {`Add, rename or remove the guests coming with you to ${registration.event_name}. Removing every guest keeps your own place.`}
      </p>
      <GuestFields form={form} />
    </ConfirmDialog>
  )
}
