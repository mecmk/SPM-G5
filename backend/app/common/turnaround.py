"""The longest setup or teardown, shared by a booking request's own (story 12.1 AC5) and a venue's
defaults (story 8.3 AC14), so the two can never drift apart. Mirrored by
``TURNAROUND_MAX_MINUTES`` in ``frontend/src/api/bookings.ts`` - keep the two in step."""

from __future__ import annotations

# Story 12.1 AC5, decided for f12.1.2 (14 Oct 2026) and not in the backlog: setup and teardown are
# each at most 14 days, the longest an event may run. A venue's own defaults have the same limit
# (story 8.3 AC14, fix f8.3.4).
TURNAROUND_MAX_MINUTES = 14 * 24 * 60
