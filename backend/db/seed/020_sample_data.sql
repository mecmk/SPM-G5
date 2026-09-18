-- =====================================================================
-- Seed 020 - sample data for local development and tests.
--
-- * Every row has a FIXED UUID so tests and teammates can refer to it by
--   constant (see backend/tests/support/seed.py for the Python mirror).
--   ID prefixes:   1111.. users   2222.. venues   3333.. events
--                  4444.. venue bookings   5555.. client organisations
--                  6666.. equipment requests   7777.. equipment types (010)
-- * Every login has the password  Password123!
-- * Idempotent: UPSERTs, so `npm run db:ready` re-applies canonical values
--   to these rows on every start without touching rows you created.
-- * Story 1 AC3: "schema can be populated with sample data without
--   integrity errors" - this file is that sample data; the test
--   tests/test_schema.py::test_seed_loads_without_integrity_errors proves it.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Client organisations
-- ---------------------------------------------------------------------
INSERT INTO client_organisations (id, name, contact_email, contact_phone) VALUES
    ('55555555-0000-0000-0000-000000000001', 'Acme Learning Pte Ltd',  'hello@acme-learning.example', '+65 6100 0001'),
    ('55555555-0000-0000-0000-000000000002', 'Nimbus Technologies',    'events@nimbus.example',       '+65 6100 0002')
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name, contact_email = EXCLUDED.contact_email, contact_phone = EXCLUDED.contact_phone;

-- ---------------------------------------------------------------------
-- Users (one or two per role). Password for all: Password123!
-- ---------------------------------------------------------------------
INSERT INTO users (id, email, password_hash, full_name, role_code, organisation_id, phone, department) VALUES
    ('11111111-0000-0000-0000-000000000001', 'organiser@acme.example',    'scrypt$16384$8$1$00112233445566778899aabbccddeeff$c911d27275ec36c9f4b0608f60483cab696b762b352b511362f66e809e89f6fe', 'Olivia Organiser',  'EVENT_ORGANISER',    '55555555-0000-0000-0000-000000000001', '+65 9100 0001', NULL),
    ('11111111-0000-0000-0000-000000000002', 'organiser@nimbus.example',  'scrypt$16384$8$1$00112233445566778899aabbccddeeff$c911d27275ec36c9f4b0608f60483cab696b762b352b511362f66e809e89f6fe', 'Omar Organiser',    'EVENT_ORGANISER',    '55555555-0000-0000-0000-000000000002', '+65 9100 0002', NULL),
    ('11111111-0000-0000-0000-000000000003', 'coordinator@connectsphere.example',  'scrypt$16384$8$1$00112233445566778899aabbccddeeff$c911d27275ec36c9f4b0608f60483cab696b762b352b511362f66e809e89f6fe', 'Chloe Coordinator', 'EVENT_COORDINATOR',  NULL, '+65 9200 0001', 'Events'),
    ('11111111-0000-0000-0000-000000000004', 'coordinator2@connectsphere.example', 'scrypt$16384$8$1$00112233445566778899aabbccddeeff$c911d27275ec36c9f4b0608f60483cab696b762b352b511362f66e809e89f6fe', 'Carl Coordinator',  'EVENT_COORDINATOR',  NULL, '+65 9200 0002', 'Events'),
    ('11111111-0000-0000-0000-000000000005', 'venue@connectsphere.example',        'scrypt$16384$8$1$00112233445566778899aabbccddeeff$c911d27275ec36c9f4b0608f60483cab696b762b352b511362f66e809e89f6fe', 'Vera Venue',        'VENUE_STAFF',        NULL, '+65 9300 0001', 'Venues'),
    ('11111111-0000-0000-0000-000000000006', 'tech@connectsphere.example',         'scrypt$16384$8$1$00112233445566778899aabbccddeeff$c911d27275ec36c9f4b0608f60483cab696b762b352b511362f66e809e89f6fe', 'Theo Tech',         'TECH_SUPPORT_STAFF', NULL, '+65 9400 0001', 'Technical Support'),
    ('11111111-0000-0000-0000-000000000007', 'attendee@example.com',               'scrypt$16384$8$1$00112233445566778899aabbccddeeff$c911d27275ec36c9f4b0608f60483cab696b762b352b511362f66e809e89f6fe', 'Aiden Attendee',    'ATTENDEE',           NULL, NULL, NULL),
    ('11111111-0000-0000-0000-000000000008', 'inactive@connectsphere.example',     'scrypt$16384$8$1$00112233445566778899aabbccddeeff$c911d27275ec36c9f4b0608f60483cab696b762b352b511362f66e809e89f6fe', 'Ian Inactive',      'VENUE_STAFF',        NULL, NULL, 'Venues')
ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email, password_hash = EXCLUDED.password_hash, full_name = EXCLUDED.full_name,
    role_code = EXCLUDED.role_code, organisation_id = EXCLUDED.organisation_id,
    phone = EXCLUDED.phone, department = EXCLUDED.department;
