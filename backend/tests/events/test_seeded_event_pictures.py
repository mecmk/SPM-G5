"""Chore c13 - the sample pictures the seeded events show. INTEGRATION test: the seeded database and
the files the frontend serves beside it.

A seeded event's picture is a file in frontend/public, which the frontend serves at its address
(events.cover_image_url's comment), so no upload ever checked it. This checks each one meets the
rules an upload must (story 2.1 AC14): the file is there, its bytes are a JPEG, PNG or WebP, and it
is no bigger than an upload may be. A picture that fails to load gives way to the placeholder
(18.1 AC8), so a broken path would otherwise fail nothing and show only as a placeholder.

Which event shows which picture is e2e-tested where a page shows it: Harbourfront Jazz Evening in
attendee-registration.spec.ts, Sunset Yoga by the Bay in my-registrations.spec.ts and Data
Literacy Workshop in events.spec.ts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.models import Event
from app.events.service import MAX_COVER_IMAGE_BYTES

# The frontend serves a seeded picture from here: its address is a path under it.
FRONTEND_PUBLIC = Path(__file__).resolve().parents[3] / "frontend" / "public"
SEEDED_PICTURE_PREFIX = "/images/events/"
# How a JPEG and a PNG begin; a WebP is a RIFF file whose format is WEBP (2.1 AC14).
JPEG_START = b"\xff\xd8\xff"
PNG_START = b"\x89PNG\r\n\x1a\n"


def _is_an_upload_format(content: bytes) -> bool:
    is_webp = content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return content.startswith((JPEG_START, PNG_START)) or is_webp


@pytest.mark.story("2.1", ac=14)
@pytest.mark.story("18.1", ac=8)
def test_every_seeded_event_picture_is_one_an_upload_could_be(db: Session):
    """Cannot fail first: the one seeded picture before c13 met these rules too. Proved instead
    by a seeded address with no file behind it, and by a file that is not a picture."""
    seeded = set(
        db.scalars(
            select(Event.cover_image_url).where(
                Event.cover_image_url.startswith(SEEDED_PICTURE_PREFIX)
            )
        )
    )

    assert seeded, "no seeded event has a picture"
    for url in sorted(seeded):
        path = FRONTEND_PUBLIC / url.removeprefix("/")
        assert path.is_file(), f"{url} names no file in frontend/public"
        content = path.read_bytes()
        assert _is_an_upload_format(content), f"{url} is not a JPEG, PNG or WebP"
        assert len(content) <= MAX_COVER_IMAGE_BYTES, f"{url} is bigger than an upload may be"
