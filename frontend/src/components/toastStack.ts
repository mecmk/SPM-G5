import { useSyncExternalStore } from 'react'

/** The space between two stacked toasts, matching `.toast-stack`'s gap. */
const GAP_PX = 8

/**
 * The error toasts on screen, oldest first, with their heights. Each `ErrorToast` is rendered
 * beside what it is about, wherever that is on the page, so they cannot stack by layout: each
 * reads its own distance from the corner here instead, and the notification toasts sit above all
 * of them.
 */
let shown: { id: string; height: number }[] = []
const listeners = new Set<() => void>()

function announce() {
  listeners.forEach((listener) => listener())
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
