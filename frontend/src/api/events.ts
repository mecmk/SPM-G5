import { api } from './client'

/** Mirrors `ReviewQueueSort` in backend/app/events/schemas.py. */
export type ReviewQueueSort = 'submitted_at' | 'starts_at'
export type ReviewQueueStatus = 'SUBMITTED' | 'UNDER_REVIEW' | 'CLARIFICATION_REQUESTED'

/** Mirrors `ReviewQueueEntry`: one row of the coordinator's review queue. */
export interface ReviewQueueEntry {
  id: string
  name: string
  organiser_name: string
  starts_at: string
  ends_at: string
  submitted_at: string | null
  status: ReviewQueueStatus
  cover_image_url: string | null
}

export interface ReviewQueueQuery {
  sort: ReviewQueueSort
  coordinatorId: string | null
}

/** Story 4.1 AC1/AC3: the requests waiting for a decision, in the chosen order. */
export function listReviewQueue(query: ReviewQueueQuery): Promise<ReviewQueueEntry[]> {
  const params = new URLSearchParams({ sort: query.sort })
  if (query.coordinatorId !== null) params.set('coordinator_id', query.coordinatorId)
  return api<ReviewQueueEntry[]>(`/events/review-queue?${params.toString()}`)
}
