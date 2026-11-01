import { useState, type FormEvent } from 'react'
import { ApiError, formatApiError } from '../api/client'
import {
  MAX_SAFETY_TEXT_LENGTH,
  decideSafetyCheck,
  type SafetyArrangement,
  type SafetyCheckDetail,
  type SafetyReviewOutcome,
} from '../api/safety'
import { ERROR_REGISTRY } from '../errors/registry'
import { turnaroundLine } from '../shared/bookingStatus'
import {
  ARRANGEMENT_LABELS,
  RELEASE_BOOKINGS_HINT,
  RELEASE_BOOKINGS_LEGEND,
  bookingChoiceLabel,
} from '../shared/safetyReview'

const OUTCOMES: { value: SafetyReviewOutcome; label: string }[] = [
  { value: 'APPROVED', label: 'Approve' },
  { value: 'CHANGES_REQUESTED', label: 'Request changes' },
]

interface FindingDraft {
  key: number
  factorCode: string
  requiredChange: string
  arrangement: SafetyArrangement | ''
  /** Story 21.3 AC1: the bookings ticked to release, by id; only a venue-bookings finding has any. */
  bookingIds: string[]
}

interface SafetyDecisionFormProps {
  check: SafetyCheckDetail
  onDecided: (check: SafetyCheckDetail) => void
  /** AC20: the decision was refused - decided by someone else meanwhile, or the facts moved since
   * the page was read - so the page loads the event again. */
  onRefused: () => void
}

const FINDING_ERROR_ID = 'safety-finding-error'

/**
 * Story 21.2 - the Safety Officer's decision on an event awaiting the check.
 * AC2/AC5: Approve or Request changes, nothing else, and neither is chosen until the officer picks
 * one. AC4: requesting changes takes findings, each a review factor, exactly what must change and
 * optionally the arrangement to rebook. AC9: no notes. AC10: each finding must say what must
 * change - checked here before anything is sent. AC20: the decision carries the facts the page was
 * read with, and a refusal has the page load the event again.
 * Story 21.3 - AC1: a finding about venue bookings lists the event's approved bookings to tick, each
 * with its setup line, and only while its arrangement is Venue bookings; switching away clears the
 * ticks. AC2: the ticked ids go with the finding (`booking_ids`), and recording the decision
 * releases them. AC7: a refusal that names bookings no longer approved has the page load again.
 */