UPDATE users SET is_active = FALSE WHERE id = '11111111-0000-0000-0000-000000000008';

-- ---------------------------------------------------------------------
-- Venues
-- ---------------------------------------------------------------------
INSERT INTO venues (id, name, location, capacity, description, floor_area_sqm, operating_hours_start, operating_hours_end, operating_notes, setup_minutes_default, teardown_minutes_default, status, created_by_id) VALUES
    ('22222222-0000-0000-0000-000000000001', 'Grand Hall',        'Tower A, Level 1',  400, 'Largest space; divisible into two halves.',      520.00, '08:00', '22:00', 'Loading bay access from Carpark B.', 60, 60, 'ACTIVE',    '11111111-0000-0000-0000-000000000005'),
    ('22222222-0000-0000-0000-000000000002', 'Seminar Room 2.1',  'Tower A, Level 2',  80,  'Tiered seminar room with fixed desks.',          140.00, '08:00', '20:00', NULL,                                  30, 15, 'ACTIVE',    '11111111-0000-0000-0000-000000000005'),
    ('22222222-0000-0000-0000-000000000003', 'Boardroom 3.4',     'Tower B, Level 3',  16,  'Executive boardroom.',                            45.00,  '08:00', '18:00', NULL,                                  15, 15, 'ACTIVE',    '11111111-0000-0000-0000-000000000005'),
    ('22222222-0000-0000-0000-000000000004', 'Exhibition Foyer',  'Tower B, Level 1',  250, 'Open-plan foyer suitable for exhibitions.',       380.00, NULL,    NULL,    'Operating hours not yet confirmed.',   45, 45, 'ACTIVE',    '11111111-0000-0000-0000-000000000005'),
    ('22222222-0000-0000-0000-000000000005', 'Old Annex Room',    'Annex, Level 1',    40,  'Withdrawn pending renovation.',                   NULL,   NULL,    NULL,    NULL,                                  0,  0,  'WITHDRAWN', '11111111-0000-0000-0000-000000000005')
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name, location = EXCLUDED.location, capacity = EXCLUDED.capacity,
    description = EXCLUDED.description, floor_area_sqm = EXCLUDED.floor_area_sqm,
    operating_hours_start = EXCLUDED.operating_hours_start, operating_hours_end = EXCLUDED.operating_hours_end,
    operating_notes = EXCLUDED.operating_notes, setup_minutes_default = EXCLUDED.setup_minutes_default,
    teardown_minutes_default = EXCLUDED.teardown_minutes_default, status = EXCLUDED.status,
    created_by_id = EXCLUDED.created_by_id;

INSERT INTO venue_facilities (venue_id, facility_code, quantity, notes) VALUES
    ('22222222-0000-0000-0000-000000000001', 'PROJECTOR', 2, NULL),
    ('22222222-0000-0000-0000-000000000001', 'SOUND_SYSTEM', NULL, NULL),
    ('22222222-0000-0000-0000-000000000001', 'STAGE', NULL, NULL),
    ('22222222-0000-0000-0000-000000000001', 'WIFI', NULL, NULL),
    ('22222222-0000-0000-0000-000000000001', 'CATERING_AREA', NULL, NULL),
    ('22222222-0000-0000-0000-000000000002', 'PROJECTOR', 1, NULL),
    ('22222222-0000-0000-0000-000000000002', 'VIDEO_CONFERENCING', NULL, 'Zoom Rooms'),
    ('22222222-0000-0000-0000-000000000002', 'WIFI', NULL, NULL),
    ('22222222-0000-0000-0000-000000000003', 'VIDEO_CONFERENCING', NULL, NULL),
    ('22222222-0000-0000-0000-000000000003', 'WHITEBOARD', NULL, NULL),
    ('22222222-0000-0000-0000-000000000003', 'WIFI', NULL, NULL),
    ('22222222-0000-0000-0000-000000000004', 'WIFI', NULL, NULL),
    ('22222222-0000-0000-0000-000000000004', 'CATERING_AREA', NULL, NULL)
