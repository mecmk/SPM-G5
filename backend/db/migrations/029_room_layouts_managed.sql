-- =====================================================================
-- Migration 029 - story 8.6: Venue Staff manage the room layouts venues can offer.
--
-- Until now room_layouts was reference data that only the seed changed. From story 8.6 Venue
-- Staff add, rename and delete layouts in the app, so the table holds its own rules:
-- 1. uq_room_layouts_name: no two layouts share a name, ignoring capitals (AC6). Two saves of
--    one name at the same moment are settled here, so only one is saved (AC10).
-- 2. ck_room_layouts_name: a name has no spaces around it, is not empty, and has at most 100
--    characters (AC5).
-- 3. description NOT NULL, and ck_room_layouts_description: a description is required, has no
--    spaces around it, is not empty, and has at most 500 characters (AC7). Every standard layout
--    the seed adds has one.
-- 4. deleted_room_layouts: each layout Venue Staff delete, by its code and the name it had (AC4).
--    No layout takes one of these codes again (AC2), so nothing that kept a deleted layout's code
--    is taken for another layout, and a venue saved with one is told which layout went (AC11).
-- A layout in use cannot be deleted (AC8): the foreign keys from venue_layouts,
-- venue_requirements and venue_bookings (migrations 001 and 012) already refuse it.
-- =====================================================================

CREATE UNIQUE INDEX uq_room_layouts_name ON room_layouts (lower(name));

ALTER TABLE room_layouts
    ALTER COLUMN description SET NOT NULL,
    ADD CONSTRAINT ck_room_layouts_name
        CHECK (name = btrim(name) AND name <> '' AND char_length(name) <= 100),
    ADD CONSTRAINT ck_room_layouts_description
        CHECK (description = btrim(description) AND description <> ''
               AND char_length(description) <= 500);

COMMENT ON TABLE room_layouts IS
    'Stories: 2.1, 8.2, 8.3, 8.6, 12.1. Room layouts (theatre, classroom, boardroom, banquet, exhibition, ...) that a venue supports and an event may require. Venue Staff add, rename and delete them in the app (story 8.6); the seed only adds the standard ones that are missing and were never deleted. A layout a venue, venue requirement or booking request uses cannot be deleted (AC8).';
COMMENT ON COLUMN room_layouts.code IS
    'Stable identifier, e.g. THEATRE. Made from the name when a layout is added in the app (story 8.6 AC2), with a number added when that code is taken or was a deleted layout''s (THEATRE_2, THEATRE_3, ...), and never changed by a rename, so every reference to the layout keeps working.';
COMMENT ON COLUMN room_layouts.name IS
    'Display name, shown wherever the layout appears (story 8.6 AC3). Required, without spaces around it, at most 100 characters (AC5, ck_room_layouts_name), and unique ignoring capitals (AC6, uq_room_layouts_name).';
COMMENT ON COLUMN room_layouts.description IS
    'Longer description, shown with the name on the Room layouts page. Required, without spaces around it, at most 500 characters (story 8.6 AC7, ck_room_layouts_description); never blank.';
COMMENT ON COLUMN room_layouts.sort_order IS
    'Display ordering in pick-lists (ascending): the standard layouts carry 10 to 70, and a layout added in the app the default 100, so it follows them from A to Z (story 8.6 AC1).';

CREATE TABLE deleted_room_layouts (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

COMMENT ON TABLE deleted_room_layouts IS
    'Stories: 8.6. The room layouts Venue Staff deleted (AC4), one row each, written in the same transaction as the delete. A deleted layout''s code is never given to another layout, by the app (AC2) or the seed, so a pending change request, a saved catalogue link or an audit entry that kept the code is never taken for a different layout; and a venue saved with a deleted layout is told it no longer exists, by name (AC11), while a code no layout ever had is refused as unknown.';
COMMENT ON COLUMN deleted_room_layouts.code IS
    'The deleted layout''s code, as it was in room_layouts.code. Primary key: a code is deleted at most once, as it never comes back.';
COMMENT ON COLUMN deleted_room_layouts.name IS
    'The name the layout had when it was deleted, so a refusal can name it (story 8.6 AC11).';
