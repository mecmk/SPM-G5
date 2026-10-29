import { useEffect, useId, useRef, useState } from 'react'
import type { AttendeeDetails, GuestDetails } from '../api/registrations'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { AttendeeDetailsFields } from './AttendeeDetailsFields'
import { GUEST_CHECKS, NO_GUEST } from './attendeeDetails'
import { GuestFields } from './GuestFields'
import { NO_ROOM_FOR_GUEST_NOTE, PLACES_WITH_GUEST } from './registrationLabels'
import { useAttendeeDetailsForm } from './useAttendeeDetailsForm'

interface AttendeeDetailsDialogProps {
  /** What the fields start with: the details on the attendee's profile, or blank before their
   *  first registration (the name aside, which their account already has). */
  initial: AttendeeDetails
  /** The event being registered for. */
  eventName: string
  /** The places the event has left, as the page last loaded it: a guest needs a second. */
  placesLeft: number
  /** The attendee has never given their details, so they are asked for, not confirmed (AC2). */
  isFirstTime: boolean
  isBusy: boolean
  /** Why the details were refused, shown in the dialog so nothing typed is lost. */
  error: string | null
  /** The attendee's details, and their guest's, or null when they bring none. */
  onConfirm: (details: AttendeeDetails, guest: GuestDetails | null) => void
  onCancel: () => void
}

/**
 * Story 18.4 - "Confirm your details", opened by every Register on an event's page; confirming
 * registers, and nothing is registered until then. AC2: the first time, the details are asked for.
 * AC3: after that they are filled in from the attendee's profile, to check before registering
 * (CL-167); a change made here is saved to My profile with the registration.
 * AC1/AC7: a missing name, or a missing or wrong phone number, stops the confirm before anything
 * is sent, announced and tied to its field. 18.1 AC6: Confirm and register is disabled while the
 * registration is on its way, so a double-click sends one. On a phone the dialog fits the screen
 * and its buttons are at least 44px tall (App.css `.attendee-details-dialog`).
 *
 * AC12 (fix f18.4.1): below their own details, Add a guest opens one guest's fields, blank, which
 * Remove guest takes off again; the guest's problems stop the confirm too, and focus goes to the
 * first problem - the attendee's own before their guest's. AC13: a guest takes a second place, so
 * with one place left Add a guest is unavailable and says why; a refusal for want of that place,
 * the server's own, stays here with the rest of the server's refusals of what was sent.
 */
export function AttendeeDetailsDialog({
  initial,
  eventName,
  placesLeft,
  isFirstTime,
  isBusy,
  error,
  onConfirm,
  onCancel,
}: AttendeeDetailsDialogProps) {
  const form = useAttendeeDetailsForm(initial)
  const guestForm = useAttendeeDetailsForm(NO_GUEST, GUEST_CHECKS)
  const [hasGuest, setHasGuest] = useState(false)
  const addGuestButton = useRef<HTMLButtonElement>(null)
  // Where focus goes once Add a guest or Remove guest has re-rendered the dialog.
  const focusAfterChange = useRef<'guest' | 'add-guest' | null>(null)
  const noRoomId = useId()
  const hasRoomForGuest = placesLeft >= PLACES_WITH_GUEST
  const guestNameInput = guestForm.nameInput

  useEffect(() => {
    if (focusAfterChange.current === 'guest') guestNameInput.current?.focus()
    if (focusAfterChange.current === 'add-guest') addGuestButton.current?.focus()
    focusAfterChange.current = null
  }, [hasGuest, guestNameInput])

  function handleAddGuest() {
    focusAfterChange.current = 'guest'
    setHasGuest(true)
  }

  /** Nothing typed for a guest taken off is kept: added again, they start blank. */
  function handleRemoveGuest() {
    guestForm.reset(NO_GUEST)
    focusAfterChange.current = 'add-guest'
    setHasGuest(false)
  }

  function handleConfirm() {
    // Every problem is shown; the attendee's own are checked last, so the first of theirs takes
    // the focus ahead of any of their guest's.
    const isGuestReady = !hasGuest || guestForm.canSend()
    const isAttendeeReady = form.canSend()
    if (isGuestReady && isAttendeeReady) {
      onConfirm(form.details, hasGuest ? guestForm.details : null)
    }
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
      {hasGuest ? (
        <GuestFields form={guestForm} isBusy={isBusy} onRemove={handleRemoveGuest} />
      ) : (
        <div className="stack add-guest">
          <div>
            <button
              ref={addGuestButton}
              type="button"
              className="secondary"
              disabled={!hasRoomForGuest || isBusy}
              aria-describedby={hasRoomForGuest ? undefined : noRoomId}
              onClick={handleAddGuest}
            >
              Add a guest
            </button>
          </div>
          {!hasRoomForGuest && (
            <p id={noRoomId} className="small muted">
              {NO_ROOM_FOR_GUEST_NOTE}
            </p>
          )}
        </div>
      )}
    </ConfirmDialog>
  )
}
