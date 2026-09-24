/** Turns a backend status code like `UNDER_REVIEW` into `Under review`. */
function formatStatusLabel(status: string): string {
  const lower = status.toLowerCase().replace(/_/g, ' ')
  return lower.charAt(0).toUpperCase() + lower.slice(1)
}

export interface StatusBadgeProps {
  status: string
  /** Override the auto-generated label, e.g. for a code with an unusual display form. */
  label?: string
}

/**
 * Story c3 - a status pill for events, bookings, equipment requests and venues. Pair a new
 * status code with a `.badge-<status-lowercase>` rule in App.css, or it falls back to the
 * default border/background.
 */
export function StatusBadge({ status, label }: StatusBadgeProps) {
  return (
    <span className={`badge badge-${status.toLowerCase()}`}>
      {label ?? formatStatusLabel(status)}
    </span>
  )
}
