import { useState, type FormEvent } from 'react'
import { formatApiError } from '../api/client'
import {
  MAX_SAFETY_TEXT_LENGTH,
  decideSafetyCheck,
  type SafetyArrangement,
  type SafetyCheckDetail,
  type SafetyReviewOutcome,
} from '../api/safety'
import { ERROR_REGISTRY } from '../errors/registry'
import { ARRANGEMENT_LABELS } from '../shared/safetyReview'

const OUTCOMES: { value: SafetyReviewOutcome; label: string }[] = [
  { value: 'APPROVED', label: 'Approve' },
  { value: 'CHANGES_REQUESTED', label: 'Request changes' },
]

interface FindingDraft {
  key: number
  factorCode: string
  requiredChange: string
  arrangement: SafetyArrangement | ''
}

interface SafetyDecisionFormProps {
  check: SafetyCheckDetail
  onDecided: (check: SafetyCheckDetail) => void
}

/**
 * Story 21.2 - the Safety Officer's decision on an event awaiting the check.
 * AC2/AC5: Approve or Request changes, nothing else. AC4: requesting changes takes findings, each
 * a review factor, exactly what must change and optionally the arrangement to rebook. AC9: no
 * notes. AC10: each finding must say what must change - checked here before
 * anything is sent.
 */
export function SafetyDecisionForm({ check, onDecided }: SafetyDecisionFormProps) {
  const firstFactor = check.factors[0]?.code ?? ''
  const [outcome, setOutcome] = useState<SafetyReviewOutcome>('APPROVED')
  const [findings, setFindings] = useState<FindingDraft[]>([
    { key: 1, factorCode: firstFactor, requiredChange: '', arrangement: '' },
  ])
  const [hasTriedToSubmit, setHasTriedToSubmit] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isRequestingChanges = outcome === 'CHANGES_REQUESTED'
  const isFindingBlank =
    isRequestingChanges && findings.some((finding) => !finding.requiredChange.trim())

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
      },
    ])
  }

  function removeFinding(key: number) {
    setFindings((drafts) => drafts.filter((draft) => draft.key !== key))
  }

  async function sendDecision() {
    setIsSubmitting(true)
    setError(null)
    try {
      const updated = await decideSafetyCheck(check.id, check.name, {
        outcome,
        findings: isRequestingChanges
          ? findings.map((finding) => ({
              factor_code: finding.factorCode,
              required_change: finding.requiredChange,
              arrangement: finding.arrangement || null,
            }))
          : [],
      })
      onDecided(updated)
    } catch (caught) {
      setError(formatApiError(caught))
      setIsSubmitting(false)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setHasTriedToSubmit(true)
    if (isFindingBlank) return
    void sendDecision()
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
                  />
                </label>
                <label>
                  Arrangement to rebook
                  <select
                    value={finding.arrangement}
                    onChange={(event) =>
                      updateFinding(finding.key, {
                        arrangement: event.target.value as SafetyArrangement | '',
                      })
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
            {hasTriedToSubmit && isFindingBlank && (
              <p role="alert" className="error">
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
