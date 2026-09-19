"""Generate docs/database/DATA_DICTIONARY.md and docs/database/ERD.excalidraw from the live DB.

The single source of truth for the data dictionary is the schema itself: table and column
COMMENTs in backend/db/migrations/*.sql. This module reads the PostgreSQL catalog and writes
both documents, so they can never drift from what is actually deployed. Run it via
``npm run db:docs`` after any schema change (``npm run db:ready`` does it automatically when a
migration is applied).

Layout hints for the ERD (which tables sit in which column, header colours) live in ``GROUPS``
below. A table that is not listed still appears - in an "Other" group - so nothing is ever
silently missing from the diagram.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.dbtool.connection import connect

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = REPO_ROOT / "docs" / "database"
DICTIONARY_PATH = DOCS_DIR / "DATA_DICTIONARY.md"
ERD_PATH = DOCS_DIR / "ERD.excalidraw"

# (group title, header colour, [tables in display order])
GROUPS: list[tuple[str, str, list[str]]] = [
    ("Identity & access", "#a5d8ff", ["roles", "users", "user_sessions", "client_organisations"]),
    (
        "Reference lists",
        "#e9ecef",
        ["facilities", "room_layouts", "accessibility_features", "equipment_types"],
    ),
    (
        "Venues",
        "#b2f2bb",
        [
            "venues",
            "venue_facilities",
            "venue_layouts",
            "venue_accessibility_features",
            "venue_unavailability_periods",
        ],
    ),
    ("Events", "#ffec99", ["events"]),
    (
        "Event details & history",
        "#fff3bf",
        [
            "event_required_facilities",
            "event_accessibility_needs",
            "event_equipment_requests",
            "event_status_history",
            "event_coordinator_assignments",
            "event_clarifications",
            "event_change_requests",
        ],
    ),
    ("Venue bookings", "#ffc9c9", ["venue_bookings"]),
    ("Equipment", "#d0bfff", ["equipment_reservations", "equipment_unavailability_periods"]),
    ("Registration", "#ffd8a8", ["event_registrations"]),
    ("Notifications & audit", "#eebefa", ["notifications", "audit_log"]),
    ("Infrastructure", "#dee2e6", ["schema_migrations"]),
]

# Reference tables whose seeded rows are listed in the dictionary: table -> columns to show
REFERENCE_TABLES: dict[str, list[str]] = {
    "roles": ["code", "name", "is_internal", "description"],
    "facilities": ["code", "name", "description"],
    "room_layouts": ["code", "name", "description"],
    "accessibility_features": ["code", "name", "description"],
    "equipment_types": ["code", "name", "total_quantity", "storage_location"],
}


# ---------------------------------------------------------------------------
# Catalog reading
# ---------------------------------------------------------------------------
@dataclass
class Column:
    name: str
    type: str
    not_null: bool
    default: str | None
    description: str | None
    generated: bool
    is_pk: bool = False
    fk_target: str | None = None  # "table.column"


@dataclass
class Constraint:
    name: str
    kind: str  # p, u, f, c, x
    definition: str


@dataclass
class Table:
    name: str
    description: str | None
    columns: list[Column] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    indexes: list[tuple[str, str]] = field(default_factory=list)

    # "Stories: 1.1, 1.2. Rest of the description." -> the story list ends at the first
    # full stop that is followed by whitespace and the start of a sentence.
    _STORIES = re.compile(r"^\s*Stories?:\s*(.+?)\.(?:\s+(?=[A-Z\"'(])|\s*$)")

    @property
    def stories(self) -> str | None:
        match = self._STORIES.match(self.description or "")
        return match.group(1).strip() if match else None

    @property
    def description_body(self) -> str:
        return self._STORIES.sub("", self.description or "").strip()

    @property
    def foreign_keys(self) -> list[tuple[str, str, str]]:
        """(local column, referenced table, referenced column) for every single-column FK."""
        out = []
        for c in self.constraints:
            if c.kind != "f":
                continue
            m = re.match(r"FOREIGN KEY \((\w+)\) REFERENCES (\w+)\((\w+)\)", c.definition)
            if m:
                out.append((m.group(1), m.group(2), m.group(3)))
        return out

    def allowed_values(self) -> dict[str, list[str]]:
        """column -> allowed values, parsed from single-column ``CHECK (col IN (...))``."""
        result: dict[str, list[str]] = {}
        for c in self.constraints:
            if c.kind != "c":
                continue
            m = re.match(r"CHECK \(\(?(\w+) = ANY \(ARRAY\[(.*?)\]\)\)?\)", c.definition)
            if m:
                values = re.findall(r"'([^']*)'::text", m.group(2))
                result[m.group(1)] = values
        return result


def read_catalog(url: str) -> list[Table]:
    tables: list[Table] = []
    with connect(url) as conn:
        rows = conn.execute(
            """
            SELECT c.relname, obj_description(c.oid, 'pg_class')
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r' AND n.nspname = 'public'
            ORDER BY c.relname
            """
        ).fetchall()
        for relname, description in rows:
            table = Table(name=relname, description=description)
            for name, type_, notnull, default, col_desc, generated in conn.execute(
                """
                SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                       pg_get_expr(d.adbin, d.adrelid), col_description(a.attrelid, a.attnum),
                       a.attgenerated <> ''
                FROM pg_attribute a
                LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY a.attnum
                """,
                (f"public.{relname}",),
            ):
                table.columns.append(
                    Column(name, type_, notnull, default, col_desc, bool(generated))
                )
            for cname, ctype, cdef in conn.execute(
                """
                SELECT conname, contype, pg_get_constraintdef(oid)
                FROM pg_constraint WHERE conrelid = %s::regclass
                ORDER BY contype, conname
                """,
                (f"public.{relname}",),
            ):
                table.constraints.append(Constraint(cname, ctype, cdef))
            for iname, idef in conn.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = %s ORDER BY indexname",
                (relname,),
            ):
                table.indexes.append((iname, idef))
            tables.append(table)

    # decorate PK / FK flags on columns
    for table in tables:
        for c in table.constraints:
            if c.kind == "p":
                for col in re.findall(r"\((.*?)\)", c.definition)[0].split(", "):
                    _column(table, col).is_pk = True
        for local, ref_table, ref_col in table.foreign_keys:
            _column(table, local).fk_target = f"{ref_table}.{ref_col}"
    return tables


def _column(table: Table, name: str) -> Column:
    return next(c for c in table.columns if c.name == name)


def read_reference_rows(url: str) -> dict[str, list[tuple]]:
    out: dict[str, list[tuple]] = {}
    with connect(url) as conn:
        for table, cols in REFERENCE_TABLES.items():
            exists = conn.execute(
                "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=%s", (table,)
            ).fetchone()
            if not exists:
                continue
            order = "sort_order, code" if "facilit" in table or "layout" in table else "code"
            if table == "accessibility_features":
                order = "sort_order, code"
            out[table] = conn.execute(
                f"SELECT {', '.join(cols)} FROM {table} ORDER BY {order}"  # noqa: S608 - trusted
            ).fetchall()
    return out


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------
def grouped(tables: list[Table]) -> list[tuple[str, str, list[Table]]]:
    by_name = {t.name: t for t in tables}
    seen: set[str] = set()
    result: list[tuple[str, str, list[Table]]] = []
    for title, colour, names in GROUPS:
        members = [by_name[n] for n in names if n in by_name]
        seen.update(t.name for t in members)
        if members:
            result.append((title, colour, members))
    leftovers = [t for t in tables if t.name not in seen]
    if leftovers:
        result.append(("Other (add to GROUPS in app/dbtool/docs.py)", "#ffffff", leftovers))
    return result


# ---------------------------------------------------------------------------
# Data dictionary (Markdown)
# ---------------------------------------------------------------------------
def _md_escape(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def render_dictionary(tables: list[Table], reference_rows: dict[str, list[tuple]]) -> str:
    groups = grouped(tables)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d")
    lines: list[str] = []
    w = lines.append
    w("# ConnectSphere Data Dictionary")
    w("")
    w(
        f"_Generated from the live PostgreSQL catalog on {generated_at} by "
        "`npm run db:docs`. **Do not edit by hand** - change the `COMMENT ON` statements in "
        "`backend/db/migrations/*.sql` and regenerate._"
    )
    w("")
    w("Companion diagram: [ERD.excalidraw](ERD.excalidraw) (open at <https://excalidraw.com>")
    w(
        "or with the VS Code Excalidraw extension). Design notes and workflow: "
        "[README.md](README.md)."
    )
    w("")
    w("## Conventions")
    w("")
    w("- **Primary keys** are UUIDs generated by the database, except reference tables keyed by a")
    w("  stable `code` and the infrastructure table `schema_migrations`.")
    w("- **Status / kind columns** are `text` with a named `CHECK` constraint; the allowed values")
    w(
        "  are listed under each table. Add or rename a value with a migration that replaces "
        "the constraint."
    )
    w(
        "- **`created_at` / `updated_at`** are `timestamptz`; `updated_at` is maintained by a "
        "trigger."
    )
    w("- **Periods** are half-open: `starts_at` inclusive, `ends_at` exclusive, so back-to-back")
    w("  bookings that touch at a boundary do not conflict (story 14.1 AC3).")
    w("- **Stories** listed against a table are backlog IDs from the SPM Product Backlog.")
    w("")
    w("## Tables at a glance")
    w("")
    w("| Domain | Table | Stories | Purpose |")
    w("| --- | --- | --- | --- |")
    for title, _, members in groups:
        for t in members:
            summary = t.description_body.split(". ")[0].rstrip(".")
            w(
                f"| {title} | [`{t.name}`](#{t.name}) | {_md_escape(t.stories) or '-'} | "
                f"{_md_escape(summary) or '-'} |"
            )
    w("")

    for title, _, members in groups:
        w(f"## {title}")
        w("")
        for t in members:
            w(f"### {t.name}")
            w("")
            if t.stories:
                w(f"**Stories:** {t.stories}")
                w("")
            if t.description_body:
                w(t.description_body)
                w("")
            w("| Column | Type | Null | Default | Key | Description |")
            w("| --- | --- | --- | --- | --- | --- |")
            for c in t.columns:
                key = " ".join(
                    k
                    for k in (
                        "PK" if c.is_pk else "",
                        f"FK → `{c.fk_target}`" if c.fk_target else "",
                    )
                    if k
                )
                default = "generated" if c.generated else (c.default or "")
                default = default.replace("::text", "").replace("::character varying", "")
                w(
                    f"| `{c.name}` | `{c.type}` | {'no' if c.not_null else 'yes'} | "
                    f"{('`' + _md_escape(default) + '`') if default else '-'} | {key or '-'} | "
                    f"{_md_escape(c.description) or '-'} |"
                )
            w("")
            allowed = t.allowed_values()
            if allowed:
                w("Allowed values:")
                w("")
                for col, values in allowed.items():
                    w(f"- `{col}`: " + ", ".join(f"`{v}`" for v in values))
                w("")
            extra = [c for c in t.constraints if c.kind in ("u", "x")] + [
                c for c in t.constraints if c.kind == "c" and c.name not in _allowed_names(t)
            ]
            uniq_idx = [
                (n, d) for n, d in t.indexes if "UNIQUE" in d and not _is_constraint_index(t, n)
            ]
            other_idx = [
                (n, d) for n, d in t.indexes if "UNIQUE" not in d and not _is_constraint_index(t, n)
            ]
            if extra or uniq_idx or other_idx:
                w("Rules and indexes:")
                w("")
                for c in extra:
                    label = {"u": "unique", "x": "exclusion", "c": "check"}[c.kind]
                    w(f"- {label} `{c.name}`: `{_md_escape(c.definition)}`")
                for n, d in uniq_idx:
                    w(f"- unique index `{n}`: `{_md_escape(d.split(' USING ', 1)[1])}`")
                for n, d in other_idx:
                    w(f"- index `{n}`: `{_md_escape(d.split(' USING ', 1)[1])}`")
                w("")

    if reference_rows:
        w("## Seeded reference values")
        w("")
        w("Loaded by `backend/db/seed/010_reference_data.sql`. Edit that file to add values.")
        w("")
        for table, rows in reference_rows.items():
            cols = REFERENCE_TABLES[table]
            w(f"### {table} values")
            w("")
            w("| " + " | ".join(cols) + " |")
            w("| " + " | ".join("---" for _ in cols) + " |")
            for row in rows:
                w(
                    "| "
                    + " | ".join(_md_escape(str(v)) if v is not None else "-" for v in row)
                    + " |"
                )
            w("")
    return "\n".join(lines).rstrip() + "\n"


def _allowed_names(t: Table) -> set[str]:
    names = set()
    for c in t.constraints:
        if c.kind == "c" and re.match(r"CHECK \(\(?(\w+) = ANY \(ARRAY\[", c.definition):
            names.add(c.name)
    return names


def _is_constraint_index(t: Table, index_name: str) -> bool:
    return any(c.name == index_name for c in t.constraints)


# ---------------------------------------------------------------------------
# ERD (Excalidraw JSON)
# ---------------------------------------------------------------------------
_BOX_WIDTH = 400
_HEADER_HEIGHT = 34
_FONT_SIZE = 13
_LINE_HEIGHT = 1.2
_PADDING = 8
_COLUMN_GAP = 140
_ROW_GAP = 60
_MAX_COLUMN_HEIGHT = 1700

_TYPE_ABBREVIATIONS = {
    "timestamp with time zone": "timestamptz",
    "time without time zone": "time",
    "character varying": "varchar",
    "integer": "int",
    "boolean": "bool",
    "citext": "citext",
}


class _Ids:
    def __init__(self) -> None:
        self._rng = random.Random(20260910)  # deterministic -> stable diffs

    def new(self, prefix: str) -> str:
        return f"{prefix}-{self._rng.getrandbits(48):012x}"

    def seed(self) -> int:
        return self._rng.getrandbits(31)


def _abbrev_type(t: str) -> str:
    return _TYPE_ABBREVIATIONS.get(t, t)


def _column_line(c: Column) -> str:
    flag = "PK" if c.is_pk else ("FK" if c.fk_target else "  ")
    null = "" if c.not_null or c.is_pk else "?"
    return f"{flag}  {c.name + null:<30} {_abbrev_type(c.type)}"


def _base(ids: _Ids, **overrides) -> dict:
    element = {
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": ids.seed(),
        "version": 1,
        "versionNonce": ids.seed(),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }
    element.update(overrides)
    return element


def _text(
    ids: _Ids, *, x, y, width, height, text, size, family, align, valign, container=None, **kw
):
    return _base(
        ids,
        id=ids.new("text"),
        type="text",
        x=x,
        y=y,
        width=width,
        height=height,
        text=text,
        originalText=text,
        fontSize=size,
        fontFamily=family,
        textAlign=align,
        verticalAlign=valign,
        containerId=container,
        autoResize=True,
        lineHeight=_LINE_HEIGHT if family == 3 else 1.25,
        **kw,
    )


def render_erd(tables: list[Table]) -> dict:
    ids = _Ids()
    elements: list[dict] = []
    boxes: dict[str, dict] = {}  # table -> {"x","y","w","h","body_id"}

    # --- title & legend -----------------------------------------------------------------
    elements.append(
        _text(
            ids,
            x=0,
            y=-150,
            width=900,
            height=40,
            text="ConnectSphere - Entity Relationship Diagram (generated by `npm run db:docs`)",
            size=28,
            family=2,
            align="left",
            valign="top",
        )
    )
    elements.append(
        _text(
            ids,
            x=0,
            y=-100,
            width=900,
            height=60,
            text=(
                "PK = primary key   FK = foreign key   ? = nullable   crow's foot = many side\n"
                "Move boxes freely - arrows stay attached. Colours = domain. "
                "Source of truth: backend/db/migrations/*.sql"
            ),
            size=14,
            family=2,
            align="left",
            valign="top",
        )
    )

    # --- table boxes, laid out in columns per group -----------------------------------------
    x, y = 0, 0
    for title, colour, members in grouped(tables):
        heights = [
            _HEADER_HEIGHT + int(len(t.columns) * _FONT_SIZE * _LINE_HEIGHT + 2 * _PADDING)
            for t in members
        ]
        group_height = sum(heights) + _ROW_GAP * len(members)
        # Small groups share a column with the previous one; otherwise start a new column.
        if y > 0 and y + 60 + group_height > _MAX_COLUMN_HEIGHT:
            x += _BOX_WIDTH + _COLUMN_GAP
            y = 0
        if y > 0:
            y += 60  # room for the group label
        column_top_label(ids, elements, title, x, y - 40)
        for t in members:
            body_lines = [_column_line(c) for c in t.columns]
            body_height = int(len(body_lines) * _FONT_SIZE * _LINE_HEIGHT + 2 * _PADDING)
            if y > 0 and y + _HEADER_HEIGHT + body_height > _MAX_COLUMN_HEIGHT:
                x += _BOX_WIDTH + _COLUMN_GAP
                y = 0
                column_top_label(ids, elements, f"{title} (cont.)", x, y - 40)
            group_id = ids.new("grp")
            header_id, body_id = ids.new("hdr"), ids.new("body")
            header = _base(
                ids,
                id=header_id,
                type="rectangle",
                x=x,
                y=y,
                width=_BOX_WIDTH,
                height=_HEADER_HEIGHT,
                backgroundColor=colour,
                groupIds=[group_id],
                strokeWidth=2,
            )
            header_text = _text(
                ids,
                x=x + _PADDING,
                y=y + 6,
                width=_BOX_WIDTH - 2 * _PADDING,
                height=_HEADER_HEIGHT - 12,
                text=t.name,
                size=16,
                family=2,
                align="center",
                valign="middle",
                container=header_id,
                groupIds=[group_id],
            )
            header["boundElements"].append({"id": header_text["id"], "type": "text"})
            body = _base(
                ids,
                id=body_id,
                type="rectangle",
                x=x,
                y=y + _HEADER_HEIGHT,
                width=_BOX_WIDTH,
                height=body_height,
                backgroundColor="#ffffff",
                groupIds=[group_id],
                strokeWidth=2,
            )
            body_text = _text(
                ids,
                x=x + _PADDING,
                y=y + _HEADER_HEIGHT + _PADDING,
                width=_BOX_WIDTH - 2 * _PADDING,
                height=body_height - 2 * _PADDING,
                text="\n".join(body_lines),
                size=_FONT_SIZE,
                family=3,
                align="left",
                valign="top",
                container=body_id,
                groupIds=[group_id],
            )
            body["boundElements"].append({"id": body_text["id"], "type": "text"})
            elements.extend([header, header_text, body, body_text])
            boxes[t.name] = {
                "x": x,
                "y": y,
                "w": _BOX_WIDTH,
                "h": _HEADER_HEIGHT + body_height,
                "body": body,
                "header": header,
            }
            y += _HEADER_HEIGHT + body_height + _ROW_GAP

    # --- relationship arrows ---------------------------------------------------------------
    pair_count: dict[tuple[str, str], int] = {}
    for t in tables:
        for local_col, ref_table, _ref_col in t.foreign_keys:
            if ref_table not in boxes or t.name not in boxes:
                continue
            key = (t.name, ref_table)
            offset = pair_count.get(key, 0)
            pair_count[key] = offset + 1
            _add_arrow(ids, elements, boxes, t.name, ref_table, local_col, offset)

    return {
        "type": "excalidraw",
        "version": 2,
        "source": "connectsphere:app.dbtool.docs",
        "elements": elements,
        "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
        "files": {},
    }


def column_top_label(ids: _Ids, elements: list[dict], title: str, x: int, y: int) -> None:
    elements.append(
        _text(
            ids,
            x=x,
            y=y,
            width=_BOX_WIDTH,
            height=28,
            text=title.upper(),
            size=18,
            family=2,
            align="left",
            valign="top",
            strokeColor="#495057",
        )
    )


def _add_arrow(ids, elements, boxes, child, parent, label, offset) -> None:
    c, p = boxes[child], boxes[parent]
    shift = 18 * offset
    if p["x"] >= c["x"] + c["w"]:  # parent to the right
        start = (c["x"] + c["w"], c["y"] + min(60 + shift, c["h"] - 10))
        end = (p["x"], p["y"] + min(60 + shift, p["h"] - 10))
    elif p["x"] + p["w"] <= c["x"]:  # parent to the left
        start = (c["x"], c["y"] + min(60 + shift, c["h"] - 10))
        end = (p["x"] + p["w"], p["y"] + min(60 + shift, p["h"] - 10))
    elif p["y"] > c["y"]:  # same column, parent below
        start = (c["x"] + c["w"] / 2 + shift, c["y"] + c["h"])
        end = (p["x"] + p["w"] / 2 + shift, p["y"])
    else:  # same column, parent above
        start = (c["x"] + c["w"] / 2 + shift, c["y"])
        end = (p["x"] + p["w"] / 2 + shift, p["y"] + p["h"])
    arrow_id = ids.new("arrow")
    dx, dy = end[0] - start[0], end[1] - start[1]
    arrow = _base(
        ids,
        id=arrow_id,
        type="arrow",
        x=start[0],
        y=start[1],
        width=abs(dx),
        height=abs(dy),
        points=[[0, 0], [dx, dy]],
        lastCommittedPoint=None,
        startBinding={"elementId": c["body"]["id"], "focus": 0, "gap": 2, "fixedPoint": None},
        endBinding={"elementId": p["body"]["id"], "focus": 0, "gap": 2, "fixedPoint": None},
        startArrowhead="crowfoot_many",
        endArrowhead="crowfoot_one",
        elbowed=False,
        roundness={"type": 2},
        strokeColor="#495057",
    )
    label_el = _text(
        ids,
        x=start[0] + dx / 2 - 60,
        y=start[1] + dy / 2 - 8,
        width=120,
        height=16,
        text=label,
        size=11,
        family=3,
        align="center",
        valign="middle",
        container=arrow_id,
        strokeColor="#495057",
    )
    arrow["boundElements"].append({"id": label_el["id"], "type": "text"})
    c["body"]["boundElements"].append({"id": arrow_id, "type": "arrow"})
    p["body"]["boundElements"].append({"id": arrow_id, "type": "arrow"})
    elements.extend([arrow, label_el])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def generate(url: str, *, log=print) -> tuple[Path, Path]:
    tables = read_catalog(url)
    reference_rows = read_reference_rows(url)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DICTIONARY_PATH.write_text(
        render_dictionary(tables, reference_rows), encoding="utf-8", newline="\n"
    )
    ERD_PATH.write_text(
        json.dumps(render_erd(tables), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    log(f"  wrote {DICTIONARY_PATH.relative_to(REPO_ROOT)} ({len(tables)} tables)")
    log(f"  wrote {ERD_PATH.relative_to(REPO_ROOT)}")
    return DICTIONARY_PATH, ERD_PATH
