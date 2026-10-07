"""Story 8.3 - fe/be: create and update venue records - its pictures (AC5-AC10, bug f8.3.2,
raised at the Sprint 1 review).

AC5  Venue Staff can add pictures to a venue while creating or editing it, by choosing files or
     dragging them onto the form, remove any of them, and arrange their order by dragging them or
     moving them earlier or later. New pictures are previewed, and are saved with the venue's
     details in the order shown.
AC6  The venue's record shows its pictures as a gallery, in their order; the first also fills the
     record's banner and shows on the venue's catalogue card. Selecting a picture opens a pop-up
     carousel that steps through the venue's pictures. A venue without pictures shows a
     placeholder.
AC7  Each picture is a JPEG, PNG or WebP of at most 5 MB, judged by its content, and a venue holds
     at most 10. The form checks each chosen picture on its own: it keeps those that pass and
     names each one it refuses, with the reason, before anything is sent. The server refuses them
     too.
AC8  If the details save but a picture is refused, the venue and its accepted pictures are kept,
     and the venue's edit page says why. Editing the details leaves the pictures as they are. Each
     picture's file is stored and served only under a name the server generates, and lasts exactly
     as long as the picture: removing the picture or deleting the venue deletes it, a refused
     deletion keeps it, and a picture that fails to save leaves none.
AC9  Only Venue Staff can add, remove or reorder pictures (as AC4).
AC10 Pictures added to one venue at the same moment are all kept, each in its own place in the
     order, and never more than 10. A venue deleted while its form is open refuses new pictures
     with "Venue not found." and keeps no file. An order that does not list exactly the venue's
     current pictures is refused, and the pictures keep their order.

Choosing, previewing, dragging and arranging pictures, the browser's own checks, the carousel, and
the form keeping a new venue whose picture was refused are e2e cases: tests/e2e/venues.spec.ts.
Files are written to a per-test temporary folder, never to the real upload folder.
"""

from __future__ import annotations

import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.common.audit import AuditLog
from app.config import settings
from app.venues import service
from app.venues.models import Venue
from tests.support.factories import venue_payload
from tests.support.seed import Users, Venues

MAX_BYTES = 5 * 1024 * 1024
MAX_PICTURES = 10
TOO_MANY_MESSAGE = "A venue can have at most 10 pictures."
CHANGED_MESSAGE = (
    "The venue's pictures have changed since this page was opened. Reload the page and arrange "
    "them again."
)
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"\x00" * 32
_GIF = b"GIF89a" + b"\x00" * 32
_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
_PDF = b"%PDF-1.4\n" + b"\x00" * 32
NOT_VENUE_STAFF = [
    pytest.param(Users.COORDINATOR, id="coordinator"),
    pytest.param(Users.TECH_SUPPORT, id="tech-support"),
    pytest.param(Users.ORGANISER, id="organiser"),
    pytest.param(Users.ATTENDEE, id="attendee"),
]


@pytest.fixture(autouse=True)
def upload_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    return tmp_path


def _padded(header: bytes, size: int) -> bytes:
    return header + b"\x00" * (size - len(header))


def _images_path(venue_id) -> str:
    return f"/venues/{venue_id}/images"


def _add(client, venue_id, content: bytes = _PNG, name: str = "room.png", mime="image/png"):
    return client.post(_images_path(venue_id), files={"file": (name, content, mime)})


def _add_ok(client, venue_id, content: bytes = _PNG, name: str = "room.png", mime="image/png"):
    """Add a picture that must be accepted, and return it: a new picture always goes last."""
    response = _add(client, venue_id, content, name, mime)
    assert response.status_code == 201, response.text
    return response.json()["images"][-1]


def _remove(client, venue_id, image_id):
    return client.delete(f"{_images_path(venue_id)}/{image_id}")


def _reorder(client, venue_id, image_ids):
    return client.put(
        f"{_images_path(venue_id)}/order", json={"image_ids": [str(i) for i in image_ids]}
    )


def _reorder_audits(db: Session, venue_id) -> list:
    return db.execute(
        text(
            "SELECT actor_id, details FROM audit_log"
            " WHERE entity_id = :id AND action = 'VENUE_IMAGES_REORDERED'"
        ),
        {"id": str(venue_id)},
    ).all()


