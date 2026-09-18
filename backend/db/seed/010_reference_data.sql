-- =====================================================================
-- Seed 010 - reference data (roles, facilities, layouts, accessibility
-- features, equipment types).
--
-- Idempotent: every statement is an UPSERT, so `npm run db:ready` can run
-- it on every start. Editing a name here and re-running updates the row;
-- rows you delete here are NOT removed from the database (add a DELETE
-- if you really need that).
-- =====================================================================

INSERT INTO roles (code, name, is_internal, description) VALUES
    ('EVENT_ORGANISER',    'Event Organiser',         FALSE, 'External client representative who has an event to organise and communicates requirements to ConnectSphere.'),
    ('EVENT_COORDINATOR',  'Event Coordinator',       TRUE,  'Internal staff assigned to coordinate the overall planning of an event; main internal point of contact.'),
    ('VENUE_STAFF',        'Venue Staff',             TRUE,  'Internal staff responsible for venue information, availability, booking decisions and physical venue preparation.'),
    ('TECH_SUPPORT_STAFF', 'Technical Support Staff', TRUE,  'Internal staff responsible for equipment, technical requirements, reservations and on-site technical support.'),
    ('ATTENDEE',           'Attendee',                FALSE, 'External participant who registers for and attends an event.')
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name, is_internal = EXCLUDED.is_internal, description = EXCLUDED.description;

INSERT INTO facilities (code, name, description, sort_order) VALUES
    ('PROJECTOR',          'Projector & screen',      'Ceiling-mounted projector with screen or LED wall.', 10),
    ('SOUND_SYSTEM',       'Sound system',            'In-room PA with mixer.', 20),
    ('VIDEO_CONFERENCING', 'Video conferencing',      'Camera, room microphones and conferencing software for hybrid events.', 30),
    ('WIFI',               'Wi-Fi',                   'Guest wireless internet.', 40),
    ('STAGE',              'Stage',                   'Raised platform for presenters.', 50),
    ('WHITEBOARD',         'Whiteboard / flipchart',  NULL, 60),
    ('CATERING_AREA',      'Catering area',           'Space and power for food service.', 70),
    ('RECORDING',          'Recording equipment',     'Fixed cameras and capture for session recording.', 80),
    ('BREAKOUT_ROOMS',     'Breakout rooms',          'Adjoining smaller rooms.', 90)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name, description = EXCLUDED.description, sort_order = EXCLUDED.sort_order;

INSERT INTO room_layouts (code, name, description, sort_order) VALUES
    ('THEATRE',    'Theatre',    'Rows of chairs facing the front; highest capacity.', 10),
    ('CLASSROOM',  'Classroom',  'Rows of tables and chairs facing the front.', 20),
    ('BOARDROOM',  'Boardroom',  'Single large table.', 30),
    ('U_SHAPE',    'U-shape',    'Tables arranged in a U, open at the front.', 40),
    ('BANQUET',    'Banquet',    'Round tables for dining.', 50),
    ('EXHIBITION', 'Exhibition', 'Open floor for booths and stands.', 60),
    ('STANDING',   'Standing / reception', 'No seating; networking style.', 70)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name, description = EXCLUDED.description, sort_order = EXCLUDED.sort_order;

INSERT INTO accessibility_features (code, name, description, sort_order) VALUES
    ('WHEELCHAIR_ACCESS',   'Wheelchair access',            'Step-free entry and circulation inside the venue.', 10),
    ('STEP_FREE_ROUTE',     'Step-free route from entrance', 'Step-free route from building entrance to the venue.', 20),
    ('LIFT_ACCESS',         'Lift access',                  NULL, 30),
    ('ACCESSIBLE_TOILET',   'Accessible toilet nearby',     NULL, 40),
    ('HEARING_LOOP',        'Hearing loop',                 'Induction loop for hearing-aid users.', 50),
    ('ACCESSIBLE_PARKING',  'Accessible parking',           NULL, 60),
    ('SIGN_LANGUAGE_SPACE', 'Space for sign-language interpreter', 'Clear sight-line position near the presenter.', 70)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name, description = EXCLUDED.description, sort_order = EXCLUDED.sort_order;

INSERT INTO equipment_types (id, code, name, description, total_quantity, storage_location) VALUES
    ('77777777-0000-0000-0000-000000000001', 'PROJECTOR_PORTABLE', 'Portable projector',   'Full HD, HDMI input', 8,  'Equipment store, Level 1'),
    ('77777777-0000-0000-0000-000000000002', 'WIRELESS_MIC',       'Wireless microphone',  'Handheld, UHF',      20, 'Equipment store, Level 1'),
    ('77777777-0000-0000-0000-000000000003', 'LAPEL_MIC',          'Lapel microphone',     NULL,                 10, 'Equipment store, Level 1'),
    ('77777777-0000-0000-0000-000000000004', 'LAPTOP',             'Presentation laptop',  'Windows, with clicker', 6, 'Equipment store, Level 1'),
    ('77777777-0000-0000-0000-000000000005', 'SPEAKER_SET',        'Portable speaker set', 'Pair of powered speakers with stands', 5, 'Equipment store, Level 2'),
    ('77777777-0000-0000-0000-000000000006', 'VIDEO_CAMERA',       'Video camera',         'With tripod',        4,  'Equipment store, Level 2'),
    ('77777777-0000-0000-0000-000000000007', 'LED_SCREEN',         'Mobile LED screen',    '75-inch on stand',   3,  'Equipment store, Level 2'),
    ('77777777-0000-0000-0000-000000000008', 'CONF_PHONE',         'Conference phone',     NULL,                 6,  'Equipment store, Level 1')
ON CONFLICT (id) DO UPDATE SET
    code = EXCLUDED.code, name = EXCLUDED.name, description = EXCLUDED.description,
    total_quantity = EXCLUDED.total_quantity, storage_location = EXCLUDED.storage_location;
