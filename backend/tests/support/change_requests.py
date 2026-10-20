"""Set-up shared by the tests that approve a change request (stories 19.2 and 19.3, and the
stories whose rules an approval applies).

Since story 19.3 AC7 an approval carries the fingerprint of the impact assessment the coordinator
saw, so approving reads the assessment first, as the approval dialog does. Kept here so the next
change to that contract is made in one place.
"""

from __future__ import annotations

import uuid


def approve_as_seen(
    client, event_id: uuid.UUID, request_id: uuid.UUID, *, fallback: str | None = None
):
    """``POST .../approve`` as ``client``, with the fingerprint of the assessment it reads just
    before. Where it cannot read one - the request already decided, the client not its
    coordinator - ``fallback`` is sent instead, so the approval's own refusal answers; without
    one, an unreadable assessment fails the test."""
    url = f"/events/{event_id}/change-requests/{request_id}"
    seen = client.get(f"{url}/impact")
    if seen.status_code == 200:
        fingerprint = seen.json()["fingerprint"]
    else:
        assert fallback is not None, seen.text
        fingerprint = fallback
    return client.post(f"{url}/approve", json={"assessment_fingerprint": fingerprint})
