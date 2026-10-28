-- =====================================================================
-- Migration 028 - story 8.6: Venue Staff manage the room layouts venues can offer.
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
    'Stories: 2.1, 8.2, 8.3, 8.6, 12.1. Room layouts (theatre, classroom, boardroom, banquet, exhibition, ...) that a venue supports and an event may require. Venue Staff add, rename and delete them in the app (story 8.6); the seed only adds the standard ones where they are missing. A layout a venue, venue requirement or booking request uses cannot be deleted (AC8).';
COMMENT ON COLUMN room_layouts.code IS
    'Stable identifier, e.g. THEATRE. Made from the name when a layout is added in the app (story 8.6 AC2), with a number added when that code is taken (THEATRE_2, THEATRE_3, ...), and never changed by a rename, so every reference to the layout keeps working.';
COMMENT ON COLUMN room_layouts.name IS
    'Display name, shown wherever the layout appears (story 8.6 AC3). Required, without spaces around it, at most 100 characters (AC5, ck_room_layouts_name), and unique ignoring capitals (AC6, uq_room_layouts_name).';
COMMENT ON COLUMN room_layouts.description IS
    'Longer description, shown with the name on the Room layouts page. Required, without spaces around it, at most 500 characters (story 8.6 AC7, ck_room_layouts_description); never blank.';
COMMENT ON COLUMN room_layouts.sort_order IS
    'Display ordering in pick-lists (ascending): the standard layouts carry 10 to 70, and a layout added in the app the default 100, so it follows them from A to Z (story 8.6 AC1).';
