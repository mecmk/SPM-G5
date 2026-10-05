-- =====================================================================
-- Migration 013 - a venue's pictures.
--
-- Bug f8.3.2 (story 8.3 AC5-AC10, raised at the Sprint 1 review): Venue Staff add pictures to a
-- venue on its create and edit form, by choosing files or dragging them on, and remove them. A
-- venue holds at most 10 (MAX_VENUE_IMAGES in backend/app/venues/service.py), kept in the order
-- they were added. The first is shown on the venue's catalogue card and in its record's banner,
-- and the record shows them all.
--
-- The files live under UPLOAD_DIR/venues/ (backend/app/config.py) and the API serves them at
-- /uploads/venues/<name>; a row holds that address. Positions only grow: a new picture goes after
-- the last one, and removing one leaves a gap rather than renumbering the rest.
-- =====================================================================

CREATE TABLE venue_images (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue_id      UUID NOT NULL REFERENCES venues (id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    position      INTEGER NOT NULL,
    created_by_id UUID REFERENCES users (id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_venue_images_position UNIQUE (venue_id, position),
    CONSTRAINT uq_venue_images_url UNIQUE (url),
    CONSTRAINT ck_venue_images_position_positive CHECK (position > 0)
);
COMMENT ON TABLE venue_images IS
    'Stories: 8.3 (AC5-AC10, bug f8.3.2), 8.1, 8.2. The pictures of a venue, at most 10, in the order they were added. The first is the venue''s cover on its catalogue card and record banner. Deleting a venue deletes its rows; the service deletes the files.';
COMMENT ON COLUMN venue_images.venue_id IS 'FK -> venues.id.';
COMMENT ON COLUMN venue_images.url IS 'Root-relative address the API serves the picture from: /uploads/venues/<name>, a name the server generated (a UUID and the extension of the format its bytes were read as).';
COMMENT ON COLUMN venue_images.position IS 'Place in the venue''s order, from 1. A new picture goes after the highest; removing one leaves a gap. Lowest = the cover (story 8.3 AC6).';
COMMENT ON COLUMN venue_images.created_by_id IS 'FK -> users.id. Venue Staff member who added the picture.';
COMMENT ON COLUMN venue_images.created_at IS 'When the picture was added.';