def _stored_urls(db: Session, venue_id) -> list[str]:
    return list(
        db.execute(
            text("SELECT url FROM venue_images WHERE venue_id = :id ORDER BY position"),
            {"id": str(venue_id)},
        ).scalars()
    )


def _files_in(folder: Path) -> list[Path]:
    return [path for path in folder.rglob("*") if path.is_file()]


def _file_names(folder: Path) -> set[str]:
    return {path.name for path in _files_in(folder)}


def _name_of(url: str) -> str:
    return url.rsplit("/", 1)[1]


def _new_venue(client) -> str:
    response = client.post("/venues", json=venue_payload())
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- AC5: adding and removing --------------------------------------------------------------
@pytest.mark.story("8.3", ac=5)
@pytest.mark.parametrize(
    ("content", "mime", "suffix"),
    [
        pytest.param(_PNG, "image/png", ".png", id="png"),
        pytest.param(_JPEG, "image/jpeg", ".jpg", id="jpeg"),
        pytest.param(_WEBP, "image/webp", ".webp", id="webp"),
    ],
)
def test_a_picture_is_added_and_served(venue_staff_client, db: Session, content, mime, suffix):
    response = _add(venue_staff_client, Venues.BOARDROOM, content, f"photo{suffix}", mime)

    assert response.status_code == 201, response.text
    (image,) = response.json()["images"]
    assert re.fullmatch(rf"/uploads/venues/{_UUID}{re.escape(suffix)}", image["url"])
    assert _stored_urls(db, Venues.BOARDROOM) == [image["url"]]
    served = venue_staff_client.get(image["url"])
    assert served.status_code == 200
    assert served.content == content
    assert served.headers["content-type"] == mime


@pytest.mark.story("8.3", ac=5)
def test_removing_a_picture_deletes_its_file_and_keeps_the_rest(
    venue_staff_client, db: Session, upload_dir
):
    first, second, third = (_add_ok(venue_staff_client, Venues.BOARDROOM) for _ in range(3))

    response = _remove(venue_staff_client, Venues.BOARDROOM, second["id"])

    assert response.status_code == 200, response.text
    kept = [first["url"], third["url"]]
    assert [image["url"] for image in response.json()["images"]] == kept
    assert _stored_urls(db, Venues.BOARDROOM) == kept
    assert venue_staff_client.get(second["url"]).status_code == 404
    assert _file_names(upload_dir) == {_name_of(url) for url in kept}


@pytest.mark.story("8.3", ac=5)
def test_adding_and_removing_pictures_are_audited(venue_staff_client, db: Session):
    image = _add_ok(venue_staff_client, Venues.BOARDROOM)
    assert _remove(venue_staff_client, Venues.BOARDROOM, image["id"]).status_code == 200

    rows = db.execute(
        text(
            "SELECT action, actor_id, entity_type, details FROM audit_log"
            " WHERE entity_id = :id AND action LIKE 'VENUE_IMAGE_%'"
        ),
        {"id": str(Venues.BOARDROOM)},
    ).all()

    assert sorted(row.action for row in rows) == ["VENUE_IMAGE_ADDED", "VENUE_IMAGE_REMOVED"]
    for row in rows:
        assert row.actor_id == Users.VENUE_STAFF.id
        assert row.entity_type == "venue"
        assert row.details == {"image_id": image["id"], "url": image["url"]}


@pytest.mark.story("8.3", ac=5)
def test_another_venues_picture_cannot_be_removed_through_this_one(venue_staff_client, db: Session):
    image = _add_ok(venue_staff_client, Venues.BOARDROOM)

    response = _remove(venue_staff_client, Venues.SEMINAR_ROOM, image["id"])

    assert response.status_code == 404
    assert response.json()["detail"] == "Picture not found."
    assert _stored_urls(db, Venues.BOARDROOM) == [image["url"]]
    assert venue_staff_client.get(image["url"]).status_code == 200


@pytest.mark.story("8.3", ac=5)
def test_a_picture_already_removed_is_not_found(venue_staff_client):
    image = _add_ok(venue_staff_client, Venues.BOARDROOM)
    assert _remove(venue_staff_client, Venues.BOARDROOM, image["id"]).status_code == 200

    again = _remove(venue_staff_client, Venues.BOARDROOM, image["id"])

    assert again.status_code == 404
    assert again.json()["detail"] == "Picture not found."


