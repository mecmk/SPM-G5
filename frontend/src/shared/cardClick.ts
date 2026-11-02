import type { MouseEvent } from 'react'

/** Anything a click on it is meant for, so the card does not also open. */
const INTERACTIVE_ELEMENTS =
  'a, button, input, select, textarea, label, summary, [role="button"], [role="link"]'

/**
 * Whether a click on a linked card should open it: a plain primary click that is not on a control
 * inside the card (a button, another link) and does not end a text selection. Shared by
 * `EventCard` (story 7.1) and `VenueCard` (story 8.1 AC1).
 */
export function isCardOpenClick(click: MouseEvent<HTMLElement>): boolean {
  if (click.button !== 0) return false
  if (click.metaKey || click.ctrlKey || click.shiftKey || click.altKey) return false
  if (click.target instanceof Element) {
    const inner = click.target.closest(INTERACTIVE_ELEMENTS)
    if (inner !== null && click.currentTarget.contains(inner)) return false
  }
  return window.getSelection()?.isCollapsed !== false
}
