import { formatMonthYear, isoDate, isWeekendColumn, monthGrid, weekdayLabels } from './calendarGrid'

export type CalendarEntryTone = 'danger' | 'warning' | 'info' | 'success'

export interface CalendarEntry {
  id: string
  /** `YYYY-MM-DD` - the day this entry is shown on. */
  date: string
  label: string
  tone: CalendarEntryTone
}

export interface CalendarLegendItem {
  tone: CalendarEntryTone
  label: string
}

export interface CalendarProps {
  /** The month being viewed. Only the year and month are read - the day is ignored. */
  month: Date
  onMonthChange: (nextMonth: Date) => void
  entries: CalendarEntry[]
  /** Called with a day's `YYYY-MM-DD` when a day with no entries is clicked. Omit for read-only. */
  onSelectDay?: (date: string) => void
  legend?: CalendarLegendItem[]
}

const TONE_RANK: Record<CalendarEntryTone, number> = {
  success: 0,
  info: 1,
  warning: 2,
  danger: 3,
}

function strongestTone(entries: CalendarEntry[]): CalendarEntryTone | null {
  if (entries.length === 0) return null
  return entries.reduce<CalendarEntryTone>(
    (strongest, entry) => (TONE_RANK[entry.tone] > TONE_RANK[strongest] ? entry.tone : strongest),
    entries[0].tone,
  )
}

/**
 * Story c3 - a month calendar for showing venue and equipment availability. Presentational and
 * controlled: the parent owns which month is open and what happens when a free day is clicked.
 */
export function Calendar({ month, onMonthChange, entries, onSelectDay, legend }: CalendarProps) {
  const year = month.getFullYear()
  const monthIndex = month.getMonth()
  const cells = monthGrid(year, monthIndex)

  function handlePrevMonth() {
    onMonthChange(new Date(year, monthIndex - 1, 1))
  }

  function handleNextMonth() {
    onMonthChange(new Date(year, monthIndex + 1, 1))
  }

  function handleSelectDay(date: string) {
    onSelectDay?.(date)
  }

  function entriesForDay(day: number): CalendarEntry[] {
    const date = isoDate(year, monthIndex, day)
    return entries.filter((entry) => entry.date === date)
  }

  return (
    <div>
      <div className="calendar-nav">
        <button type="button" className="ghost button-sm" onClick={handlePrevMonth}>
          ← Prev
        </button>
        <span className="calendar-title">{formatMonthYear(month)}</span>
        <button type="button" className="ghost button-sm" onClick={handleNextMonth}>
          Next →
        </button>
      </div>

      <div className="calendar" aria-label={`Calendar for ${formatMonthYear(month)}`}>
        {weekdayLabels().map((label) => (
          <div key={label} className="calendar-head">
            {label}
          </div>
        ))}
        {cells.map((day, index) => {
          if (day === null) {
            return <div key={`blank-${index}`} className="calendar-cell calendar-cell-blank" />
          }

          const dayEntries = entriesForDay(day)
          const tone = strongestTone(dayEntries)
          const isWeekend = isWeekendColumn(index)
          const isSelectable = Boolean(onSelectDay) && dayEntries.length === 0
          const cellClassName = [
            'calendar-cell',
            tone ? `calendar-cell-${tone}` : '',
            !tone && isWeekend ? 'calendar-cell-weekend' : '',
            isSelectable ? 'calendar-cell-selectable' : '',
          ]
            .filter(Boolean)
            .join(' ')

          const cellContent = (
            <>
              <div className="calendar-day">{day}</div>
              {dayEntries.slice(0, 2).map((entry) => (
                <div
                  key={entry.id}
                  className={`calendar-entry calendar-entry-${entry.tone}`}
                  title={entry.label}
                >
                  {entry.label}
                </div>
              ))}
              {dayEntries.length > 2 && (
                <div className="calendar-more">+{dayEntries.length - 2} more</div>
              )}
              {isSelectable && !isWeekend && <div className="calendar-hint">Available</div>}
            </>
          )

          if (isSelectable) {
            return (
              <button
                key={day}
                type="button"
                className={cellClassName}
                onClick={() => handleSelectDay(isoDate(year, monthIndex, day))}
              >
                {cellContent}
              </button>
            )
          }

          return (
            <div key={day} className={cellClassName}>
              {cellContent}
            </div>
          )
        })}
      </div>

      {legend && legend.length > 0 && (
        <div className="calendar-legend">
          {legend.map((item) => (
            <span key={item.tone} className="legend-item">
              <span className={`legend-swatch legend-swatch-${item.tone}`} />
              {item.label}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