# --- AC5: arranging the order --------------------------------------------------------------
@pytest.mark.story("8.3", ac=5)
def test_pictures_can_be_put_in_a_new_order(venue_staff_client, db: Session):
    first, second, third = (_add_ok(venue_staff_client, Venues.BOARDROOM) for _ in range(3))

    response = _reorder(
        venue_staff_client, Venues.BOARDROOM, [third["id"], first["id"], second["id"]]
    )

    assert response.status_code == 200, response.text
    assert response.json()["images"] == [third, first, second]
    assert response.json()["cover_image_url"] == third["url"]
    assert _stored_urls(db, Venues.BOARDROOM) == [third["url"], first["url"], second["url"]]
    # A picture added afterwards still goes last.
    added = _add_ok(venue_staff_client, Venues.BOARDROOM)
    assert _stored_urls(db, Venues.BOARDROOM)[-1] == added["url"]


@pytest.mark.story("8.3", ac=5)
def test_reordering_is_audited(venue_staff_client, db: Session):
    first, second = (_add_ok(venue_staff_client, Venues.BOARDROOM) for _ in range(2))

    assert _reorder(venue_staff_client, Venues.BOARDROOM, [second["id"], first["id"]]).is_success

    (row,) = _reorder_audits(db, Venues.BOARDROOM)
    assert row.actor_id == Users.VENUE_STAFF.id
    assert row.details == {
        "from": [first["id"], second["id"]],
        "to": [second["id"], first["id"]],
    }


@pytest.mark.story("8.3", ac=5)
def test_the_same_order_changes_nothing(venue_staff_client, db: Session):
    first, second = (_add_ok(venue_staff_client, Venues.BOARDROOM) for _ in range(2))

    response = _reorder(venue_staff_client, Venues.BOARDROOM, [first["id"], second["id"]])

    assert response.status_code == 200, response.text
    assert _stored_urls(db, Venues.BOARDROOM) == [first["url"], second["url"]]
    assert _reorder_audits(db, Venues.BOARDROOM) == []


# --- AC6: the gallery and its cover ----------------------------------------------------------
@pytest.mark.story("8.3", ac=6)
def test_pictures_keep_their_order_and_the_first_is_the_cover(login_as):
    staff = login_as(Users.VENUE_STAFF)
    added = [
        _add_ok(staff, Venues.BOARDROOM, _PNG, "a.png", "image/png")["url"],
        _add_ok(staff, Venues.BOARDROOM, _JPEG, "b.jpg", "image/jpeg")["url"],
        _add_ok(staff, Venues.BOARDROOM, _WEBP, "c.webp", "image/webp")["url"],
    ]

    coordinator = login_as(Users.COORDINATOR)
    record = coordinator.get(f"/venues/{Venues.BOARDROOM}").json()
    listed = next(
        venue for venue in coordinator.get("/venues").json() if venue["id"] == str(Venues.BOARDROOM)
    )
    found = next(
        venue
        for venue in coordinator.get("/venues/search", params={"search": "Boardroom"}).json()[
            "venues"
        ]
        if venue["id"] == str(Venues.BOARDROOM)
    )

    assert [image["url"] for image in record["images"]] == added
    assert record["cover_image_url"] == added[0]
    assert listed["cover_image_url"] == added[0]
    assert found["cover_image_url"] == added[0]


@pytest.mark.story("8.3", ac=6)
def test_removing_the_cover_makes_the_next_picture_the_cover(venue_staff_client):
    first = _add_ok(venue_staff_client, Venues.BOARDROOM)
    second = _add_ok(venue_staff_client, Venues.BOARDROOM)

    response = _remove(venue_staff_client, Venues.BOARDROOM, first["id"])

    assert response.status_code == 200, response.text
    assert response.json()["cover_image_url"] == second["url"]


@pytest.mark.story("8.3", ac=6)
def test_a_new_venue_has_no_pictures(venue_staff_client):
    response = venue_staff_client.post("/venues", json=venue_payload())

    assert response.status_code == 201, response.text
    assert response.json()["images"] == []
    assert response.json()["cover_image_url"] is None


@pytest.mark.story("8.3", ac=6)
def test_pictures_are_served_without_signing_in(venue_staff_client):
    url = _add_ok(venue_staff_client, Venues.BOARDROOM)["url"]
    venue_staff_client.logout()

    assert venue_staff_client.get(url).status_code == 200


