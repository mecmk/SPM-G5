/**
 * Fix f16.2.6: Chrome counts a focused number box up or down as the mouse wheel or a trackpad turns
 * over it, so a 10 typed in the Units box and then scrolled past on the way to Save was saved as 1
 * (the box stops at its minimum). This leaves the box as the wheel turns over it, so the page
 * scrolls and the number stays as typed. Registered once for the whole app, so every
 * `type="number"` box has it, including ones added later.
 */
export function leaveNumberBoxOnWheel(): void {
  document.addEventListener(
    'wheel',
    (event) => {
      const box = document.activeElement
      if (box instanceof HTMLInputElement && box.type === 'number' && box === event.target) {
        box.blur()
      }
    },
    // Capture: runs before the browser's own count, and passive: the page still scrolls.
    { capture: true, passive: true },
  )
}
