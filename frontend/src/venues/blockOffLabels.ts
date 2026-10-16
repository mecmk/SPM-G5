/**
 * Story 9.4: the words Venue Staff's block-off card, its form and its confirmation share, so the
 * card says what the page and the dialog say. Adding a closure is "Block off time"; editing one is
 * "Edit blocked-off time".
 */
export const BLOCK_OFF_LABEL = 'Block off time'
export const EDIT_BLOCK_OFF_LABEL = 'Edit blocked-off time'

/** The card's heading, the form's own button and the confirmation's button. */
export function blockOffLabel(isEditing: boolean): string {
  return isEditing ? EDIT_BLOCK_OFF_LABEL : BLOCK_OFF_LABEL
}

/** The confirmation's title, which names the venue: "Block off time at Harbour Pavilion". */
export function blockOffTitle(isEditing: boolean, venueName: string): string {
  return `${blockOffLabel(isEditing)} at ${venueName}`
}
