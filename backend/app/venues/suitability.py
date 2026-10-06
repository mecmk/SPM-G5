"""Story 11.1: whether one venue suits one venue requirement, and every criterion it fails.

Pure on purpose: no database, no framework, no event or booking rows - only the plain values
below. The catalogue search and the booking request will both build these values from their own
records and call ``judge_suitability``, so the two can never judge a venue differently.

A requirement is one venue an event needs (story 2.7): the people it must hold, a layout, the
facilities with optional quantities, and the accessibility needs. An event with "No venue
requirements" is judged on its people alone (AC5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class Criterion(StrEnum):
    """What a failure is about. FACILITY is the facility itself (offered or not);
    FACILITY_QUANTITY is how many of an offered facility the venue has."""

    CAPACITY = "CAPACITY"
    LAYOUT = "LAYOUT"
    FACILITY = "FACILITY"
    FACILITY_QUANTITY = "FACILITY_QUANTITY"
    ACCESSIBILITY = "ACCESSIBILITY"


class Outcome(StrEnum):
    """AC5: UNKNOWN when the venue has not recorded what the criterion needs. Either outcome
    makes the venue unsuitable - an unknown is never treated as met."""

    NOT_MET = "NOT_MET"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RequiredItem:
    """A layout or accessibility feature a requirement asks for, by reference-table code."""

    code: str
    name: str


@dataclass(frozen=True)
class RequiredFacility:
    """A facility a requirement asks for. ``quantity`` None = any number will do."""

    code: str
    name: str
    quantity: int | None


@dataclass(frozen=True)
class RequirementNeeds:
    """One venue requirement, as plain values. Only ``people`` for an event with "No venue
    requirements" (AC5), which has no requirement to name, so ``name`` is None."""

    name: str | None
    people: int
    layout: RequiredItem | None = None
    facilities: tuple[RequiredFacility, ...] = ()
    accessibility: tuple[RequiredItem, ...] = ()


@dataclass(frozen=True)
class VenueCharacteristics:
    """A venue's recorded characteristics, as plain values. An empty mapping or set means the
    venue recorded nothing of that kind, which judges as Unknown, not as absent.

    ``layouts`` maps a layout code to that layout's own capacity (None = the venue's maximum);
    ``facilities`` maps a facility code to how many the venue has (None = not recorded).
    """

    capacity: int
    layouts: Mapping[str, int | None]
    facilities: Mapping[str, int | None]
    accessibility: frozenset[str]


@dataclass(frozen=True)
class FailedCriterion:
    """AC1: one criterion the venue fails, with the requirement's value (``required``) and the
    venue's (``venue_value``) where the criterion has numbers. ``code`` and ``name`` say which
    layout, facility or feature; for CAPACITY they name the layout whose capacity was compared,
    or are None when it was the venue's maximum."""

    criterion: Criterion
    outcome: Outcome
    code: str | None
    name: str | None
    required: int | None
    venue_value: int | None


@dataclass(frozen=True)
class Suitability:
    """AC1: the verdict for one requirement against one venue. Suitable exactly when nothing
    failed; ``failures`` lists capacity, layout, facilities, then accessibility."""

    requirement_name: str | None
    failures: tuple[FailedCriterion, ...]

    @property
    def is_suitable(self) -> bool:
        return not self.failures


def _capacity_failure(
    needs: RequirementNeeds, venue: VenueCharacteristics
) -> FailedCriterion | None:
    """AC4: the venue holds the people when its capacity is at least that many. With a layout it
    offers and recorded a capacity for, that capacity is compared; otherwise its maximum."""
    layout = needs.layout
    layout_capacity = None if layout is None else venue.layouts.get(layout.code)
    if layout is None or layout_capacity is None:
        capacity, code, name = venue.capacity, None, None
    else:
        capacity, code, name = layout_capacity, layout.code, layout.name
    if capacity >= needs.people:
        return None
    return FailedCriterion(
        criterion=Criterion.CAPACITY,
        outcome=Outcome.NOT_MET,
        code=code,
        name=name,
        required=needs.people,
        venue_value=capacity,
    )


def _missing_item(
    item: RequiredItem | RequiredFacility,
    recorded: Mapping[str, int | None] | frozenset[str],
    criterion: Criterion,
) -> FailedCriterion | None:
    """AC5: an item the venue's recorded list leaves out is Not met; when the venue recorded
    nothing of that kind at all, it is Unknown."""
    if item.code in recorded:
        return None
    return FailedCriterion(
        criterion=criterion,
        outcome=Outcome.UNKNOWN if len(recorded) == 0 else Outcome.NOT_MET,
        code=item.code,
        name=item.name,
        required=item.quantity if isinstance(item, RequiredFacility) else None,
        venue_value=None,
    )


def _facility_failure(
    facility: RequiredFacility, venue: VenueCharacteristics
) -> FailedCriterion | None:
    """AC4: a required quantity is met by that many or more. AC5: an offered facility whose
    quantity the venue did not record is Unknown when a quantity is required."""
    missing = _missing_item(facility, venue.facilities, Criterion.FACILITY)
    if missing is not None or facility.quantity is None:
        return missing
    has = venue.facilities[facility.code]
    if has is not None and has >= facility.quantity:
        return None
    return FailedCriterion(
        criterion=Criterion.FACILITY_QUANTITY,
        outcome=Outcome.UNKNOWN if has is None else Outcome.NOT_MET,
        code=facility.code,
        name=facility.name,
        required=facility.quantity,
        venue_value=has,
    )


def judge_suitability(needs: RequirementNeeds, venue: VenueCharacteristics) -> Suitability:
    """AC1: Suitable or Unsuitable for one requirement, from that requirement and the venue's
    recorded characteristics only, listing every failed criterion. One requirement at a time,
    so each of an event's requirements is judged on its own - groundwork for AC8, whose
    booking-level part waits for story 12.5."""
    failures = [_capacity_failure(needs, venue)]
    if needs.layout is not None:
        failures.append(_missing_item(needs.layout, venue.layouts, Criterion.LAYOUT))
    failures.extend(_facility_failure(facility, venue) for facility in needs.facilities)
    failures.extend(
        _missing_item(feature, venue.accessibility, Criterion.ACCESSIBILITY)
        for feature in needs.accessibility
    )
    return Suitability(
        requirement_name=needs.name,
        failures=tuple(failure for failure in failures if failure is not None),
    )
