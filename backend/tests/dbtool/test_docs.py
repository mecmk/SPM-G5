"""Story 1 - chore: set up database schema. The data dictionary and ERD generated from it.

Level: integration, plus unit tests of the renderers. ``app/dbtool/docs.py`` reads the live
PostgreSQL catalog and writes ``DATA_DICTIONARY.md`` and ``ERD.excalidraw``. The integration tests
read the scratch database built from the real migrations and seed (``conftest.py``) and write to a
temporary folder. The unit tests at the end hand the renderers tables the real schema does not
have - one with no comment, one outside every group, a foreign key to a table not drawn - with no
database.

AC1 Schema covers users, events, venues, bookings, equipment. (Here: every table, column and
    rule is documented, from the comments in the migrations.)
AC2 Foreign key constraints defined. (Here: each one is marked in the dictionary and drawn as an
    arrow in the ERD.)
AC3 Schema can be populated with sample data without integrity errors. (Here: the seeded
    reference values are listed.)
"""

from __future__ import annotations

import json

import pytest

from app.dbtool import docs, migrate
from app.dbtool.__main__ import main

OTHER_GROUP = "Other (add to GROUPS in app/dbtool/docs.py)"


@pytest.fixture(scope="module")
def tables(seeded_template) -> list[docs.Table]:
    return docs.read_catalog(seeded_template)


@pytest.fixture(scope="module")
def dictionary(seeded_template, tables) -> str:
    return docs.render_dictionary(tables, docs.read_reference_rows(seeded_template))


@pytest.fixture(scope="module")
def erd(tables) -> dict:
    return json.loads(json.dumps(docs.render_erd(tables)))


def _section(dictionary: str, table: str) -> str:
    """The part of the dictionary under ``### <table>``, up to the next heading."""
    return dictionary.split(f"\n### {table}\n", 1)[1].split("\n#", 1)[0].strip()


def _row(section: str, column: str) -> str:
    return next(line for line in section.splitlines() if line.startswith(f"| `{column}` |"))


def _table(name: str, *columns: docs.Column, description=None, constraints=()) -> docs.Table:
    return docs.Table(
        name=name, description=description, columns=list(columns), constraints=list(constraints)
    )


def _uuid_column(name: str, *, is_pk: bool = False) -> docs.Column:
    return docs.Column(name, "uuid", True, None, None, False, is_pk=is_pk)


