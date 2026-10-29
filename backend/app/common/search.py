"""The text search and name order shared by Venue Staff's booking queue and Technical Support's
equipment queue (story 13.3).

Each queue names the columns its search reads (AC2) and its orders (AC3); the rules for matching
and for ordering a name are the same in both, so they are written once, here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.sql import ColumnElement

# Story 13.3 AC5: the longest search either queue takes. Keep in step by hand with
# QUEUE_SEARCH_MAX_LENGTH in frontend/src/shared/queueView.ts, which the search box uses.
QUEUE_SEARCH_MAX_LENGTH = 100
# AC3: names compare character by character once lower-cased, whatever the database's own locale,
# so "A to Z" is the same order on every database and a shorter word comes before a longer one.
_NAME_COLLATION = "C"


def search_term(search: str | None) -> str | None:
    """AC5: the text to search for, with the spaces around it ignored; None for no search, so a
    blank or spaces-only one lists the whole tab."""
    term = (search or "").strip()
    return term or None


def matches_any(term: str, *columns: ColumnElement[Any]) -> ColumnElement[bool]:
    """AC2: any of ``columns`` contains ``term``, ignoring capitals. AC6: ``%``, ``_`` and the
    escape character itself are escaped (``autoescape``), so they match only themselves, and the
    term is a bound parameter, never written into the SQL."""
    return or_(*(column.icontains(term, autoescape=True) for column in columns))


def by_name(column: ColumnElement[Any]) -> ColumnElement[Any]:
    """AC3: a name, A to Z ignoring capitals."""
    return func.lower(column).collate(_NAME_COLLATION)
