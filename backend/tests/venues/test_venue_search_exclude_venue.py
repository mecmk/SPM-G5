"""Story 12.6 AC1 - the catalogue opened to replace a booking leaves out the unavailable venue.

``GET /venues/search`` takes ``exclude_venue``: a venue the results never hold, whatever else is
filtered - the period included, which the coordinator may edit by hand once the catalogue is open.
It is part of the search's scope, not one of its filters, so the "Try removing" hints of a search
that found nothing never offer to bring that venue back, and never count it.

The page that sends it is tests/e2e/venue-replacement.spec.ts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.support.factories import make_venue


def _pair(db) -> tuple[str, object, object]:
    """Two venues sharing a name prefix no other venue has: a large one and a small one."""
    prefix = f"Replace {uuid.uuid4().hex[:8]}"
    large = make_venue(db, name=f"{prefix} Alpha", capacity=300)
    small = make_venue(db, name=f"{prefix} Beta", capacity=20)
    return prefix, large, small


def _names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [venue["name"] for venue in response.json()["venues"]]


@pytest.mark.story("12.6", ac=1)
def test_search_excludes_the_named_venue(coordinator_client, db):
    prefix, large, small = _pair(db)

    everything = _names(coordinator_client.get("/venues/search", params={"search": prefix}))
    excluded = _names(
        coordinator_client.get(
            "/venues/search", params={"search": prefix, "exclude_venue": str(large.id)}
        )
    )

    assert everything == [large.name, small.name]
    assert excluded == [small.name]


@pytest.mark.story("12.6", ac=1)
def test_the_exclusion_holds_with_a_period_and_with_none(coordinator_client, db):
    """Free for the whole period, the venue would be found - the exclusion is what leaves it out,
    for the period the page opened with, a hand-edited one, and no period at all."""
    prefix, large, small = _pair(db)
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=60)

    for period in (
        {},
        {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=6)).isoformat()},
        {
            "starts_at": (start + timedelta(days=3)).isoformat(),
            "ends_at": (start + timedelta(days=3, hours=2)).isoformat(),
        },
    ):
        names = _names(
            coordinator_client.get(
                "/venues/search",
                params={"search": prefix, "exclude_venue": str(large.id), **period},
            )
        )
        assert names == [small.name], period


@pytest.mark.story("12.6", ac=1)
def test_the_excluded_venue_is_never_offered_back_or_counted_by_the_removal_hints(
    coordinator_client, db
):
    """Only the large venue fits 250 people. Excluded, nothing is found, and removing the capacity
    would find the one other venue - not two, since the excluded one is outside the search."""
    prefix, large, _small = _pair(db)
    params = {"search": prefix, "capacity": 250}

    unexcluded = coordinator_client.get("/venues/search", params=params).json()
    excluded = coordinator_client.get(
        "/venues/search", params={**params, "exclude_venue": str(large.id)}
    ).json()

    assert [venue["name"] for venue in unexcluded["venues"]] == [large.name]
    assert excluded["venues"] == []
    capacity = next(hint for hint in excluded["relax"] if hint["filter"] == "capacity")
    assert capacity["count"] == 1


@pytest.mark.story("12.6", ac=1)
def test_a_malformed_exclude_venue_is_refused(coordinator_client):
    response = coordinator_client.get("/venues/search", params={"exclude_venue": "not-an-id"})

    assert response.status_code == 422
