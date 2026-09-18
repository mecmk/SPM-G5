export interface FilterPillOption<TKey extends string> {
  key: TKey
  label: string
}

export interface FilterPillsProps<TKey extends string> {
  options: FilterPillOption<TKey>[]
  value: TKey
  onChange: (key: TKey) => void
}

/** Story c3 - a row of single-select toggle filters, e.g. status filters above a list. */
export function FilterPills<TKey extends string>({
  options,
  value,
  onChange,
}: FilterPillsProps<TKey>) {
  return (
    <div className="pills">
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          className="pill"
          aria-pressed={option.key === value}
          onClick={() => onChange(option.key)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
