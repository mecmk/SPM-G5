import type { EventStatus } from '../api/events'

/** Story 7.2 AC3: routine editing (and the internal-notes view) closes at these statuses. */
export const TERMINAL_STATUSES: readonly EventStatus[] = ['COMPLETED', 'CANCELLED', 'REJECTED']
