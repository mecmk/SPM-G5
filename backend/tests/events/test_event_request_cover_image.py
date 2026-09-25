"""Story 2.1 - be: the cover picture on an event request (AC14, added after customer feedback).

AC14 The organiser can give a request a cover picture (JPEG, PNG or WebP, at most 5 MB), replace
     it and remove it while the request is a draft. It is optional and not needed to submit.
     Once the request is submitted the picture cannot be changed. Only the organiser who owns
     the request can change it. The picture is served from ``cover_image_url`` and shows in the
     organiser's list and on the reviewing coordinator's queue and details.

Choosing, previewing and dragging a file onto the form are e2e cases:
tests/e2e/event-request.spec.ts. Files are written to a per-test temporary folder, never to the
real upload folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from tests.support.factories import create_event_request, create_submittable_event_request
from tests.support.seed import Events, Users

COVER_IMAGE_PATH = "/events/{event_id}/cover-image"
MAX_BYTES = 5 * 1024 * 1024
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"\x00" * 32
_GIF = b"GIF89a" + b"\x00" * 32
_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
_PDF = b"%PDF-1.4\n" + b"\x00" * 32
NON_ORGANISERS = [
    pytest.param(Users.COORDINATOR, id="coordinator"),
    pytest.param(Users.VENUE_STAFF, id="venue-staff"),
    pytest.param(Users.TECH_SUPPORT, id="tech-support"),
    pytest.param(Users.ATTENDEE, id="attendee"),
]


@pytest.fixture(autouse=True)
def upload_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    return tmp_path


def _padded(header: bytes, size: int) -> bytes:
    return header + b"\x00" * (size - len(header))


def _upload(client, event_id, content: bytes = _PNG, name: str = "cover.png", mime="image/png"):
    return client.put(
        COVER_IMAGE_PATH.format(event_id=event_id), files={"file": (name, content, mime)}
    )


def _remove(client, event_id):
    return client.delete(COVER_IMAGE_PATH.format(event_id=event_id))


def _stored_url(db: Session, event_id) -> str | None:
    return db.execute(
        text("SELECT cover_image_url FROM events WHERE id = :id"), {"id": str(event_id)}
    ).scalar_one()


def _files_in(folder: Path) -> list[Path]:
    return [path for path in folder.rglob("*") if path.is_file()]


# --- AC14: uploading ---------------------------------------------------------------------------
@pytest.mark.story("2.1", ac=14)
@pytest.mark.parametrize(
    ("content", "mime", "suffix"),
    [
        pytest.param(_PNG, "image/png", ".png", id="png"),
        pytest.param(_JPEG, "image/jpeg", ".jpg", id="jpeg"),
        pytest.param(_WEBP, "image/webp", ".webp", id="webp"),
    ],
)
def test_a_picture_is_saved_and_served(organiser_client, db: Session, content, mime, suffix):
    created = create_event_request(organiser_client)

    response = _upload(organiser_client, created["id"], content, f"photo{suffix}", mime)

    assert response.status_code == 200, response.text
    url = response.json()["cover_image_url"]
    assert url.startswith("/uploads/events/")
    assert url.endswith(suffix)
    assert _stored_url(db, created["id"]) == url
    served = organiser_client.get(url)
    assert served.status_code == 200
    assert served.content == content
    assert served.headers["content-type"] == mime


@pytest.mark.story("2.1", ac=14)
def test_the_picture_is_served_without_signing_in(organiser_client, client):
    created = create_event_request(organiser_client)
    url = _upload(organiser_client, created["id"]).json()["cover_image_url"]

    assert client.get(url).status_code == 200


@pytest.mark.story("2.1", ac=14)
def test_the_stored_name_is_generated_by_the_server(organiser_client, upload_dir):
    created = create_event_request(organiser_client)

    url = _upload(organiser_client, created["id"], name="../../evil name.png").json()[
        "cover_image_url"
    ]

    assert "evil" not in url
    assert ".." not in url
    (saved,) = _files_in(upload_dir)
    assert saved.name == url.rsplit("/", 1)[1]
    assert saved.resolve().is_relative_to(upload_dir.resolve())


@pytest.mark.story("2.1", ac=14)
def test_a_path_outside_the_upload_folder_is_not_served(organiser_client):
    assert organiser_client.get("/uploads/events/..%2F..%2Fpyproject.toml").status_code == 404
    assert organiser_client.get("/uploads/events/missing.png").status_code == 404


@pytest.mark.story("2.1", ac=14)
def test_a_new_request_has_no_picture(organiser_client):
    assert create_event_request(organiser_client)["cover_image_url"] is None


# --- AC14: the size and type limits -------------------------------------------------------------
@pytest.mark.story("2.1", ac=14)
def test_a_picture_of_exactly_5_mb_is_accepted(organiser_client):
    created = create_event_request(organiser_client)

    response = _upload(organiser_client, created["id"], _padded(_PNG, MAX_BYTES))

    assert response.status_code == 200, response.text


@pytest.mark.story("2.1", ac=14)
def test_a_picture_one_byte_over_5_mb_is_refused(organiser_client, db: Session, upload_dir):
    created = create_event_request(organiser_client)

    response = _upload(organiser_client, created["id"], _padded(_PNG, MAX_BYTES + 1))

    assert response.status_code == 413
    assert _stored_url(db, created["id"]) is None
    assert _files_in(upload_dir) == []


@pytest.mark.story("2.1", ac=14)
def test_an_empty_file_is_refused(organiser_client):
    created = create_event_request(organiser_client)

    assert _upload(organiser_client, created["id"], b"").status_code == 422


@pytest.mark.story("2.1", ac=14)
@pytest.mark.parametrize(
    ("content", "name", "mime"),
    [
        pytest.param(_GIF, "anim.gif", "image/gif", id="gif"),
        pytest.param(_SVG, "logo.svg", "image/svg+xml", id="svg"),
        pytest.param(_PDF, "brief.pdf", "application/pdf", id="pdf"),
        pytest.param(b"just some text", "notes.png", "image/png", id="text-named-png"),
    ],
)
def test_only_jpeg_png_and_webp_are_accepted(
    organiser_client, db: Session, upload_dir, content, name, mime
):
    created = create_event_request(organiser_client)

    response = _upload(organiser_client, created["id"], content, name, mime)

    assert response.status_code == 422
    assert "jpeg" in response.text.lower()
    assert _stored_url(db, created["id"]) is None
    assert _files_in(upload_dir) == []


@pytest.mark.story("2.1", ac=14)
def test_the_bytes_decide_the_type_not_the_file_name(organiser_client):
    created = create_event_request(organiser_client)

    response = _upload(
        organiser_client, created["id"], _PNG, "cover.exe", "application/octet-stream"
    )

    assert response.status_code == 200
    assert response.json()["cover_image_url"].endswith(".png")


@pytest.mark.story("2.1", ac=14)
def test_a_missing_file_part_is_refused(organiser_client):
    created = create_event_request(organiser_client)

    response = organiser_client.put(COVER_IMAGE_PATH.format(event_id=created["id"]))

    assert response.status_code == 422


# --- AC14: replacing and removing ---------------------------------------------------------------
@pytest.mark.story("2.1", ac=14)
def test_a_new_picture_replaces_the_old_one_and_deletes_its_file(organiser_client, upload_dir):
    created = create_event_request(organiser_client)
    first = _upload(organiser_client, created["id"], _PNG).json()["cover_image_url"]

    second = _upload(organiser_client, created["id"], _JPEG, "b.jpg", "image/jpeg").json()[
        "cover_image_url"
    ]

    assert first != second
    assert organiser_client.get(first).status_code == 404
    assert organiser_client.get(second).status_code == 200
    assert len(_files_in(upload_dir)) == 1


@pytest.mark.story("2.1", ac=14)
def test_a_refused_replacement_keeps_the_old_picture(organiser_client, db: Session):
    created = create_event_request(organiser_client)
    first = _upload(organiser_client, created["id"], _PNG).json()["cover_image_url"]

    assert _upload(organiser_client, created["id"], _GIF, "a.gif", "image/gif").status_code == 422

    assert _stored_url(db, created["id"]) == first
    assert organiser_client.get(first).status_code == 200


@pytest.mark.story("2.1", ac=14)
def test_removing_the_picture_clears_it_and_deletes_the_file(
    organiser_client, db: Session, upload_dir
):
    created = create_event_request(organiser_client)
    url = _upload(organiser_client, created["id"]).json()["cover_image_url"]

    response = _remove(organiser_client, created["id"])

    assert response.status_code == 200, response.text
    assert response.json()["cover_image_url"] is None
    assert _stored_url(db, created["id"]) is None
    assert organiser_client.get(url).status_code == 404
    assert _files_in(upload_dir) == []


@pytest.mark.story("2.1", ac=14)
def test_removing_when_there_is_no_picture_is_harmless(organiser_client):
    created = create_event_request(organiser_client)

    response = _remove(organiser_client, created["id"])

    assert response.status_code == 200
    assert response.json()["cover_image_url"] is None


@pytest.mark.story("2.1", ac=14)
def test_a_picture_is_not_needed_to_submit(organiser_client):
    created = create_submittable_event_request(organiser_client)

    assert organiser_client.post(f"/events/{created['id']}/submit").status_code == 200


@pytest.mark.story("2.1", ac=14)
def test_a_picture_can_be_added_by_a_regular_edit_of_a_draft_without_touching_it(
    organiser_client,
):
    created = create_event_request(organiser_client)
    url = _upload(organiser_client, created["id"]).json()["cover_image_url"]

    response = organiser_client.patch(f"/events/{created['id']}", json={"name": "Renamed"})

    assert response.json()["cover_image_url"] == url


@pytest.mark.story("2.1", ac=14)
def test_the_picture_cannot_be_set_through_the_details_body(organiser_client):
    """The server owns the path: a client cannot point a request at any URL it likes."""
    created = create_event_request(organiser_client)

    response = organiser_client.patch(
        f"/events/{created['id']}", json={"cover_image_url": "https://evil.example/x.png"}
    )

    assert response.status_code == 422


# --- AC14: once submitted ----------------------------------------------------------------------
@pytest.mark.story("2.1", ac=14)
def test_a_submitted_request_refuses_a_new_picture(organiser_client, db: Session, upload_dir):
    created = create_submittable_event_request(organiser_client)
    assert organiser_client.post(f"/events/{created['id']}/submit").status_code == 200

    response = _upload(organiser_client, created["id"])

    assert response.status_code == 409
    assert _stored_url(db, created["id"]) is None
    assert _files_in(upload_dir) == []


@pytest.mark.story("2.1", ac=14)
def test_a_submitted_request_refuses_removing_its_picture(organiser_client, db: Session):
    created = create_submittable_event_request(organiser_client)
    url = _upload(organiser_client, created["id"]).json()["cover_image_url"]
    assert organiser_client.post(f"/events/{created['id']}/submit").status_code == 200

    response = _remove(organiser_client, created["id"])

    assert response.status_code == 409
    assert _stored_url(db, created["id"]) == url
    assert organiser_client.get(url).status_code == 200


# --- AC14: who can change it, who can see it ---------------------------------------------------
@pytest.mark.story("2.1", ac=14)
@pytest.mark.parametrize("user", NON_ORGANISERS)
def test_only_an_organiser_can_change_a_picture(login_as, db: Session, user):
    created = create_event_request(login_as(Users.ORGANISER))

    assert _upload(login_as(user), created["id"]).status_code == 403
    assert _remove(login_as(user), created["id"]).status_code == 403
    assert _stored_url(db, created["id"]) is None


@pytest.mark.story("2.1", ac=14)
def test_changing_a_picture_requires_sign_in(client, login_as):
    created = create_event_request(login_as(Users.ORGANISER))
    client.logout()

    assert _upload(client, created["id"]).status_code == 401
    assert _remove(client, created["id"]).status_code == 401


@pytest.mark.story("2.1", ac=14)
def test_an_organiser_cannot_change_the_picture_of_someone_elses_request(
    login_as, db: Session, upload_dir
):
    created = create_event_request(login_as(Users.ORGANISER))
    url = _upload(login_as(Users.ORGANISER), created["id"]).json()["cover_image_url"]
    intruder = login_as(Users.ORGANISER_2)

    assert _upload(intruder, created["id"], _JPEG, "b.jpg", "image/jpeg").status_code == 404
    assert _remove(intruder, created["id"]).status_code == 404

    assert _stored_url(db, created["id"]) == url
    assert len(_files_in(upload_dir)) == 1


@pytest.mark.story("2.1", ac=14)
def test_an_unknown_request_is_not_found(organiser_client):
    assert _upload(organiser_client, "00000000-0000-0000-0000-000000000000").status_code == 404


@pytest.mark.story("2.1", ac=14)
def test_the_picture_shows_in_the_list_the_queue_and_the_details(login_as):
    organiser = login_as(Users.ORGANISER)
    created = create_submittable_event_request(organiser)
    url = _upload(organiser, created["id"]).json()["cover_image_url"]
    assert organiser.post(f"/events/{created['id']}/submit").status_code == 200

    mine = next(
        row for row in organiser.get("/events/mine").json()["items"] if row["id"] == created["id"]
    )
    coordinator = login_as(Users.COORDINATOR)
    queued = next(
        row for row in coordinator.get("/events/review-queue").json() if row["id"] == created["id"]
    )
    detail = coordinator.get(f"/events/{created['id']}").json()

    assert mine["cover_image_url"] == queued["cover_image_url"] == url
    assert detail["cover_image_url"] == url


@pytest.mark.story("2.1", ac=14)
def test_a_seeded_picture_is_left_alone_by_the_upload_rules(organiser_client):
    """Seeded events point at committed pictures under the frontend, not the upload folder."""
    detail = organiser_client.get(f"/events/{Events.DRAFT}").json()

    assert detail["cover_image_url"] is None or not detail["cover_image_url"].startswith(
        "/uploads/"
    )