@pytest.mark.story("1", ac=1)
def test_docs_command_writes_the_dictionary_and_the_erd(seeded_url, docs_dir, capsys):
    """`npm run db:docs` writes both documents into docs/database and says how many tables."""
    assert main(["--url", seeded_url, "docs"]) == 0

    tables = len(migrate.table_row_counts(seeded_url))
    printed = capsys.readouterr().out
    assert f"DATA_DICTIONARY.md ({tables} tables)" in printed
    assert "ERD.excalidraw" in printed
    dictionary = (docs_dir / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
    assert dictionary.startswith("# ConnectSphere Data Dictionary\n")
    erd = json.loads((docs_dir / "ERD.excalidraw").read_text(encoding="utf-8"))
    assert erd["type"] == "excalidraw"


@pytest.mark.story("1", ac=1)
def test_the_dictionary_lists_every_table_with_a_section_of_its_own(tables, dictionary):
    """Each table has a row in "Tables at a glance" and a section with a row per column."""
    assert {"users", "events", "venues", "venue_bookings", "equipment_types"} <= {
        t.name for t in tables
    }
    for table in tables:
        assert f"[`{table.name}`](#{table.name})" in dictionary
        section = _section(dictionary, table.name)
        assert all(f"| `{c.name}` | `{c.type}` |" in section for c in table.columns)


@pytest.mark.story("1", ac=1)
def test_each_column_row_carries_its_comment_from_the_migrations(dictionary):
    """The column comments written in schema_migrations' DDL come through word for word."""
    section = _section(dictionary, "schema_migrations")

    assert section.startswith("Infrastructure. One row per migration file applied by app.dbtool")
    assert _row(section, "version") == (
        "| `version` | `text` | no | - | PK | Numeric prefix of the migration file, e.g. 001. |"
    )
    assert _row(section, "applied_at") == (
        "| `applied_at` | `timestamp with time zone` | no | `now()` | - | When it was applied. |"
    )


@pytest.mark.story("1", ac=2)
def test_a_foreign_key_column_names_the_column_it_references(dictionary):
    assert "FK → `roles.code`" in _row(_section(dictionary, "users"), "role_code")
    assert "FK → `users.id`" in _row(_section(dictionary, "events"), "organiser_id")


@pytest.mark.story("1", ac=1)
def test_a_status_column_lists_its_allowed_values(tables, dictionary):
    """A ``CHECK (status IN (...))`` becomes the list of statuses under its table."""
    statuses = next(t for t in tables if t.name == "events").allowed_values()["status"]

    assert {"DRAFT", "PLANNING", "CONFIRMED", "CANCELLED"} <= set(statuses)
    assert "- `status`: " + ", ".join(f"`{s}`" for s in statuses) in _section(dictionary, "events")


@pytest.mark.story("1", ac=1)
def test_the_rules_and_indexes_of_a_table_are_listed(dictionary):
    """Unique, exclusion and other check constraints, and indexes, appear under their table."""
    rules = _section(dictionary, "venue_bookings").split("Rules and indexes:", 1)[1]

    assert "- exclusion `ex_venue_bookings_no_double_booking`" in rules
    for label in ("- unique `", "- check `", "- unique index `", "- index `"):
        assert label in dictionary


@pytest.mark.story("1", ac=3)
def test_the_seeded_reference_values_are_listed(seeded_template, dictionary):
    """Each pick-list the seed loads is printed, one row per value."""
    reference = docs.read_reference_rows(seeded_template)
    listed = dictionary.split("## Seeded reference values", 1)[1]

    assert set(reference) == set(docs.REFERENCE_TABLES)
    for table, rows in reference.items():
        assert f"### {table} values" in listed
        assert rows
    assert "| ATTENDEE | Attendee | False |" in listed


@pytest.mark.story("1", ac=1)
@pytest.mark.story("1", ac=2)
def test_the_erd_draws_a_box_per_table_and_an_arrow_per_foreign_key(tables, erd):
    """Every table gets a box, and every single-column foreign key an arrow from the child's
    box to the parent's, labelled with the column."""
    headers = {e["text"] for e in erd["elements"] if e["type"] == "text" and e["fontSize"] == 16}
    assert headers == {t.name for t in tables}

    bodies = {e["id"] for e in erd["elements"] if e["id"].startswith("body-")}
    arrows = [e for e in erd["elements"] if e["type"] == "arrow"]
    assert len(arrows) == sum(len(t.foreign_keys) for t in tables)
    assert all(a["startBinding"]["elementId"] in bodies for a in arrows)
    assert all(a["endBinding"]["elementId"] in bodies for a in arrows)
    labels = {
        e["text"] for e in erd["elements"] if (e.get("containerId") or "").startswith("arrow-")
    }
    assert {"role_code", "organiser_id"} <= labels


@pytest.mark.story("1", ac=2)
def test_the_erd_is_the_same_every_time_it_is_generated(tables):
    """Ids and seeds come from a fixed random seed, so regenerating an unchanged schema leaves
    ERD.excalidraw with no diff."""
    assert docs.render_erd(tables) == docs.render_erd(tables)


@pytest.mark.story("1")
def test_docs_on_a_database_with_no_tables_writes_empty_documents(empty_url, docs_dir, capsys):
    """Before any migration there is nothing to document: no table rows, no reference values,
    and an ERD holding only its title and legend."""
    assert main(["--url", empty_url, "docs"]) == 0

    assert "(0 tables)" in capsys.readouterr().out
    dictionary = (docs_dir / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
    assert dictionary.rstrip().endswith("| --- | --- | --- | --- |")
    assert "Seeded reference values" not in dictionary
    erd = json.loads((docs_dir / "ERD.excalidraw").read_text(encoding="utf-8"))
    assert [e["type"] for e in erd["elements"]] == ["text", "text"]


@pytest.mark.story("1", ac=1)
@pytest.mark.parametrize(
    ("description", "stories", "body"),
    [
        ("Stories: 1.1, 8.3. Venues people can book.", "1.1, 8.3", "Venues people can book."),
        ("Stories: 12.7.", "12.7", ""),
        ("Venues people can book.", None, "Venues people can book."),
        (None, None, ""),
    ],
    ids=["stories-and-text", "stories-only", "text-only", "no-comment"],
)
def test_a_table_comment_is_split_into_its_stories_and_its_description(description, stories, body):
    """The "Stories: ..." prefix of a COMMENT ON TABLE fills the Stories column; the rest is the
    paragraph under the table's heading."""
    table = _table("venues", description=description)

    assert table.stories == stories
    assert table.description_body == body


@pytest.mark.story("1", ac=1)
def test_a_table_with_no_comment_and_no_group_is_still_documented():
    """A table no one has added to GROUPS, and with no COMMENT ON, still gets its row and its
    section, under "Other", so nothing is silently missing."""
    probe = _table("zz_probe", _uuid_column("id", is_pk=True))

    dictionary = docs.render_dictionary([probe], {})

    assert f"| {OTHER_GROUP} | [`zz_probe`](#zz_probe) | - | - |" in dictionary
    assert f"## {OTHER_GROUP}\n\n### zz_probe\n\n| Column |" in dictionary
    assert "| `id` | `uuid` | no | - | PK | - |" in dictionary


@pytest.mark.story("1", ac=2)
def test_a_foreign_key_to_a_table_outside_the_diagram_draws_no_arrow():
    """An arrow needs a box at both ends, so a reference to a table not drawn is left out."""
    child = _table(
        "zz_child",
        _uuid_column("id", is_pk=True),
        _uuid_column("parent_id"),
        constraints=[
            docs.Constraint(
                "zz_child_parent_id_fkey", "f", "FOREIGN KEY (parent_id) REFERENCES zz_parent(id)"
            )
        ],
    )

    erd = docs.render_erd([child])

    assert child.foreign_keys == [("parent_id", "zz_parent", "id")]
    assert not [e for e in erd["elements"] if e["type"] == "arrow"]
