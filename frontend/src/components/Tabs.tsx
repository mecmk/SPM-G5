export interface TabItem<TKey extends string> {
  key: TKey
  label: string
}

export interface TabsProps<TKey extends string> {
  tabs: TabItem<TKey>[]
  activeKey: TKey
  onChange: (key: TKey) => void
}

/** Story c3 - a horizontal tab strip. The page owns which tab is active. */
export function Tabs<TKey extends string>({ tabs, activeKey, onChange }: TabsProps<TKey>) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={tab.key === activeKey}
          className="tab"
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
