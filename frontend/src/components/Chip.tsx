export type ChipTone = 'success' | 'info' | 'warning' | 'danger'

export interface ChipProps {
  label: string
  tone?: ChipTone
}

/** Story c3 - a small filled label for facilities, tags and calendar legends. */
export function Chip({ label, tone }: ChipProps) {
  return <span className={`chip${tone ? ` chip-${tone}` : ''}`}>{label}</span>
}
