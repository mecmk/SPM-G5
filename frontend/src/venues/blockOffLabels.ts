/**
 * Story 9.4: the words Venue Staff's block-off card, its form and its confirmation share, so the
 * card says what the page and the dialog say. Adding a closure is "Block off time"; editing one is
 * "Edit blocked-off time".
 */
export const BLOCK_OFF_LABEL = 'Block off time'
export const EDIT_BLOCK_OFF_LABEL = 'Edit blocked-off time'

/** Fix f9.4.1: the name of the calendar's card, on the details page and the Edit venue page. */
export const AVAILABILITY_LABEL = 'Availability'

/** Story 9.4 AC6, fix f9.4.1: said beside the button each belongs to, so Venue Staff know what it
 * will do before pressing it: Remove is for a closure not yet started, End now for one in force. */
export const REMOVE_CLOSURE_HINT = 'Not started yet: removes it completely'
export const END_CLOSURE_HINT = 'Ends the whole closure now; the time already passed is kept'

/** Fix f9.4.1: said under the form's Save changes, above the closure sections, which are not
 * part of the form: a closure is saved by its own Save closure, not by the venue's Save changes. */
export const CLOSURES_SAVED_NOTE =
  'Closures are saved as soon as you add them; Save changes is not needed.'

/** The card's heading, the form's own button and the confirmation's button. */
export function blockOffLabel(isEditing: boolean): string {
  return isEditing ? EDIT_BLOCK_OFF_LABEL : BLOCK_OFF_LABEL
}

/** The confirmation's title, which names the venue: "Block off time at Harbour Pavilion". */
export function blockOffTitle(isEditing: boolean, venueName: string): string {
  return `${blockOffLabel(isEditing)} at ${venueName}`
}
