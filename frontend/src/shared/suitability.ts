import type { FailedCriterion, VenueSuitability } from '../api/venues'

/** Story 11.1 AC5: what a characteristic the venue has not recorded reads as. Never met. */
const UNKNOWN = 'Unknown'

/**
 * Story 11.1 AC1/AC5: one criterion a venue fails, as the coordinator reads it - the venue's
 * value against the requirement's ("Capacity 80 < 120 people"), naming the layout whose capacity
 * was compared where there was one, and "Unknown" for what the venue has not recorded. Shared by
 * the catalogue and the request step, so both word a failure the same way.
 */
export function describeFailure(failure: FailedCriterion): string {
  const name = failure.name ?? ''
  const isUnknown = failure.outcome === 'UNKNOWN'
  switch (failure.criterion) {
    case 'CAPACITY':
      return failure.code === null
        ? `Capacity ${failure.venue_value} < ${failure.required} people`
        : `Capacity in ${name} ${failure.venue_value} < ${failure.required} people`
    case 'LAYOUT':
      return isUnknown ? `Layout ${name}: ${UNKNOWN}` : `Layout ${name} not offered`
    case 'FACILITY': {
      const needed = failure.required === null ? name : `${name} ×${failure.required}`
      return isUnknown ? `${needed}: ${UNKNOWN}` : `${needed} not offered`
    }
    case 'FACILITY_QUANTITY':
      return isUnknown
        ? `${name} ×${failure.required}: ${UNKNOWN}`
        : `${name}: ${failure.venue_value} available, ${failure.required} needed`
    case 'ACCESSIBILITY':
      return isUnknown ? `${name}: ${UNKNOWN}` : `${name} not available`
  }
}

/**
 * Story 11.1 AC1: the verdict as a word - "Suitable" or "Unsuitable" - naming the venue
 * requirement judged only when the event has several (decided 6 Oct 2026).
 */
export function suitabilityLabel(suitability: VenueSuitability, requirementCount: number): string {
  const verdict = suitability.is_suitable ? 'Suitable' : 'Unsuitable'
  return requirementCount > 1 && suitability.requirement_name !== null
    ? `${verdict} for ${suitability.requirement_name}`
    : verdict
}
