/**
 * Pure date-grid math for the Calendar component. No React and no JSX here - Calendar.tsx turns
 * these into cells.
 */

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const

export function weekdayLabels(): readonly string[] {
  return WEEKDAY_LABELS
}

/**
 * One cell per day of `month`, Monday-first, padded with `null`s at both ends so day 1 lands in
 * the right weekday column and the last week is complete.
 */
export function monthGrid(year: number, month: number): (number | null)[] {
  const firstWeekday = new Date(year, month, 1).getDay() // 0 = Sunday
  const leadingBlanks = (firstWeekday + 6) % 7 // shift to Monday-first
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const cells: (number | null)[] = Array.from({ length: leadingBlanks }, () => null)
  for (let day = 1; day <= daysInMonth; day += 1) {
    cells.push(day)
  }
  while (cells.length % 7 !== 0) {
    cells.push(null)
  }
  return cells
}

/** `YYYY-MM-DD` for a given year / zero-based month / day, matching backend date strings. */
export function isoDate(year: number, month: number, day: number): string {
  const monthPart = String(month + 1).padStart(2, '0')
  const dayPart = String(day).padStart(2, '0')
  return `${year}-${monthPart}-${dayPart}`
}

/** Whether the grid column at `columnIndex` (0 = Monday) falls on a weekend. */
export function isWeekendColumn(columnIndex: number): boolean {
  return columnIndex % 7 >= 5
}

export function formatMonthYear(month: Date): string {
  return month.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
}
