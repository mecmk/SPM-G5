import { useSyncExternalStore } from 'react'

/** The space between two stacked toasts, matching `.toast-stack`'s gap. */
const GAP_PX = 8
/** The stack's distance from the bottom of the screen, matching `.error-toast`'s 1rem. */
const EDGE_PX = 16
/** The room the error toasts take at the foot of the screen, which the page and dialogs keep clear
 *  (`#root::after`, `.dialog` in App.css), so a toast never hides a form's buttons for good. */
const SPACE_VARIABLE = '--error-toasts-space'

/**
 * The error toasts on screen, oldest first, with their heights. Each `ErrorToast` is rendered
 * beside what it is about, wherever that is on the page, so they cannot stack by layout: each
 * reads its own distance from the corner here instead, and the notification toasts sit above all
 * of them.
 */
let shown: { id: string; height: number }[] = []
const listeners = new Set<() => void>()

let isClearingFocus = false

function announce() {
  const space = shown.length > 0 ? heightOf(shown) + EDGE_PX : 0
  document.documentElement.style.setProperty(SPACE_VARIABLE, `${space}px`)
  listeners.forEach((listener) => listener())
  if (shown.length > 0) clearFocusOfToasts()
}

/**
 * Once the toasts have moved into place, scrolls the focused element up out from under them. A
 * refused save leaves focus on its button, and the toasts it raises can land on top of it (WCAG
 * 2.4.11, focus not obscured). `html`'s scroll-padding-bottom (App.css) stops the scroll above them.
 */
function clearFocusOfToasts() {
  if (isClearingFocus) return
  isClearingFocus = true
  requestAnimationFrame(() => {
    isClearingFocus = false
    const focused = document.activeElement
    if (!(focused instanceof HTMLElement) || focused === document.body) return
    if (focused.closest('.error-toast')) return
    const box = focused.getBoundingClientRect()
    const isCovered = [...document.querySelectorAll('.error-toast')].some((toast) => {
      const cover = toast.getBoundingClientRect()
      return (
        cover.left < box.right &&
        box.left < cover.right &&
        cover.top < box.bottom &&
        box.top < cover.bottom
      )
    })
    if (isCovered) focused.scrollIntoView({ block: 'nearest' })
  })
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function heightOf(toasts: typeof shown) {
  return toasts.reduce((total, toast) => total + toast.height + GAP_PX, 0)
}

export function placeErrorToast(id: string, height: number) {
  const index = shown.findIndex((toast) => toast.id === id)
  if (index === -1) shown = [...shown, { id, height }]
  else if (shown[index].height !== height)
    shown = shown.map((toast) => (toast.id === id ? { id, height } : toast))
  else return
  announce()
}

export function removeErrorToast(id: string) {
  shown = shown.filter((toast) => toast.id !== id)
  announce()
}

/** How far above the corner this toast sits: the newest is lowest, so they read top to bottom in
 *  the order they appeared. */
export function useErrorToastOffset(id: string): number {
  return useSyncExternalStore(subscribe, () => {
    const index = shown.findIndex((toast) => toast.id === id)
    return index === -1 ? 0 : heightOf(shown.slice(index + 1))
  })
}

/** The height of every error toast on screen, with the gap above them, or 0 when there are none. */
export function useErrorToastsHeight(): number {
  return useSyncExternalStore(subscribe, () => heightOf(shown))
}
