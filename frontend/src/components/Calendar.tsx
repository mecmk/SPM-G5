import {
  formatDayLabel,
  formatMonthYear,
  isoDate,
  isWeekendColumn,
  monthGrid,
  weekdayLabels,
} from './calendarGrid'

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
  /**
   * Story 9.1 AC5: called with a day's `YYYY-MM-DD` when a day that has entries is pressed, so the
   * parent can list them. Omit and a day with entries is not pressable, as before.
   */
  onOpenDay?: (date: string) => void
  /** The day whose list is open (`YYYY-MM-DD`), or null. Marks that day's button expanded. */
  openDay?: string | null
  /** The id of the list an open day controls, for its button's `aria-controls`. */
  openDayPanelId?: string
  legend?: CalendarLegendItem[]
  /**
   * f9.1.1: `entries` may not reflect true availability - a fetch is still in flight, or the last
   * one failed. Dims the day grid and marks it accordingly for assistive tech, without touching
   * Prev/Next: the month is still navigable while its own data is unknown.
   */
  gridStatus?: 'loading' | 'unknown'
}

// How many of a day's entries its cell shows; the rest are "+N more".
const MAX_ENTRIES_SHOWN = 2

/**
 * Story 9.1 AC5: an openable day's name for assistive tech - the date, how many items, and the
 * entries its cell shows, "+N more" included, so the name contains the visible text (WCAG 2.5.3)
 * and not only a count.
 */
function openableDayName(dayLabel: string, dayEntries: CalendarEntry[]): string {
  const count = `${dayEntries.length} ${dayEntries.length === 1 ? 'item' : 'items'}`
  const shown = dayEntries.slice(0, MAX_ENTRIES_SHOWN).map((entry) => entry.label)
  const hiddenCount = dayEntries.length - shown.length
  const summary = hiddenCount > 0 ? [...shown, `+${hiddenCount} more`] : shown
  return `${dayLabel}, ${count}: ${summary.join('; ')}`
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
 *
 * Story 9.1 AC5: with `onOpenDay`, a day that has entries is a button the parent answers by
 * listing them (`openDay` marks the open one). Without it the calendar is as it was.
 */
export function Calendar({
  month,
  onMonthChange,
  entries,
  onSelectDay,
  onOpenDay,
  openDay = null,
  openDayPanelId,
  legend,
  gridStatus,
}: CalendarProps) {
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

  function handleOpenDay(date: string) {
    onOpenDay?.(date)
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

      <div
        className={`calendar${gridStatus ? ` calendar-${gridStatus}` : ''}`}
        aria-label={`Calendar for ${formatMonthYear(month)}`}
        aria-busy={gridStatus === 'loading' ? true : undefined}
      >
        {weekdayLabels().map((label) => (
          <div key={label} className="calendar-head">
            {label}
          </div>
        ))}
        {cells.map((day, index) => {
          if (day === null) {
            return <div key={`blank-${index}`} className="calendar-cell calendar-cell-blank" />
          }

          const date = isoDate(year, monthIndex, day)
          const dayEntries = entriesForDay(day)
          const tone = strongestTone(dayEntries)
          const isWeekend = isWeekendColumn(index)
          const isSelectable = Boolean(onSelectDay) && dayEntries.length === 0
          const isOpenable = Boolean(onOpenDay) && dayEntries.length > 0
          const isOpen = isOpenable && openDay === date
          const cellClassName = [
            'calendar-cell',
            tone ? `calendar-cell-${tone}` : '',
            !tone && isWeekend ? 'calendar-cell-weekend' : '',
            isSelectable ? 'calendar-cell-selectable' : '',
            isOpenable ? 'calendar-cell-openable' : '',
            isOpen ? 'calendar-cell-open' : '',
          ]
            .filter(Boolean)
            .join(' ')

          // A button may only hold phrasing content, so an openable or selectable day's parts
          // are spans; a plain (unclickable) day keeps the divs it has always had.
          const Part = isOpenable || isSelectable ? 'span' : 'div'
          const cellContent = (
            <>
              <Part className="calendar-day">{day}</Part>
              {dayEntries.slice(0, MAX_ENTRIES_SHOWN).map((entry) => (
                <Part
                  key={entry.id}
                  className={`calendar-entry calendar-entry-${entry.tone}`}
                  title={entry.label}
                >
                  {entry.label}
                </Part>
              ))}
              {dayEntries.length > MAX_ENTRIES_SHOWN && (
                <Part className="calendar-more">+{dayEntries.length - MAX_ENTRIES_SHOWN} more</Part>
              )}
              {isSelectable && !isWeekend && <Part className="calendar-hint">Available</Part>}
            </>
          )

          if (isOpenable) {
            return (
              <button
                key={day}
                type="button"
                className={cellClassName}
                aria-expanded={isOpen}
                aria-controls={isOpen ? openDayPanelId : undefined}
                aria-label={openableDayName(formatDayLabel(year, monthIndex, day), dayEntries)}
                onClick={() => handleOpenDay(date)}
              >
                {cellContent}
              </button>
            )
          }

          if (isSelectable) {
            return (
              <button
                key={day}
                type="button"
                className={cellClassName}
                onClick={() => handleSelectDay(date)}
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