# --- AC7: the size, type and number limits ---------------------------------------------------
@pytest.mark.story("8.3", ac=7)
def test_a_picture_of_exactly_5_mb_is_accepted(venue_staff_client):
    response = _add(venue_staff_client, Venues.BOARDROOM, _padded(_PNG, MAX_BYTES))

    assert response.status_code == 201, response.text


@pytest.mark.story("8.3", ac=7)
def test_a_picture_one_byte_over_5_mb_is_refused(venue_staff_client, db: Session, upload_dir):
    response = _add(venue_staff_client, Venues.BOARDROOM, _padded(_PNG, MAX_BYTES + 1))

    assert response.status_code == 413
    assert response.json()["detail"] == "The picture must be 5 MB or smaller."
    assert _stored_urls(db, Venues.BOARDROOM) == []
    assert _files_in(upload_dir) == []


@pytest.mark.story("8.3", ac=7)
def test_an_empty_file_is_refused(venue_staff_client, db: Session):
    response = _add(venue_staff_client, Venues.BOARDROOM, b"")

    assert response.status_code == 422
    assert _stored_urls(db, Venues.BOARDROOM) == []


@pytest.mark.story("8.3", ac=7)
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
    venue_staff_client, db: Session, upload_dir, content, name, mime
):
    response = _add(venue_staff_client, Venues.BOARDROOM, content, name, mime)

    assert response.status_code == 422
    assert response.json()["detail"] == "Choose a JPEG, PNG or WebP picture."
    assert _stored_urls(db, Venues.BOARDROOM) == []
    assert _files_in(upload_dir) == []


@pytest.mark.story("8.3", ac=7)
def test_the_bytes_decide_the_type_not_the_file_name(venue_staff_client):
    image = _add_ok(
        venue_staff_client, Venues.BOARDROOM, _PNG, "cover.exe", "application/octet-stream"
    )

    assert image["url"].endswith(".png")


@pytest.mark.story("8.3", ac=7)
def test_a_missing_file_part_is_refused(venue_staff_client):
    response = venue_staff_client.post(_images_path(Venues.BOARDROOM))

    assert response.status_code == 422


@pytest.mark.story("8.3", ac=7)
def test_the_tenth_picture_is_accepted_and_the_eleventh_refused(
    venue_staff_client, db: Session, upload_dir
):
    for _ in range(MAX_PICTURES - 1):
        _add_ok(venue_staff_client, Venues.BOARDROOM)

    tenth = _add(venue_staff_client, Venues.BOARDROOM)
    eleventh = _add(venue_staff_client, Venues.BOARDROOM)

    assert tenth.status_code == 201, tenth.text
    assert eleventh.status_code == 409
    assert eleventh.json()["detail"] == TOO_MANY_MESSAGE
    assert len(_stored_urls(db, Venues.BOARDROOM)) == MAX_PICTURES
    assert len(_files_in(upload_dir)) == MAX_PICTURES


@pytest.mark.story("8.3", ac=7)
def test_removing_a_picture_makes_room_for_another(venue_staff_client):
    images = [_add_ok(venue_staff_client, Venues.BOARDROOM) for _ in range(MAX_PICTURES)]
    assert _remove(venue_staff_client, Venues.BOARDROOM, images[3]["id"]).status_code == 200

    response = _add(venue_staff_client, Venues.BOARDROOM)

    assert response.status_code == 201, response.text
    urls = [image["url"] for image in response.json()["images"]]
    assert len(urls) == MAX_PICTURES
    assert urls[:-1] == [image["url"] for image in images if image is not images[3]]
    assert urls[-1] not in {image["url"] for image in images}


# --- AC8: names, files and the details ------------------------------------------------------
@pytest.mark.story("8.3", ac=8)
def test_the_stored_name_is_generated_by_the_server(venue_staff_client, upload_dir):
    url = _add_ok(venue_staff_client, Venues.BOARDROOM, name="../../evil name.png")["url"]

    assert "evil" not in url
    assert ".." not in url
    (saved,) = _files_in(upload_dir)
    assert saved.name == _name_of(url)
    assert saved.resolve().is_relative_to(upload_dir.resolve())


