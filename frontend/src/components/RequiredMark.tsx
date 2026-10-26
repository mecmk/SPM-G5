/**
 * Marks a field that must be filled in: story 2.1 AC10's event request, and story 18.4's
 * attendee details (AC1/AC7). Hidden from assistive technology, which reads the field's own
 * `aria-required` instead.
 */
export function RequiredMark() {
  return (
    <span className="req" aria-hidden="true">
      *
    </span>
  )
}
