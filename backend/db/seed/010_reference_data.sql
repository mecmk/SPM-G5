-- =====================================================================
-- Seed 010 - reference data (roles, facilities, layouts, accessibility
-- features, equipment types).
--
-- Idempotent: every statement is an UPSERT, so `npm run db:ready` can run
-- it on every start. Editing a name here and re-running updates the row;
-- rows you delete here are NOT removed from the database (add a DELETE
-- if you really need that). Room layouts are the exception: Venue Staff
-- manage them in the app (story 8.6), so their rows are only added where
-- missing - see the room_layouts statement.
-- =====================================================================

INSERT INTO roles (code, name, is_internal, description) VALUES
    ('EVENT_ORGANISER',    'Event Organiser',         FALSE, 'External client representative who has an event to organise and communicates requirements to ConnectSphere.'),
    ('EVENT_COORDINATOR',  'Event Coordinator',       TRUE,  'Internal staff assigned to coordinate the overall planning of an event; main internal point of contact.'),
    ('VENUE_STAFF',        'Venue Staff',             TRUE,  'Internal staff responsible for venue information, availability, booking decisions and physical venue preparation.'),
    ('TECH_SUPPORT_STAFF', 'Technical Support Staff', TRUE,  'Internal staff responsible for equipment, technical requirements, reservations and on-site technical support.'),
    ('ATTENDEE',           'Attendee',                FALSE, 'External participant who registers for and attends an event.'),
    ('SAFETY_OFFICER',     'Safety Officer',          TRUE,  'Internal staff who check an event is operationally safe before it goes ahead.'),
    ('EVENT_COORDINATOR_LEAD', 'Event Coordinator Lead', TRUE, 'Internal staff who review newly submitted event requests and assign each to an Event Coordinator with the team''s workload in mind (story 5.4).')
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
    ('BREAKOUT_ROOMS',     'Breakout rooms',          'Adjoining smaller rooms.', 90)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name, description = EXCLUDED.description, sort_order = EXCLUDED.sort_order;

-- f2.1.2: RECORDING had no corresponding row in equipment_types, so an organiser could request
-- it under venue requirements with nothing behind it to actually reserve or track. INSERTs above
-- are UPSERT-only and never remove a row, so the delete is explicit.
DELETE FROM facilities WHERE code = 'RECORDING';

-- Story 8.6: Venue Staff add, rename and delete room layouts in the app, so these are only the
-- standard ones a new database starts with. A row is added only where it is missing - no
-- conflict target, so a layout whose code or name is now taken is skipped too - and a rename or
-- a new description made in the app is never undone. A standard layout deleted in the app stays
-- deleted: its code is in deleted_room_layouts, and no layout takes it again.
INSERT INTO room_layouts (code, name, description, sort_order)
SELECT standard.code, standard.name, standard.description, standard.sort_order
FROM (VALUES
    ('THEATRE',    'Theatre',    'Rows of chairs facing the front; highest capacity.', 10),
    ('CLASSROOM',  'Classroom',  'Rows of tables and chairs facing the front.', 20),
    ('BOARDROOM',  'Boardroom',  'Single large table.', 30),
    ('U_SHAPE',    'U-shape',    'Tables arranged in a U, open at the front.', 40),
    ('BANQUET',    'Banquet',    'Round tables for dining.', 50),
    ('EXHIBITION', 'Exhibition', 'Open floor for booths and stands.', 60),
    ('STANDING',   'Standing / reception', 'No seating; networking style.', 70)
) AS standard (code, name, description, sort_order)
WHERE NOT EXISTS (SELECT 1 FROM deleted_room_layouts deleted WHERE deleted.code = standard.code)
ON CONFLICT DO NOTHING;

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

-- Story 21.2: the factors a safety review considers.
INSERT INTO safety_review_factors (code, name, description, sort_order) VALUES
    ('EXPECTED_ATTENDANCE',  'Expected attendance',        'How many people are expected, against what the event can safely hold.', 10),
    ('CAPACITY_AND_LAYOUT',  'Venue capacity and layout',  'Whether each venue holds its people in the booked layout.', 20),
    ('EMERGENCY_ACCESS',     'Emergency access',           'Exits, evacuation routes and access for emergency services.', 30),
    ('ACCESSIBILITY',        'Accessibility requirements', 'Whether the accessibility needs can be met safely.', 40),
    ('EQUIPMENT_PLACEMENT',  'Equipment placement',        'Where equipment, cables and staging go, and what they obstruct.', 50),
    ('CROWD_MOVEMENT',       'Crowd movement',             'Queues, entry and exit flow, and pinch points.', 60),
    ('VENUE_RESTRICTIONS',   'Known venue restrictions',   'Any restriction the venue is known to have.', 70)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name, description = EXCLUDED.description, sort_order = EXCLUDED.sort_order;