@pytest.mark.story("8.3", ac=8)
def test_only_names_the_server_generated_are_served(venue_staff_client, upload_dir):
    url = _add_ok(venue_staff_client, Venues.BOARDROOM)["url"]
    assert venue_staff_client.get(url).is_success
    # Two files the server never named: one beside the venues folder, one inside it.
    (upload_dir / "outside.png").write_bytes(_PNG)
    (upload_dir / "venues" / "planted.png").write_bytes(_PNG)

    # A backslash (%5C) separates folders on Windows, so without the name rule the first would
    # serve outside.png; the last is a generated name with no file behind it.
    for name in ("..%5Coutside.png", "planted.png", f"{uuid.uuid4()}.png"):
        response = venue_staff_client.get(f"/uploads/venues/{name}")
        assert response.status_code == 404, name
        assert response.json()["detail"] == "Picture not found."
    # A name holding a slash never reaches the endpoint: routing refuses it first.
    assert venue_staff_client.get("/uploads/venues/..%2F..%2Fpyproject.toml").status_code == 404


@pytest.mark.story("8.3", ac=8)
def test_a_refused_picture_leaves_the_others_alone(venue_staff_client, db: Session):
    first = _add_ok(venue_staff_client, Venues.BOARDROOM)

    refused = _add(venue_staff_client, Venues.BOARDROOM, _GIF, "a.gif", "image/gif")

    assert refused.status_code == 422
    assert _stored_urls(db, Venues.BOARDROOM) == [first["url"]]
    assert venue_staff_client.get(first["url"]).status_code == 200


@pytest.mark.story("8.3", ac=8)
def test_editing_the_details_keeps_the_pictures(venue_staff_client):
    images = [_add_ok(venue_staff_client, Venues.BOARDROOM) for _ in range(2)]

    response = venue_staff_client.patch(
        f"/venues/{Venues.BOARDROOM}", json={"description": "Refitted boardroom."}
    )

    assert response.status_code == 200, response.text
    assert response.json()["images"] == images
    assert response.json()["cover_image_url"] == images[0]["url"]


@pytest.mark.story("8.3", ac=8)
def test_pictures_cannot_be_set_through_the_details(venue_staff_client, db: Session):
    """The server owns the addresses: a client cannot point a venue at any URL it likes."""
    elsewhere = "https://evil.example/x.png"

    by_list = venue_staff_client.patch(
        f"/venues/{Venues.BOARDROOM}",
        json={"images": [{"id": str(uuid.uuid4()), "url": elsewhere}]},
    )
    by_cover = venue_staff_client.patch(
        f"/venues/{Venues.BOARDROOM}", json={"cover_image_url": elsewhere}
    )
    created = venue_staff_client.post(
        "/venues",
        json=venue_payload(cover_image_url=elsewhere, images=[{"url": elsewhere}]),
    )

    assert by_list.status_code == 422
    assert by_cover.status_code == 422
    assert _stored_urls(db, Venues.BOARDROOM) == []
    assert created.status_code == 201, created.text
    assert created.json()["images"] == []
    assert created.json()["cover_image_url"] is None


@pytest.mark.story("8.3", ac=8)
def test_deleting_a_venue_deletes_its_picture_files(venue_staff_client, db: Session, upload_dir):
    venue_id = _new_venue(venue_staff_client)
    urls = [_add_ok(venue_staff_client, venue_id)["url"] for _ in range(2)]
    assert len(_files_in(upload_dir)) == 2

    response = venue_staff_client.delete(f"/venues/{venue_id}")

    assert response.status_code == 204, response.text
    assert _files_in(upload_dir) == []
    assert _stored_urls(db, venue_id) == []
    for url in urls:
        assert venue_staff_client.get(url).status_code == 404


@pytest.mark.story("8.3", ac=8)
def test_a_venue_whose_deletion_is_refused_keeps_its_picture_files(
    venue_staff_client, db: Session, upload_dir
):
    """The Grand Hall has a booking, so deleting it is refused, and its pictures still load."""
    url = _add_ok(venue_staff_client, Venues.GRAND_HALL)["url"]

    response = venue_staff_client.delete(f"/venues/{Venues.GRAND_HALL}")

    assert response.status_code == 409, response.text
    assert _stored_urls(db, Venues.GRAND_HALL) == [url]
    assert _file_names(upload_dir) == {_name_of(url)}
    assert venue_staff_client.get(url).status_code == 200


class _SaveFailed(RuntimeError):
    """A failure after a picture's file is written and before its row is saved."""