export function SafetyDecisionForm({ check, onDecided, onRefused }: SafetyDecisionFormProps) {
  const firstFactor = check.factors[0]?.code ?? ''
  const [outcome, setOutcome] = useState<SafetyReviewOutcome | null>(null)
  const [findings, setFindings] = useState<FindingDraft[]>([
    { key: 1, factorCode: firstFactor, requiredChange: '', arrangement: '', bookingIds: [] },
  ])
  const [hasTriedToSubmit, setHasTriedToSubmit] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isRequestingChanges = outcome === 'CHANGES_REQUESTED'
  const isFindingBlank =
    isRequestingChanges && findings.some((finding) => !finding.requiredChange.trim())
  const showsOutcomeError = hasTriedToSubmit && outcome === null
  const showsFindingError = hasTriedToSubmit && isFindingBlank

  function updateFinding(key: number, change: Partial<FindingDraft>) {
    setFindings((drafts) =>
      drafts.map((draft) => (draft.key === key ? { ...draft, ...change } : draft)),
    )
  }

  function addFinding() {
    setFindings((drafts) => [
      ...drafts,
      {
        key: Math.max(...drafts.map((d) => d.key)) + 1,
        factorCode: firstFactor,
        requiredChange: '',
        arrangement: '',
        bookingIds: [],
      },
    ])
  }

  /** Story 21.3 AC1: another arrangement is another choice, so the ticks start again. */
  function changeArrangement(key: number, arrangement: SafetyArrangement | '') {
    updateFinding(key, { arrangement, bookingIds: [] })
  }

  function toggleBooking(key: number, bookingId: string, isTicked: boolean) {
    setFindings((drafts) =>
      drafts.map((draft) =>
        draft.key === key
          ? {
              ...draft,
              bookingIds: isTicked
                ? [...draft.bookingIds, bookingId]
                : draft.bookingIds.filter((id) => id !== bookingId),
            }
          : draft,
      ),
    )
  }

  function removeFinding(key: number) {
    setFindings((drafts) => drafts.filter((draft) => draft.key !== key))
  }

  async function sendDecision(chosen: SafetyReviewOutcome) {
    setIsSubmitting(true)
    setError(null)
    try {
      const updated = await decideSafetyCheck(check.id, check.name, {
        outcome: chosen,
        facts_fingerprint: check.facts_fingerprint,
        findings: isRequestingChanges
          ? findings.map((finding) => ({
              factor_code: finding.factorCode,
              required_change: finding.requiredChange,
              arrangement: finding.arrangement || null,
              booking_ids: finding.arrangement === 'VENUE_BOOKINGS' ? finding.bookingIds : [],
            }))
          : [],
      })
      onDecided(updated)
    } catch (caught) {
      setError(formatApiError(caught))
      setIsSubmitting(false)
      if (caught instanceof ApiError && (caught.status === 409 || caught.status === 404)) {
        onRefused()
      }
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setHasTriedToSubmit(true)
    if (outcome === null || isFindingBlank) return
    void sendDecision(outcome)
  }

  return (
    <section className="card stack" aria-labelledby="safety-decision-heading">
      <h2 id="safety-decision-heading">Decision</h2>
      <form className="stack" onSubmit={handleSubmit} noValidate>
        <fieldset className="cluster" disabled={isSubmitting}>
          <legend className="fact-label">Outcome</legend>
          {OUTCOMES.map(({ value, label }) => (
            <label key={value} className="checkbox">
              <input
                type="radio"
                name="safety-outcome"
                value={value}
                checked={outcome === value}
                onChange={() => setOutcome(value)}
              />
              {label}
            </label>
          ))}
        </fieldset>
        {showsOutcomeError && (
          <p role="alert" className="error">
            {ERROR_REGISTRY.SAFETY_OUTCOME_REQUIRED.message}
          </p>
        )}

        {isRequestingChanges && (
          <div className="stack">
            {findings.map((finding, index) => (
              <fieldset key={finding.key} className="subtle-block stack" disabled={isSubmitting}>
                <legend className="fact-label">Finding {index + 1}</legend>
                <label>
                  Factor
                  <select
                    value={finding.factorCode}
                    onChange={(event) =>
                      updateFinding(finding.key, { factorCode: event.target.value })
                    }
                  >
                    {check.factors.map((factor) => (
                      <option key={factor.code} value={factor.code}>
                        {factor.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  What must change
                  <textarea
                    value={finding.requiredChange}
                    onChange={(event) =>
                      updateFinding(finding.key, { requiredChange: event.target.value })
                    }
                    maxLength={MAX_SAFETY_TEXT_LENGTH}
                    rows={2}
                    aria-invalid={showsFindingError && !finding.requiredChange.trim()}
                    aria-describedby={
                      showsFindingError && !finding.requiredChange.trim()
                        ? FINDING_ERROR_ID
                        : undefined
                    }
                  />
                </label>
                <label>
                  Arrangement to rebook
                  <select
                    value={finding.arrangement}
                    onChange={(event) =>
                      changeArrangement(finding.key, event.target.value as SafetyArrangement | '')
                    }
                  >
                    <option value="">None</option>
                    {Object.entries(ARRANGEMENT_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                {finding.arrangement === 'VENUE_BOOKINGS' && (
                  <fieldset className="subtle-block stack">
                    <legend className="fact-label">{RELEASE_BOOKINGS_LEGEND}</legend>
                    <p className="small muted">{RELEASE_BOOKINGS_HINT}</p>
                    {check.venues.map((booking) => (
                      <div key={booking.booking_id}>
                        <label className="checkbox">
                          <input
                            type="checkbox"
                            checked={finding.bookingIds.includes(booking.booking_id)}
                            onChange={(event) =>
                              toggleBooking(finding.key, booking.booking_id, event.target.checked)
                            }
                          />
                          {bookingChoiceLabel(booking)}
                        </label>
                        <p className="small muted">{turnaroundLine(booking)}</p>
                      </div>
                    ))}
                  </fieldset>
                )}
                {findings.length > 1 && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => removeFinding(finding.key)}
                  >
                    Remove finding {index + 1}
                  </button>
                )}
              </fieldset>
            ))}
            {showsFindingError && (
              <p id={FINDING_ERROR_ID} role="alert" className="error">
                {ERROR_REGISTRY.SAFETY_FINDING_CHANGE_REQUIRED.message}
              </p>
            )}
            <button
              type="button"
              className="secondary"
              onClick={addFinding}
              disabled={isSubmitting}
            >
              Add finding
            </button>
          </div>
        )}

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div>
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Recording…' : 'Record decision'}
          </button>
        </div>
      </form>
    </section>
  )
}
