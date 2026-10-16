import type { ChangeEvent } from 'react'
import { PHONE_REGIONS, type PhoneRegion } from './phoneRegions'

export interface PhoneRegionSelectProps {
  value: PhoneRegion
  onChange: (region: PhoneRegion) => void
}

/**
 * Story 2.1 AC21/AC24 (f2.1.4): the contact phone's country or region, each shown with its calling
 * code, in front of the number - on the request form and on the event page's point-of-contact
 * update (story 19.1 AC2). A native select, so typing a name's first letters jumps to it.
 */
export function PhoneRegionSelect({ value, onChange }: PhoneRegionSelectProps) {
  function handleChange(change: ChangeEvent<HTMLSelectElement>) {
    const region = PHONE_REGIONS.find((each) => each.code === change.target.value)
    if (region !== undefined) onChange(region)
  }

  return (
    <label>
      Country or region
      <select value={value.code} onChange={handleChange}>
        {PHONE_REGIONS.map((region) => (
          <option key={region.code} value={region.code}>
            {region.name} (+{region.callingCode})
          </option>
        ))}
      </select>
    </label>
  )
}