@pytest.mark.story("8.3", ac=8)
def test_a_picture_that_fails_to_save_leaves_no_file(
    venue_staff_client, db: Session, upload_dir, monkeypatch
):
    def fail_to_record(*_args, **_kwargs):
        raise _SaveFailed

    monkeypatch.setattr(service, "record_audit", fail_to_record)

    with pytest.raises(_SaveFailed):
        _add(venue_staff_client, Venues.BOARDROOM)
    # The request's session is rolled back when it closes; here the test shares that session.
    db.rollback()

    assert _stored_urls(db, Venues.BOARDROOM) == []
    assert _files_in(upload_dir) == []


@pytest.mark.story("8.3", ac=8)
def test_a_file_that_cannot_be_deleted_does_not_fail_a_change_that_worked(
    venue_staff_client, db: Session, monkeypatch
):
    """The rows are committed before the files are deleted, so a delete that fails (a file locked
    on Windows, say) must not turn a saved change into an error."""
    image = _add_ok(venue_staff_client, Venues.BOARDROOM)
    venue_id = _new_venue(venue_staff_client)
    _add_ok(venue_staff_client, venue_id)

    def refuse_to_delete(self, missing_ok=False):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", refuse_to_delete)

    removed = _remove(venue_staff_client, Venues.BOARDROOM, image["id"])
    deleted = venue_staff_client.delete(f"/venues/{venue_id}")

    assert removed.status_code == 200, removed.text
    assert removed.json()["images"] == []
    assert _stored_urls(db, Venues.BOARDROOM) == []
    assert deleted.status_code == 204, deleted.text


# --- AC9: who can change them ---------------------------------------------------------------
@pytest.mark.story("8.3", ac=9)
@pytest.mark.parametrize("user", NOT_VENUE_STAFF)
def test_only_venue_staff_can_add_remove_or_reorder_pictures(
    login_as, db: Session, upload_dir, user
):
    staff = login_as(Users.VENUE_STAFF)
    first, second = (_add_ok(staff, Venues.BOARDROOM) for _ in range(2))
    other = login_as(user)

    assert _add(other, Venues.BOARDROOM).status_code == 403
    assert _remove(other, Venues.BOARDROOM, first["id"]).status_code == 403
    assert _reorder(other, Venues.BOARDROOM, [second["id"], first["id"]]).status_code == 403
    assert _stored_urls(db, Venues.BOARDROOM) == [first["url"], second["url"]]
    assert _file_names(upload_dir) == {_name_of(first["url"]), _name_of(second["url"])}


@pytest.mark.story("8.3", ac=9)
def test_changing_pictures_requires_sign_in(venue_staff_client, db: Session):
    first, second = (_add_ok(venue_staff_client, Venues.BOARDROOM) for _ in range(2))
    venue_staff_client.logout()

    assert _add(venue_staff_client, Venues.BOARDROOM).status_code == 401
    assert _remove(venue_staff_client, Venues.BOARDROOM, first["id"]).status_code == 401
    assert (
        _reorder(venue_staff_client, Venues.BOARDROOM, [second["id"], first["id"]]).status_code
        == 401
    )
    assert _stored_urls(db, Venues.BOARDROOM) == [first["url"], second["url"]]


# --- AC10: at the same moment, and a venue that is gone --------------------------------------
def _committed_venue(engine) -> uuid.UUID:
    with Session(engine) as session:
        venue = Venue(
            name=f"Concurrent pictures {uuid.uuid4()}",
            location="Test Tower",
            capacity=10,
            created_by_id=Users.VENUE_STAFF.id,
        )
        session.add(venue)
        session.commit()
        return venue.id


def _drop_committed_venue(engine, venue_id: uuid.UUID) -> None:
    with Session(engine) as session:
        session.execute(delete(AuditLog).where(AuditLog.entity_id == venue_id))
        session.execute(delete(Venue).where(Venue.id == venue_id))
        session.commit()


def _add_at_once(engine, venue_id: uuid.UUID, attempts: int) -> list[str]:
    """``attempts`` pictures added to the venue at the same moment, each in its own transaction."""
    start = threading.Barrier(attempts)

    def attempt() -> str:
        with Session(engine) as session:
            actor = session.get(User, Users.VENUE_STAFF.id)
            start.wait()
            try:
                service.add_venue_image(session, venue_id, _PNG, actor=actor)
            except service.TooManyVenueImages:
                return "refused"
            return "added"

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        results = [pool.submit(attempt) for _ in range(attempts)]
        return sorted(future.result(timeout=30) for future in results)