ON CONFLICT (venue_id, facility_code) DO UPDATE SET quantity = EXCLUDED.quantity, notes = EXCLUDED.notes;

INSERT INTO venue_layouts (venue_id, layout_code, layout_capacity) VALUES
    ('22222222-0000-0000-0000-000000000001', 'THEATRE', NULL),
    ('22222222-0000-0000-0000-000000000001', 'BANQUET', 240),
    ('22222222-0000-0000-0000-000000000001', 'EXHIBITION', 300),
    ('22222222-0000-0000-0000-000000000001', 'STANDING', NULL),
    ('22222222-0000-0000-0000-000000000002', 'CLASSROOM', NULL),
    ('22222222-0000-0000-0000-000000000003', 'BOARDROOM', NULL),
    ('22222222-0000-0000-0000-000000000004', 'EXHIBITION', NULL),
    ('22222222-0000-0000-0000-000000000004', 'STANDING', NULL)
ON CONFLICT (venue_id, layout_code) DO UPDATE SET layout_capacity = EXCLUDED.layout_capacity;

INSERT INTO venue_accessibility_features (venue_id, feature_code, notes) VALUES
    ('22222222-0000-0000-0000-000000000001', 'WHEELCHAIR_ACCESS', NULL),
    ('22222222-0000-0000-0000-000000000001', 'STEP_FREE_ROUTE', NULL),
    ('22222222-0000-0000-0000-000000000001', 'ACCESSIBLE_TOILET', NULL),
    ('22222222-0000-0000-0000-000000000001', 'HEARING_LOOP', NULL),
    ('22222222-0000-0000-0000-000000000002', 'WHEELCHAIR_ACCESS', 'Front row only'),
    ('22222222-0000-0000-0000-000000000002', 'LIFT_ACCESS', NULL),
    ('22222222-0000-0000-0000-000000000003', 'LIFT_ACCESS', NULL),
    ('22222222-0000-0000-0000-000000000004', 'WHEELCHAIR_ACCESS', NULL),
    ('22222222-0000-0000-0000-000000000004', 'STEP_FREE_ROUTE', NULL)
ON CONFLICT (venue_id, feature_code) DO UPDATE SET notes = EXCLUDED.notes;

INSERT INTO venue_unavailability_periods (id, venue_id, starts_at, ends_at, reason, notes, created_by_id) VALUES
    ('88888888-0000-0000-0000-000000000001', '22222222-0000-0000-0000-000000000002', '2026-11-02 00:00+08', '2026-11-04 00:00+08', 'MAINTENANCE', 'Annual air-con servicing', '11111111-0000-0000-0000-000000000005')
ON CONFLICT (id) DO UPDATE SET
    venue_id = EXCLUDED.venue_id, starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at,
    reason = EXCLUDED.reason, notes = EXCLUDED.notes;