def _positions(engine, venue_id: uuid.UUID) -> list[int]:
    with Session(engine) as session:
        return list(
            session.execute(
                text("SELECT position FROM venue_images WHERE venue_id = :id ORDER BY position"),
                {"id": str(venue_id)},
            ).scalars()
        )


@pytest.mark.story("8.3", ac=10)
def test_pictures_added_at_the_same_moment_are_all_kept(engine, upload_dir):
    """Real concurrent transactions, so this test commits and cleans up after itself."""
    venue_id = _committed_venue(engine)
    attempts = 4
    try:
        outcomes = _add_at_once(engine, venue_id, attempts)

        assert outcomes == ["added"] * attempts
        assert _positions(engine, venue_id) == [1, 2, 3, 4]
        assert len(_files_in(upload_dir)) == attempts
    finally:
        _drop_committed_venue(engine, venue_id)


@pytest.mark.story("8.3", ac=10)
def test_pictures_added_at_the_same_moment_never_pass_the_limit(engine, upload_dir):
    """Real concurrent transactions, so this test commits and cleans up after itself."""
    venue_id = _committed_venue(engine)
    try:
        with Session(engine) as session:
            actor = session.get(User, Users.VENUE_STAFF.id)
            for _ in range(MAX_PICTURES - 1):
                service.add_venue_image(session, venue_id, _PNG, actor=actor)

        outcomes = _add_at_once(engine, venue_id, 2)

        assert outcomes == ["added", "refused"]
        assert _positions(engine, venue_id) == list(range(1, MAX_PICTURES + 1))
        assert len(_files_in(upload_dir)) == MAX_PICTURES
    finally:
        _drop_committed_venue(engine, venue_id)


@pytest.mark.story("8.3", ac=10)
def test_a_venue_that_no_longer_exists_takes_no_pictures(venue_staff_client, upload_dir):
    venue_id = _new_venue(venue_staff_client)
    assert venue_staff_client.delete(f"/venues/{venue_id}").status_code == 204

    for missing in (venue_id, str(uuid.uuid4())):
        added = _add(venue_staff_client, missing)
        removed = _remove(venue_staff_client, missing, uuid.uuid4())
        reordered = _reorder(venue_staff_client, missing, [])

        assert added.status_code == 404
        assert added.json()["detail"] == "Venue not found."
        assert removed.status_code == 404
        assert reordered.status_code == 404
    assert _files_in(upload_dir) == []


@pytest.mark.story("8.3", ac=10)
@pytest.mark.parametrize("change", ["one-missing", "one-unknown", "another-venues"])
def test_an_order_that_is_not_the_venues_pictures_is_refused(
    venue_staff_client, db: Session, change
):
    """The form sends the order last; if a picture was added or removed elsewhere since the form
    was opened, its list no longer matches, and nothing is reordered."""
    first, second = (_add_ok(venue_staff_client, Venues.BOARDROOM) for _ in range(2))
    elsewhere = _add_ok(venue_staff_client, Venues.SEMINAR_ROOM)
    orders = {
        "one-missing": [second["id"]],
        "one-unknown": [second["id"], first["id"], str(uuid.uuid4())],
        "another-venues": [second["id"], first["id"], elsewhere["id"]],
    }

    response = _reorder(venue_staff_client, Venues.BOARDROOM, orders[change])

    assert response.status_code == 409
    assert response.json()["detail"] == CHANGED_MESSAGE
    assert _stored_urls(db, Venues.BOARDROOM) == [first["url"], second["url"]]
    assert _reorder_audits(db, Venues.BOARDROOM) == []


@pytest.mark.story("8.3", ac=10)
def test_an_order_naming_a_picture_twice_is_refused(venue_staff_client, db: Session):
    first, second = (_add_ok(venue_staff_client, Venues.BOARDROOM) for _ in range(2))

    response = _reorder(
        venue_staff_client, Venues.BOARDROOM, [second["id"], first["id"], second["id"]]
    )

    assert response.status_code == 422
    assert _stored_urls(db, Venues.BOARDROOM) == [first["url"], second["url"]]