-- ---------------------------------------------------------------------
-- Events in several lifecycle stages
-- ---------------------------------------------------------------------
INSERT INTO events (id, organiser_id, organisation_id, name, purpose, description, starts_at, ends_at, expected_attendance, status,
                    assigned_coordinator_id, preferred_location, required_layout_code, accessibility_none_required,
                    registration_required, registration_capacity, registration_closes_at,
                    contact_name, contact_email, submitted_at, decided_at, decided_by_id, decision_reason) VALUES
    -- 3333..01: a draft, deliberately incomplete
    ('33333333-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Q1 Sales Kick-off (draft)', NULL, 'Still gathering requirements.', NULL, NULL, NULL, 'DRAFT',
     NULL, NULL, NULL, FALSE, FALSE, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    -- 3333..02: submitted, waiting for a coordinator
    ('33333333-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Data Literacy Workshop', 'Staff training', 'One-day hands-on workshop.', '2026-11-18 09:00+08', '2026-11-18 17:00+08', 60, 'SUBMITTED',
     NULL, 'Tower A', 'CLASSROOM', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '2026-09-08 10:15+08', NULL, NULL, NULL),
    -- 3333..03: approved and assigned; has an approved venue booking
    ('33333333-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Nimbus Developer Conference', 'Annual customer conference', 'Keynotes in the morning, breakout tracks after lunch.', '2026-11-25 09:00+08', '2026-11-25 18:00+08', 350, 'APPROVED',
     '11111111-0000-0000-0000-000000000003', 'Tower A', 'THEATRE', FALSE, TRUE, 350, '2026-11-20 18:00+08', 'Omar Organiser', 'organiser@nimbus.example', '2026-09-01 09:00+08', '2026-09-03 14:30+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..04: rejected with a reason
    ('33333333-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Rooftop Networking Night', 'Networking', NULL, '2026-10-30 19:00+08', '2026-10-30 23:00+08', 120, 'REJECTED',
     '11111111-0000-0000-0000-000000000004', 'Rooftop', 'STANDING', TRUE, FALSE, NULL, NULL, NULL, NULL, '2026-09-05 16:00+08', '2026-09-07 11:00+08', '11111111-0000-0000-0000-000000000004', 'No outdoor venues are available after 22:00.')
ON CONFLICT (id) DO UPDATE SET
    organiser_id = EXCLUDED.organiser_id, organisation_id = EXCLUDED.organisation_id, name = EXCLUDED.name,
    purpose = EXCLUDED.purpose, description = EXCLUDED.description, starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at,
    expected_attendance = EXCLUDED.expected_attendance, status = EXCLUDED.status,
    assigned_coordinator_id = EXCLUDED.assigned_coordinator_id, preferred_location = EXCLUDED.preferred_location,
    required_layout_code = EXCLUDED.required_layout_code, accessibility_none_required = EXCLUDED.accessibility_none_required,
    registration_required = EXCLUDED.registration_required, registration_capacity = EXCLUDED.registration_capacity,
    registration_closes_at = EXCLUDED.registration_closes_at, contact_name = EXCLUDED.contact_name,
    contact_email = EXCLUDED.contact_email, submitted_at = EXCLUDED.submitted_at, decided_at = EXCLUDED.decided_at,
    decided_by_id = EXCLUDED.decided_by_id, decision_reason = EXCLUDED.decision_reason;

INSERT INTO event_required_facilities (event_id, facility_code) VALUES
    ('33333333-0000-0000-0000-000000000002', 'PROJECTOR'),
    ('33333333-0000-0000-0000-000000000002', 'WIFI'),
    ('33333333-0000-0000-0000-000000000003', 'PROJECTOR'),
    ('33333333-0000-0000-0000-000000000003', 'SOUND_SYSTEM'),
    ('33333333-0000-0000-0000-000000000003', 'STAGE')
ON CONFLICT DO NOTHING;

INSERT INTO event_accessibility_needs (event_id, feature_code, notes) VALUES
    ('33333333-0000-0000-0000-000000000003', 'WHEELCHAIR_ACCESS', 'Two wheelchair users expected'),
    ('33333333-0000-0000-0000-000000000003', 'HEARING_LOOP', NULL)
ON CONFLICT DO NOTHING;

INSERT INTO event_equipment_requests (id, event_id, equipment_type_id, quantity, technical_notes, status, created_by_id) VALUES
    ('66666666-0000-0000-0000-000000000001', '33333333-0000-0000-0000-000000000003', '77777777-0000-0000-0000-000000000002', 6, 'Two per breakout room', 'REQUESTED', '11111111-0000-0000-0000-000000000002'),
    ('66666666-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000003', '77777777-0000-0000-0000-000000000004', 2, NULL, 'REQUESTED', '11111111-0000-0000-0000-000000000002'),
    ('66666666-0000-0000-0000-000000000003', '33333333-0000-0000-0000-000000000002', '77777777-0000-0000-0000-000000000001', 1, 'Room already has one; spare requested', 'REQUESTED', '11111111-0000-0000-0000-000000000001')
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, equipment_type_id = EXCLUDED.equipment_type_id, quantity = EXCLUDED.quantity,
    technical_notes = EXCLUDED.technical_notes, status = EXCLUDED.status, created_by_id = EXCLUDED.created_by_id;

-- Status history for the non-draft events (append-only in real use; idempotent here via fixed ids)
INSERT INTO event_status_history (id, event_id, from_status, to_status, changed_by_id, changed_at, reason) VALUES
    ('99999999-0000-0000-0000-000000000001', '33333333-0000-0000-0000-000000000002', NULL, 'DRAFT', '11111111-0000-0000-0000-000000000001', '2026-09-08 10:00+08', NULL),
    ('99999999-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000002', 'DRAFT', 'SUBMITTED', '11111111-0000-0000-0000-000000000001', '2026-09-08 10:15+08', NULL),
    ('99999999-0000-0000-0000-000000000003', '33333333-0000-0000-0000-000000000003', NULL, 'DRAFT', '11111111-0000-0000-0000-000000000002', '2026-08-30 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000004', '33333333-0000-0000-0000-000000000003', 'DRAFT', 'SUBMITTED', '11111111-0000-0000-0000-000000000002', '2026-09-01 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000005', '33333333-0000-0000-0000-000000000003', 'SUBMITTED', 'UNDER_REVIEW', '11111111-0000-0000-0000-000000000003', '2026-09-02 09:30+08', NULL),
    ('99999999-0000-0000-0000-000000000006', '33333333-0000-0000-0000-000000000003', 'UNDER_REVIEW', 'APPROVED', '11111111-0000-0000-0000-000000000003', '2026-09-03 14:30+08', NULL),
    ('99999999-0000-0000-0000-000000000007', '33333333-0000-0000-0000-000000000004', NULL, 'DRAFT', '11111111-0000-0000-0000-000000000002', '2026-09-05 15:00+08', NULL),
    ('99999999-0000-0000-0000-000000000008', '33333333-0000-0000-0000-000000000004', 'DRAFT', 'SUBMITTED', '11111111-0000-0000-0000-000000000002', '2026-09-05 16:00+08', NULL),
    ('99999999-0000-0000-0000-000000000009', '33333333-0000-0000-0000-000000000004', 'SUBMITTED', 'REJECTED', '11111111-0000-0000-0000-000000000004', '2026-09-07 11:00+08', 'No outdoor venues are available after 22:00.')
ON CONFLICT (id) DO NOTHING;

INSERT INTO event_coordinator_assignments (id, event_id, coordinator_id, assigned_by_id, assigned_at) VALUES
    ('aaaaaaaa-0000-0000-0000-000000000001', '33333333-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-02 09:30+08'),
    ('aaaaaaaa-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-06 09:00+08')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- Venue bookings: one APPROVED (blocks Grand Hall on 25 Nov), one PENDING
-- ---------------------------------------------------------------------
INSERT INTO venue_bookings (id, event_id, venue_id, requested_by_id, starts_at, ends_at, setup_minutes, teardown_minutes,
                            expected_attendance, required_layout_code, requirement_notes, status, decided_by_id, decided_at) VALUES
    ('44444444-0000-0000-0000-000000000001', '33333333-0000-0000-0000-000000000003', '22222222-0000-0000-0000-000000000001',
     '11111111-0000-0000-0000-000000000003', '2026-11-25 09:00+08', '2026-11-25 18:00+08', 60, 60,
     350, 'THEATRE', 'Projector, sound system and stage required.', 'APPROVED', '11111111-0000-0000-0000-000000000005', '2026-09-04 10:00+08'),
    ('44444444-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000003', '22222222-0000-0000-0000-000000000002',
     '11111111-0000-0000-0000-000000000003', '2026-11-25 13:00+08', '2026-11-25 18:00+08', 30, 15,
     60, 'CLASSROOM', 'Breakout track B.', 'PENDING', NULL, NULL)
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, venue_id = EXCLUDED.venue_id, requested_by_id = EXCLUDED.requested_by_id,
    starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at, setup_minutes = EXCLUDED.setup_minutes,
    teardown_minutes = EXCLUDED.teardown_minutes, expected_attendance = EXCLUDED.expected_attendance,
    required_layout_code = EXCLUDED.required_layout_code, requirement_notes = EXCLUDED.requirement_notes,
    status = EXCLUDED.status, decided_by_id = EXCLUDED.decided_by_id, decided_at = EXCLUDED.decided_at;
