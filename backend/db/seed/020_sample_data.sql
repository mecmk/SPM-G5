-- =====================================================================
-- Seed 020 - sample data for local development and tests.
--
-- * Every row has a FIXED UUID so tests and teammates can refer to it by
--   constant (see backend/tests/support/seed.py for the Python mirror).
--   ID prefixes:   1111.. users   2222.. venues   3333.. events
--                  4444.. venue bookings   5555.. client organisations
--                  6666.. equipment requests   7777.. equipment types (010)
--                  bbbb.. event clarifications   cccc.. venue requirements
--                  dddd.. equipment out of service   eeee.. equipment holds
--                  ffff.. safety reviews
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
    ('11111111-0000-0000-0000-000000000008', 'inactive@connectsphere.example',     'scrypt$16384$8$1$00112233445566778899aabbccddeeff$c911d27275ec36c9f4b0608f60483cab696b762b352b511362f66e809e89f6fe', 'Ian Inactive',      'VENUE_STAFF',        NULL, NULL, 'Venues'),
    ('11111111-0000-0000-0000-000000000009', 'safety@connectsphere.example',       'scrypt$16384$8$1$00112233445566778899aabbccddeeff$c911d27275ec36c9f4b0608f60483cab696b762b352b511362f66e809e89f6fe', 'Sam Safety',        'SAFETY_OFFICER',     NULL, '+65 9500 0001', 'Safety')
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
INSERT INTO events (id, organiser_id, organisation_id, name, purpose, description, cover_image_url, starts_at, ends_at, expected_attendance, status,
                    assigned_coordinator_id, preferred_location, accessibility_none_required,
                    registration_required, registration_capacity, registration_closes_at,
                    contact_name, contact_email, contact_phone, submitted_at, decided_at, decided_by_id, decision_reason) VALUES
    -- 3333..01: a draft, deliberately incomplete
    ('33333333-0000-0000-0000-000000000001', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Q1 Sales Kick-off (draft)', NULL, 'Still gathering requirements.', NULL, NULL, NULL, NULL, 'DRAFT',
     NULL, NULL, FALSE, FALSE, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    -- 3333..02: under review, assigned to Chloe, waiting for her decision
    ('33333333-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Data Literacy Workshop', 'Staff training', 'One-day hands-on workshop.', '/images/events/cat.jpg', '2026-11-18 09:00+08', '2026-11-18 17:00+08', 60, 'UNDER_REVIEW',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '+65 6111 2233', '2026-09-08 10:15+08', NULL, NULL, NULL),
    -- 3333..03: in planning and assigned; has an approved venue booking
    ('33333333-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Nimbus Developer Conference', 'Annual customer conference', 'Keynotes in the morning, breakout tracks after lunch.', NULL, '2026-11-25 09:00+08', '2026-11-25 18:00+08', 350, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', FALSE, TRUE, 350, '2026-11-20 18:00+08', 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-01 09:00+08', '2026-09-03 14:30+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..04: rejected with a reason
    ('33333333-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Rooftop Networking Night', 'Networking', NULL, NULL, '2026-10-30 19:00+08', '2026-10-30 23:00+08', 120, 'REJECTED',
     '11111111-0000-0000-0000-000000000004', 'Rooftop', TRUE, FALSE, NULL, NULL, NULL, NULL, NULL, '2026-09-05 16:00+08', '2026-09-07 11:00+08', '11111111-0000-0000-0000-000000000004', 'No outdoor venues are available after 22:00.'),
    -- 3333..05: under review, assigned to Chloe (more review-queue test data)
    ('33333333-0000-0000-0000-000000000005', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Nimbus Leadership Offsite', 'Internal meeting', 'Quarterly leadership planning session.', NULL, '2026-12-02 09:00+08', '2026-12-02 16:00+08', 25, 'UNDER_REVIEW',
     '11111111-0000-0000-0000-000000000003', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-10 08:00+08', NULL, NULL, NULL),
    -- 3333..06: sent back for clarification, assigned to Chloe
    ('33333333-0000-0000-0000-000000000006', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Diversity & Inclusion Forum', 'Community outreach', 'Panel discussion and workshops on workplace inclusion.', NULL, '2026-11-05 09:30+08', '2026-11-05 15:00+08', 150, 'CLARIFICATION_REQUESTED',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '+65 6111 2233', '2026-09-03 09:00+08', NULL, NULL, NULL),
    -- 3333..07: under review, assigned to Chloe, proposed before Data Literacy Workshop but submitted after it
    ('33333333-0000-0000-0000-000000000007', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Wellness Week Kickoff', 'Wellbeing', 'Morning of fitness taster sessions and a healthy breakfast.', NULL, '2026-10-20 08:00+08', '2026-10-20 12:00+08', 80, 'UNDER_REVIEW',
     '11111111-0000-0000-0000-000000000003', 'Exhibition Foyer', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '+65 6111 2233', '2026-09-15 14:00+08', NULL, NULL, NULL),
    -- 3333..08: in planning and assigned to Carl; has a pending venue booking (story 13.1 queue data)
    ('33333333-0000-0000-0000-000000000008', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Annual Wellness Summit', 'Company-wide wellness and mental health awareness day', 'Talks, workshops and screening booths for staff wellbeing.', NULL, '2026-12-03 09:00+08', '2026-12-03 17:00+08', 180, 'PLANNING',
     '11111111-0000-0000-0000-000000000004', 'Tower B', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '+65 6111 2233', '2026-09-10 09:00+08', '2026-09-12 10:00+08', '11111111-0000-0000-0000-000000000004', NULL),
    -- 3333..09: in planning and assigned to Chloe; has a pending venue booking (story 13.1 queue data)
    ('33333333-0000-0000-0000-000000000009', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Product Roadmap Townhall', 'Quarterly roadmap briefing for customers and partners', 'Livestreamed briefing with Q&A for remote offices.', NULL, '2027-01-15 10:00+08', '2027-01-15 12:00+08', 300, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-14 09:00+08', '2026-09-16 11:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..10: in planning and assigned to Chloe; pending venue booking dedicated to the story
    -- 13.2 approve e2e test (queue card) - no other test/assertion reads this row, since the
    -- e2e run's fullyParallel database is shared and approving it would break story 13.1's
    -- queue assertions if it were one of their rows.
    ('33333333-0000-0000-0000-000000000010', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Founders Day Fireside Chat', 'A conversation with the founders', 'Casual fireside chat and Q&A for all staff.', NULL, '2027-06-01 15:00+08', '2027-06-01 17:00+08', 200, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '+65 6111 2233', '2026-09-10 09:00+08', '2026-09-12 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..11: in planning and assigned to Carl; pending venue booking dedicated to the story
    -- 13.2 approve e2e test (detail page) - see 3333..10's note.
    ('33333333-0000-0000-0000-000000000011', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Investor Demo Day', 'Quarterly investor product demo', 'Live product walkthrough for the board and investors.', NULL, '2027-07-01 09:00+08', '2027-07-01 12:00+08', 100, 'PLANNING',
     '11111111-0000-0000-0000-000000000004', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-11 09:00+08', '2026-09-13 09:00+08', '11111111-0000-0000-0000-000000000004', NULL),
    -- 3333..16: in planning and assigned to Chloe; pending venue booking dedicated to the story
    -- 13.2.1 reject e2e test (queue card) - see 3333..10's note above for why this needs its
    -- own row rather than reusing an existing PENDING booking.
    ('33333333-0000-0000-0000-000000000016', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Winter Charity Gala', 'Annual fundraising dinner', 'Formal dinner and silent auction for the winter appeal.', NULL, '2027-08-01 18:00+08', '2027-08-01 22:00+08', 220, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '+65 6111 2233', '2026-09-12 09:00+08', '2026-09-14 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..17: in planning and assigned to Carl; pending venue booking dedicated to the story
    -- 13.2.1 reject e2e test (detail page) - see 3333..16's note.
    ('33333333-0000-0000-0000-000000000017', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Alumni Homecoming Weekend', 'Alumni relations', 'Campus tours and an evening showcase for returning alumni.', NULL, '2027-09-01 09:00+08', '2027-09-01 17:00+08', 100, 'PLANNING',
     '11111111-0000-0000-0000-000000000004', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-13 09:00+08', '2026-09-15 09:00+08', '11111111-0000-0000-0000-000000000004', NULL),
    -- 3333..12-15: one event in each of the four statuses story 6.1 adds to the visible/status
    -- model (PLANNING, CONFIRMED, COMPLETED, CANCELLED) - none were seeded before, so the
    -- coordinator's assigned-events list had nothing to show for them.
    ('33333333-0000-0000-0000-000000000012', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Regional Sales Summit', 'Sales enablement', 'Two-day summit for the regional sales teams.', NULL, '2026-12-15 09:00+08', '2026-12-16 17:00+08', 220, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '+65 6111 2233', '2026-09-12 09:00+08', '2026-09-14 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..13: confirmed - venue and equipment arranged, event still in the future
    ('33333333-0000-0000-0000-000000000013', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Partner Appreciation Dinner', 'Partner relations', 'A formal dinner thanking key channel partners.', NULL, '2027-02-10 18:30+08', '2027-02-10 22:00+08', 90, 'CONFIRMED',
     '11111111-0000-0000-0000-000000000003', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-13 09:00+08', '2026-09-15 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..14: completed - its date has already passed relative to "today" in this dataset
    ('33333333-0000-0000-0000-000000000014', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'New Year Town Hall', 'All-hands briefing', 'Company-wide briefing on the year ahead.', NULL, '2026-08-01 09:00+08', '2026-08-01 11:00+08', 300, 'COMPLETED',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '+65 6111 2233', '2026-06-20 09:00+08', '2026-06-22 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..15: cancelled after being arranged
    ('33333333-0000-0000-0000-000000000015', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Summer Rooftop Mixer', 'Team social', 'An evening social mixer on the rooftop terrace.', NULL, '2026-10-05 18:00+08', '2026-10-05 21:00+08', 60, 'CANCELLED',
     '11111111-0000-0000-0000-000000000003', 'Rooftop', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-08-25 09:00+08', '2026-08-27 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..18: in planning and assigned to Chloe; dedicated to story 11.1's e2e spec
    -- (tests/e2e/venue-suitability.spec.ts), which judges venues for its one venue requirement
    -- and is refused for want of a justification. Since story 12.5 a requirement takes one
    -- request at a time, so no test's request for it is ever written: the spec's real send has
    -- 3333..33, and story 12.1's has 3333..31.
    ('33333333-0000-0000-0000-000000000018', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Quarterly Partner Briefing', 'Partner relations', 'Pricing and roadmap update for channel partners.', NULL, '2027-03-10 09:00+08', '2027-03-10 12:00+08', 60, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', NULL, TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-16 09:00+08', '2026-09-18 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..19 and 3333..20: in planning and assigned to Chloe; dedicated to story 15.1's e2e spec
    -- (tests/e2e/equipment-requests.spec.ts). Dated May 2027, clear of the periods backend tests
    -- build relative to today, so their equipment holds change no figure another test asserts.
    -- 19's equipment is changed by that spec's flow; 20's is only read.
    ('33333333-0000-0000-0000-000000000019', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Robotics Hands-on Workshop', 'Staff training', 'A day of building and programming small robots in teams.', NULL, '2027-05-12 09:00+08', '2027-05-12 17:00+08', 40, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '+65 6111 2233', '2026-09-20 09:00+08', '2026-09-22 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    ('33333333-0000-0000-0000-000000000020', '11111111-0000-0000-0000-000000000001', '55555555-0000-0000-0000-000000000001',
     'Product Launch Showcase', 'Product launch', 'Demonstrations of the new product line for key customers.', NULL, '2027-05-19 09:00+08', '2027-05-19 17:00+08', 120, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower B', TRUE, FALSE, NULL, NULL, 'Olivia Organiser', 'organiser@acme.example', '+65 6111 2233', '2026-09-21 09:00+08', '2026-09-23 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..21: in planning and assigned to Chloe; dedicated to story 15.2's e2e spec
    -- (tests/e2e/equipment-queue.spec.ts), which only reads it. Dated June 2027, clear of 15.1's
    -- events and of the periods backend tests build.
    ('33333333-0000-0000-0000-000000000021', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Regional Partner Roadshow', 'Partner relations', 'A day of product sessions for regional reseller partners.', NULL, '2027-06-16 09:00+08', '2027-06-16 17:00+08', 80, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-24 09:00+08', '2026-09-25 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..22-26: in planning, split between Chloe and Carl, dated July-November 2027; more of
    -- story 15.2's e2e queue, read only. 22 and 23 overlap on 7 July, so each one's wireless
    -- microphones count against the other's.
    ('33333333-0000-0000-0000-000000000022', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Fintech Leaders Breakfast', 'Client networking', 'A breakfast briefing on payments regulation for banking clients.', NULL, '2027-07-07 08:00+08', '2027-07-07 11:00+08', 45, 'PLANNING',
     '11111111-0000-0000-0000-000000000004', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-27 09:00+08', '2026-09-28 09:00+08', '11111111-0000-0000-0000-000000000004', NULL),
    ('33333333-0000-0000-0000-000000000023', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Customer Success Forum', 'Customer engagement', 'Talks and workshops on getting the most from the platform.', NULL, '2027-07-07 10:00+08', '2027-07-07 17:00+08', 150, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-27 10:00+08', '2026-09-28 10:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    ('33333333-0000-0000-0000-000000000024', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Annual Sales Kickoff', 'Staff conference', 'The sales team''s yearly kickoff: targets, awards and product training.', NULL, '2027-08-18 09:00+08', '2027-08-18 18:00+08', 220, 'PLANNING',
     '11111111-0000-0000-0000-000000000004', 'Tower A', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-28 09:00+08', '2026-09-29 09:00+08', '11111111-0000-0000-0000-000000000004', NULL),
    ('33333333-0000-0000-0000-000000000025', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Graduate Recruitment Fair', 'Recruitment', 'Employer booths and talks for final-year students.', NULL, '2027-09-22 10:00+08', '2027-09-22 16:00+08', 300, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-29 09:00+08', '2026-09-30 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    ('33333333-0000-0000-0000-000000000026', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Year-End Partner Gala', 'Partner relations', 'A dinner and awards evening for the year''s top partners.', NULL, '2027-11-26 18:00+08', '2027-11-26 23:00+08', 180, 'PLANNING',
     '11111111-0000-0000-0000-000000000004', 'Tower A', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-30 09:00+08', '2026-10-01 09:00+08', '11111111-0000-0000-0000-000000000004', NULL),
    -- 3333..27: in planning and assigned to Chloe; dedicated to story 16.1's e2e spec
    -- (tests/e2e/equipment-decisions.spec.ts), which accepts and declines its items. Runs over two
    -- days, 8-9 December 2027, so the spec sees a period over more than one day named in full; clear
    -- of every other seeded event and of the periods backend tests build.
    ('33333333-0000-0000-0000-000000000027', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Leadership Offsite', 'Staff conference', 'Two days of strategy sessions for senior leaders.', NULL, '2027-12-08 09:00+08', '2027-12-09 17:00+08', 40, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-10-02 09:00+08', '2026-10-03 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..28: in planning and assigned to Chloe; dedicated to story 8.4's e2e spec
    -- (tests/e2e/venue-requirement-search.spec.ts), which only reads it. Its three venue
    -- requirements (below) each find different venues, so choosing one visibly changes the results.
    -- Dated March 2028, clear of every other seeded event and of the periods backend tests build.
    ('33333333-0000-0000-0000-000000000028', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Smart Cities Expo', 'Industry exhibition', 'Two days of keynotes, breakout workshops and an exhibition of smart-city projects.', NULL, '2028-03-14 09:00+08', '2028-03-15 18:00+08', 300, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', FALSE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-10-05 09:00+08', '2026-10-07 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..29 and 3333..30: in planning and assigned to Chloe; dedicated to story 12.5's e2e spec
    -- (tests/e2e/venue-requirement-booking.spec.ts), which sends real requests for them, so 8.4's
    -- read-only Expo above is never changed. 29 records three venue requirements and no bookings;
    -- 30 records one, already booked (below). Dated April and June 2028, clear of every other
    -- seeded event and of the periods backend tests build.
    ('33333333-0000-0000-0000-000000000029', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Urban Mobility Forum', 'Industry forum', 'Two days of exhibits, workshops and an evening of networking on city transport.', NULL, '2028-04-11 09:00+08', '2028-04-12 17:00+08', 200, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', FALSE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-10-06 09:00+08', '2026-10-08 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    ('33333333-0000-0000-0000-000000000030', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Coastal Resilience Workshop', 'Partner workshop', 'A morning working session on flood planning with partner agencies.', NULL, '2028-06-06 09:00+08', '2028-06-06 12:00+08', 12, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-10-06 10:00+08', '2026-10-08 10:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..31: in planning and assigned to Chloe; dedicated to story 12.1's e2e request that is
    -- really sent (tests/e2e/booking-requests.spec.ts), to Seminar Room 2.1. Since story 12.5 a
    -- venue requirement takes one request at a time, so it has an event of its own rather than
    -- sharing 3333..18's, which story 11.1's spec requests a venue for. Dated May 2028.
    ('33333333-0000-0000-0000-000000000031', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Sales Onboarding Day', 'Staff training', 'A day of product training for new sales starters.', NULL, '2028-05-17 09:00+08', '2028-05-17 17:00+08', 40, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower A', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-10-06 11:00+08', '2026-10-08 11:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..32: in planning and assigned to Chloe; dedicated to story 12.5's e2e spec, which
    -- requests venues for it and then withdraws and switches them from the catalogue (decided
    -- 11 Oct 2026). Three venue requirements and no bookings, dated July 2028.
    ('33333333-0000-0000-0000-000000000032', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Harbourfront Trade Fair', 'Trade fair', 'A day of exhibitor stands, buyer training and an evening reception.', NULL, '2028-07-19 09:00+08', '2028-07-19 20:00+08', 150, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-10-06 12:00+08', '2026-10-08 12:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..33: in planning and assigned to Chloe; dedicated to story 11.1's e2e request that is
    -- really sent with a justification (tests/e2e/venue-suitability.spec.ts), to Exhibition
    -- Foyer. Shaped like 3333..18 - one Main venue for 60 people, Classroom with a projector -
    -- so the Foyer fails it the same way. An event of its own since story 12.5, because a venue
    -- requirement takes one request at a time. Dated a week after 3333..18, so its request sits
    -- where that one's did in Venue Staff's queue, which lists the soonest first.
    ('33333333-0000-0000-0000-000000000033', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Reseller Pricing Clinic', 'Partner relations', 'A morning of pricing questions from reseller partners.', NULL, '2027-03-17 09:00+08', '2027-03-17 12:00+08', 60, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', NULL, TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-10-09 09:00+08', '2026-10-11 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..34: in planning and assigned to Chloe; dedicated to story 12.7's e2e spec
    -- (tests/e2e/venue-hold-expiry.spec.ts). Its one venue requirement's booking expired before
    -- the event was confirmed (below), and the spec requests a venue for it again. Dated July 2028.
    ('33333333-0000-0000-0000-000000000034', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Community Craft Fair', 'Community event', 'Stalls for local makers, with a workshop corner.', NULL, '2028-07-12 10:00+08', '2028-07-12 16:00+08', 120, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-24 09:00+08', '2026-09-26 09:00+08', '11111111-0000-0000-0000-000000000003', NULL),
    -- 3333..35 and 3333..36: awaiting the Safety Officer's check, for story 21.1. The 35 expects
    -- more people than its one approved venue holds, at a venue whose operating hours are not
    -- recorded. The 36 is within capacity and was sent back once by the officer
    -- (event_safety_reviews below), when it had fewer people and microphones than it has now.
    ('33333333-0000-0000-0000-000000000035', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Harbour Lights Concert', 'Community event', 'An evening concert on the foyer floor.', NULL, '2028-08-16 18:00+08', '2028-08-16 22:00+08', 300, 'AWAITING_SAFETY_CHECK',
     '11111111-0000-0000-0000-000000000004', 'Tower B', FALSE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-28 09:00+08', '2026-09-30 09:00+08', '11111111-0000-0000-0000-000000000004', NULL),
    ('33333333-0000-0000-0000-000000000036', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Riverside Book Fair', 'Community event', 'Publisher stalls with author talks through the day.', NULL, '2028-08-23 10:00+08', '2028-08-23 17:00+08', 150, 'AWAITING_SAFETY_CHECK',
     '11111111-0000-0000-0000-000000000004', 'Tower A', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-29 09:00+08', '2026-10-01 09:00+08', '11111111-0000-0000-0000-000000000004', NULL),
    -- 3333..37 and 3333..38: reviewed by the Safety Officer and no longer awaiting the check, for
    -- story 21.1's Accepted and Declined tabs. The 37 was approved and is now Confirmed; the 38
    -- was sent back to Planning and not sent again. Neither has a venue booked.
    ('33333333-0000-0000-0000-000000000037', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Marina Food Festival', 'Community event', 'Food stalls along the waterfront promenade.', NULL, '2028-09-02 11:00+08', '2028-09-02 21:00+08', 200, 'CONFIRMED',
     '11111111-0000-0000-0000-000000000004', 'Tower A', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-25 09:00+08', '2026-09-27 09:00+08', '11111111-0000-0000-0000-000000000004', NULL),
    ('33333333-0000-0000-0000-000000000038', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Lantern Night Walk', 'Community event', 'A guided evening walk with paper lanterns.', NULL, '2028-09-09 19:00+08', '2028-09-09 22:00+08', 80, 'PLANNING',
     '11111111-0000-0000-0000-000000000004', 'Tower B', TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-09-24 09:00+08', '2026-09-26 09:00+08', '11111111-0000-0000-0000-000000000004', NULL),
    -- 3333..39: in planning and assigned to Chloe; dedicated to fix f12.1.2's e2e request that is
    -- really sent (tests/e2e/booking-requests.spec.ts), to Seminar Room 2.1, with a setup that
    -- starts before the room opens at 08:00. One Main venue for 30 people, Classroom with a
    -- projector, so the room suits it. Dated February 2027, so its request sits on the first page
    -- of Venue Staff's Pending tab, which lists the soonest first. That request stays pending, so
    -- tests/e2e/bookings.spec.ts's Alumni Homecoming Weekend card (3333..17) is at worst tenth on
    -- that page: no further pending request dated before September 2027 can be added there.
    ('33333333-0000-0000-0000-000000000039', '11111111-0000-0000-0000-000000000002', '55555555-0000-0000-0000-000000000002',
     'Supplier Induction Morning', 'Supplier onboarding', 'A morning briefing for newly contracted suppliers.', NULL, '2027-02-03 09:00+08', '2027-02-03 12:00+08', 30, 'PLANNING',
     '11111111-0000-0000-0000-000000000003', NULL, TRUE, FALSE, NULL, NULL, 'Omar Organiser', 'organiser@nimbus.example', '+65 6222 3344', '2026-10-12 09:00+08', '2026-10-13 09:00+08', '11111111-0000-0000-0000-000000000003', NULL)
ON CONFLICT (id) DO UPDATE SET
    organiser_id = EXCLUDED.organiser_id, organisation_id = EXCLUDED.organisation_id, name = EXCLUDED.name,
    purpose = EXCLUDED.purpose, description = EXCLUDED.description, cover_image_url = EXCLUDED.cover_image_url,
    starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at,
    expected_attendance = EXCLUDED.expected_attendance, status = EXCLUDED.status,
    assigned_coordinator_id = EXCLUDED.assigned_coordinator_id, preferred_location = EXCLUDED.preferred_location,
    accessibility_none_required = EXCLUDED.accessibility_none_required,
    registration_required = EXCLUDED.registration_required, registration_capacity = EXCLUDED.registration_capacity,
    registration_closes_at = EXCLUDED.registration_closes_at, contact_name = EXCLUDED.contact_name,
    contact_email = EXCLUDED.contact_email, contact_phone = EXCLUDED.contact_phone,
    submitted_at = EXCLUDED.submitted_at, decided_at = EXCLUDED.decided_at,
    decided_by_id = EXCLUDED.decided_by_id, decision_reason = EXCLUDED.decision_reason;

-- Venue requirements (story 2.7). Each sample event that records venue requirements keeps them
-- as one "Main venue" (story 2.7 AC7), with the event's own times and expected attendance - read
-- from the events rows above, so the two cannot drift apart. The draft 3333..01 records none, and
-- 3333..28 (story 8.4) records three of its own, below.
-- These sample events' requirements belong to the seed: any other requirement on them is removed
-- first, so a database migrated by 012 (which gave them a Main venue with a random id) heals to
-- these fixed ids instead of colliding with them on the name or position.
DROP TABLE IF EXISTS pg_temp.sample_venue_requirements;
CREATE TEMP TABLE sample_venue_requirements (id UUID PRIMARY KEY, event_id UUID NOT NULL, layout_code TEXT);
INSERT INTO sample_venue_requirements (id, event_id, layout_code) VALUES
    ('cccccccc-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000002', 'CLASSROOM'),
    ('cccccccc-0000-0000-0000-000000000003', '33333333-0000-0000-0000-000000000003', 'THEATRE'),
    ('cccccccc-0000-0000-0000-000000000004', '33333333-0000-0000-0000-000000000004', 'STANDING'),
    ('cccccccc-0000-0000-0000-000000000005', '33333333-0000-0000-0000-000000000005', 'BOARDROOM'),
    ('cccccccc-0000-0000-0000-000000000006', '33333333-0000-0000-0000-000000000006', 'THEATRE'),
    ('cccccccc-0000-0000-0000-000000000007', '33333333-0000-0000-0000-000000000007', 'STANDING'),
    ('cccccccc-0000-0000-0000-000000000008', '33333333-0000-0000-0000-000000000008', 'EXHIBITION'),
    ('cccccccc-0000-0000-0000-000000000009', '33333333-0000-0000-0000-000000000009', 'THEATRE'),
    ('cccccccc-0000-0000-0000-000000000010', '33333333-0000-0000-0000-000000000010', 'THEATRE'),
    ('cccccccc-0000-0000-0000-000000000011', '33333333-0000-0000-0000-000000000011', 'EXHIBITION'),
    ('cccccccc-0000-0000-0000-000000000016', '33333333-0000-0000-0000-000000000016', 'BANQUET'),
    ('cccccccc-0000-0000-0000-000000000017', '33333333-0000-0000-0000-000000000017', 'EXHIBITION'),
    ('cccccccc-0000-0000-0000-000000000012', '33333333-0000-0000-0000-000000000012', 'THEATRE'),
    ('cccccccc-0000-0000-0000-000000000013', '33333333-0000-0000-0000-000000000013', 'BANQUET'),
    ('cccccccc-0000-0000-0000-000000000014', '33333333-0000-0000-0000-000000000014', 'THEATRE'),
    ('cccccccc-0000-0000-0000-000000000015', '33333333-0000-0000-0000-000000000015', 'STANDING'),
    ('cccccccc-0000-0000-0000-000000000018', '33333333-0000-0000-0000-000000000018', 'CLASSROOM'),
    ('cccccccc-0000-0000-0000-000000000033', '33333333-0000-0000-0000-000000000033', 'CLASSROOM'),
    ('cccccccc-0000-0000-0000-000000000039', '33333333-0000-0000-0000-000000000039', 'CLASSROOM');

DELETE FROM venue_requirements AS r
USING sample_venue_requirements AS sample
WHERE r.event_id = sample.event_id AND r.id <> sample.id
  AND r.id <> 'cccccccc-0000-0000-0003-000000000002'; -- Nimbus's Breakout room, story 12.5's, below

INSERT INTO venue_requirements (id, event_id, position, name, capacity, starts_at, ends_at, layout_code)
SELECT sample.id, e.id, 0, 'Main venue', e.expected_attendance, e.starts_at, e.ends_at, sample.layout_code
FROM sample_venue_requirements AS sample
JOIN events AS e ON e.id = sample.event_id
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, position = EXCLUDED.position, name = EXCLUDED.name,
    capacity = EXCLUDED.capacity, starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at,
    layout_code = EXCLUDED.layout_code, notes = EXCLUDED.notes;

DROP TABLE sample_venue_requirements;

INSERT INTO venue_requirement_facilities (requirement_id, facility_code) VALUES
    ('cccccccc-0000-0000-0000-000000000002', 'PROJECTOR'),
    ('cccccccc-0000-0000-0000-000000000002', 'WIFI'),
    ('cccccccc-0000-0000-0000-000000000003', 'PROJECTOR'),
    ('cccccccc-0000-0000-0000-000000000003', 'SOUND_SYSTEM'),
    ('cccccccc-0000-0000-0000-000000000003', 'STAGE'),
    ('cccccccc-0000-0000-0000-000000000018', 'PROJECTOR'),
    ('cccccccc-0000-0000-0000-000000000033', 'PROJECTOR'),
    ('cccccccc-0000-0000-0000-000000000039', 'PROJECTOR')
ON CONFLICT DO NOTHING;

-- Story 8.4: the Smart Cities Expo (3333..28) records three venue requirements, each with its own
-- times and number of people inside the event's, numbered within their event (cccc..0028-..0N).
-- Each finds different seed venues: the plenary hall only Grand Hall, the breakout room only
-- Seminar Room 2.1, the exhibition space Exhibition Foyer and Grand Hall. Like the Main venues
-- above, they belong to the seed: any other requirement on the event is removed first.
DELETE FROM venue_requirements
WHERE event_id = '33333333-0000-0000-0000-000000000028'
  AND id NOT IN ('cccccccc-0000-0000-0028-000000000001', 'cccccccc-0000-0000-0028-000000000002',
                 'cccccccc-0000-0000-0028-000000000003');

INSERT INTO venue_requirements (id, event_id, position, name, capacity, starts_at, ends_at, layout_code, notes) VALUES
    ('cccccccc-0000-0000-0028-000000000001', '33333333-0000-0000-0000-000000000028', 0, 'Plenary hall', 300,
     '2028-03-14 09:00+08', '2028-03-15 18:00+08', 'THEATRE', 'Keynotes on both mornings.'),
    ('cccccccc-0000-0000-0028-000000000002', '33333333-0000-0000-0000-000000000028', 1, 'Breakout room', 40,
     '2028-03-15 13:00+08', '2028-03-15 17:00+08', 'CLASSROOM', 'Hands-on workshops on the second afternoon.'),
    ('cccccccc-0000-0000-0028-000000000003', '33333333-0000-0000-0000-000000000028', 2, 'Exhibition space', 150,
     '2028-03-14 10:00+08', '2028-03-15 16:00+08', 'EXHIBITION', 'Booths for thirty exhibitors.')
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, position = EXCLUDED.position, name = EXCLUDED.name,
    capacity = EXCLUDED.capacity, starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at,
    layout_code = EXCLUDED.layout_code, notes = EXCLUDED.notes;

-- Story 12.5: Nimbus (3333..03) also needs a breakout room, which its seeded pending request of
-- Seminar Room 2.1 (4444..02, "Breakout track B.") is for: a conference needing a hall and a
-- breakout room raises one request for each.
INSERT INTO venue_requirements (id, event_id, position, name, capacity, starts_at, ends_at, layout_code) VALUES
    ('cccccccc-0000-0000-0003-000000000002', '33333333-0000-0000-0000-000000000003', 1, 'Breakout room', 60,
     '2026-11-25 13:00+08', '2026-11-25 18:00+08', 'CLASSROOM')
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, position = EXCLUDED.position, name = EXCLUDED.name,
    capacity = EXCLUDED.capacity, starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at,
    layout_code = EXCLUDED.layout_code, notes = EXCLUDED.notes;

-- Story 12.5: the Urban Mobility Forum (3333..29) and the Coastal Resilience Workshop (3333..30),
-- numbered like the Expo's. The Forum's Expo hall and Networking lounge both fit Grand Hall and
-- Exhibition Foyer and overlap on 11 April, so a venue held for one drops out for the other
-- (12.5 AC9); its Workshop room fits Seminar Room 2.1. The Workshop's Meeting room is booked
-- below. Like the Expo's, they belong to the seed: any other requirement on them is removed.
DELETE FROM venue_requirements
WHERE event_id IN ('33333333-0000-0000-0000-000000000029', '33333333-0000-0000-0000-000000000030')
  AND id NOT IN ('cccccccc-0000-0000-0029-000000000001', 'cccccccc-0000-0000-0029-000000000002',
                 'cccccccc-0000-0000-0029-000000000003', 'cccccccc-0000-0000-0030-000000000001')
  OR event_id = '33333333-0000-0000-0000-000000000031'
  AND id <> 'cccccccc-0000-0000-0031-000000000001'
  OR event_id = '33333333-0000-0000-0000-000000000032'
  AND id NOT IN ('cccccccc-0000-0000-0032-000000000001', 'cccccccc-0000-0000-0032-000000000002',
                 'cccccccc-0000-0000-0032-000000000003')
  OR event_id = '33333333-0000-0000-0000-000000000034'
  AND id <> 'cccccccc-0000-0000-0034-000000000001'
  OR event_id = '33333333-0000-0000-0000-000000000035'
  AND id <> 'cccccccc-0000-0000-0035-000000000001'
  OR event_id = '33333333-0000-0000-0000-000000000036'
  AND id <> 'cccccccc-0000-0000-0036-000000000001';

INSERT INTO venue_requirements (id, event_id, position, name, capacity, starts_at, ends_at, layout_code, notes) VALUES
    ('cccccccc-0000-0000-0029-000000000001', '33333333-0000-0000-0000-000000000029', 0, 'Expo hall', 200,
     '2028-04-11 09:00+08', '2028-04-12 17:00+08', 'STANDING', 'Stands for transport operators.'),
    ('cccccccc-0000-0000-0029-000000000002', '33333333-0000-0000-0000-000000000029', 1, 'Workshop room', 40,
     '2028-04-12 13:00+08', '2028-04-12 17:00+08', 'CLASSROOM', NULL),
    ('cccccccc-0000-0000-0029-000000000003', '33333333-0000-0000-0000-000000000029', 2, 'Networking lounge', 100,
     '2028-04-11 17:00+08', '2028-04-11 20:00+08', 'STANDING', NULL),
    ('cccccccc-0000-0000-0030-000000000001', '33333333-0000-0000-0000-000000000030', 0, 'Meeting room', 12,
     '2028-06-06 09:00+08', '2028-06-06 12:00+08', 'CLASSROOM', NULL),
    ('cccccccc-0000-0000-0031-000000000001', '33333333-0000-0000-0000-000000000031', 0, 'Training room', 40,
     '2028-05-17 09:00+08', '2028-05-17 17:00+08', 'CLASSROOM', NULL),
    -- The Trade Fair's: the Training room fits Seminar Room 2.1 alone, and the Exhibition area
    -- Exhibition Foyer and Grand Hall, so its request can be switched between them.
    ('cccccccc-0000-0000-0032-000000000001', '33333333-0000-0000-0000-000000000032', 0, 'Welcome reception', 100,
     '2028-07-19 17:00+08', '2028-07-19 20:00+08', 'STANDING', NULL),
    ('cccccccc-0000-0000-0032-000000000002', '33333333-0000-0000-0000-000000000032', 1, 'Training room', 40,
     '2028-07-19 09:00+08', '2028-07-19 12:00+08', 'CLASSROOM', NULL),
    ('cccccccc-0000-0000-0032-000000000003', '33333333-0000-0000-0000-000000000032', 2, 'Exhibition area', 150,
     '2028-07-19 10:00+08', '2028-07-19 16:00+08', 'EXHIBITION', NULL),
    -- Story 12.7: the Community Craft Fair's (3333..34), which Grand Hall and Exhibition Foyer fit.
    ('cccccccc-0000-0000-0034-000000000001', '33333333-0000-0000-0000-000000000034', 0, 'Craft hall', 120,
     '2028-07-12 10:00+08', '2028-07-12 16:00+08', 'EXHIBITION', 'Thirty stalls and a workshop corner.'),
    -- Story 21.1's, each booked below.
    ('cccccccc-0000-0000-0035-000000000001', '33333333-0000-0000-0000-000000000035', 0, 'Concert floor', 300,
     '2028-08-16 18:00+08', '2028-08-16 22:00+08', 'STANDING', NULL),
    ('cccccccc-0000-0000-0036-000000000001', '33333333-0000-0000-0000-000000000036', 0, 'Fair hall', 150,
     '2028-08-23 10:00+08', '2028-08-23 17:00+08', 'EXHIBITION', NULL)
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, position = EXCLUDED.position, name = EXCLUDED.name,
    capacity = EXCLUDED.capacity, starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at,
    layout_code = EXCLUDED.layout_code, notes = EXCLUDED.notes;

INSERT INTO venue_requirement_facilities (requirement_id, facility_code) VALUES
    ('cccccccc-0000-0000-0003-000000000002', 'PROJECTOR'),
    ('cccccccc-0000-0000-0029-000000000001', 'WIFI'),
    ('cccccccc-0000-0000-0029-000000000002', 'PROJECTOR'),
    ('cccccccc-0000-0000-0031-000000000001', 'PROJECTOR'),
    ('cccccccc-0000-0000-0032-000000000002', 'PROJECTOR'),
    ('cccccccc-0000-0000-0032-000000000003', 'WIFI'),
    ('cccccccc-0000-0000-0034-000000000001', 'WIFI'),
    ('cccccccc-0000-0000-0028-000000000001', 'PROJECTOR'),
    ('cccccccc-0000-0000-0028-000000000001', 'SOUND_SYSTEM'),
    ('cccccccc-0000-0000-0028-000000000001', 'STAGE'),
    ('cccccccc-0000-0000-0028-000000000002', 'PROJECTOR'),
    ('cccccccc-0000-0000-0028-000000000003', 'WIFI')
ON CONFLICT DO NOTHING;

INSERT INTO event_accessibility_needs (event_id, feature_code, notes) VALUES
    ('33333333-0000-0000-0000-000000000003', 'WHEELCHAIR_ACCESS', 'Two wheelchair users expected'),
    ('33333333-0000-0000-0000-000000000003', 'HEARING_LOOP', NULL),
    ('33333333-0000-0000-0000-000000000028', 'WHEELCHAIR_ACCESS', NULL),
    ('33333333-0000-0000-0000-000000000029', 'WHEELCHAIR_ACCESS', NULL),
    ('33333333-0000-0000-0000-000000000035', 'WHEELCHAIR_ACCESS', 'A ramp up to the viewing area')
ON CONFLICT DO NOTHING;

INSERT INTO event_equipment_requests (id, event_id, equipment_type_id, quantity, technical_notes, status, created_by_id) VALUES
    ('66666666-0000-0000-0000-000000000001', '33333333-0000-0000-0000-000000000003', '77777777-0000-0000-0000-000000000002', 6, 'Two per breakout room', 'REQUESTED', '11111111-0000-0000-0000-000000000002'),
    ('66666666-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000003', '77777777-0000-0000-0000-000000000004', 2, NULL, 'REQUESTED', '11111111-0000-0000-0000-000000000002'),
    ('66666666-0000-0000-0000-000000000003', '33333333-0000-0000-0000-000000000002', '77777777-0000-0000-0000-000000000001', 1, 'Room already has one; spare requested', 'REQUESTED', '11111111-0000-0000-0000-000000000001')
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, equipment_type_id = EXCLUDED.equipment_type_id, quantity = EXCLUDED.quantity,
    technical_notes = EXCLUDED.technical_notes, status = EXCLUDED.status, created_by_id = EXCLUDED.created_by_id;

-- Story 15.1's e2e items: the organiser's projectors on 3333..19, held since the request was
-- submitted but not yet sent to Technical Support, and a speaker set on 3333..20 the coordinator
-- has already sent. Each holds its units (equipment_reservations below), as every open item on a
-- submitted event does. The older items above predate the hold and hold nothing.
INSERT INTO event_equipment_requests (id, event_id, equipment_type_id, quantity, technical_notes, status, status_notes, created_by_id, submitted_by_id, submitted_at, decided_by_id, decided_at) VALUES
    ('66666666-0000-0000-0000-000000000004', '33333333-0000-0000-0000-000000000019', '77777777-0000-0000-0000-000000000001', 2, 'One for each breakout room', 'REQUESTED', NULL, '11111111-0000-0000-0000-000000000001', NULL, NULL, NULL, NULL),
    ('66666666-0000-0000-0000-000000000005', '33333333-0000-0000-0000-000000000020', '77777777-0000-0000-0000-000000000005', 1, 'For the demo stage', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-24 10:00+08', NULL, NULL),
    -- Story 15.2's e2e items on 3333..21, one per Technical Support tab. Every lapel microphone is
    -- held for the pending item, then four went out of service (below), so it is short by four.
    -- The accepted and declined items stand in for story 16.1's decisions; the declined one holds
    -- nothing and carries Technical Support's reason.
    ('66666666-0000-0000-0000-000000000006', '33333333-0000-0000-0000-000000000021', '77777777-0000-0000-0000-000000000003', 10, 'One per panel speaker', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-26 10:00+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000007', '33333333-0000-0000-0000-000000000021', '77777777-0000-0000-0000-000000000002', 4, 'For audience questions', 'ACCEPTED', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-26 10:00+08', '11111111-0000-0000-0000-000000000006', '2026-09-27 11:00+08'),
    ('66666666-0000-0000-0000-000000000008', '33333333-0000-0000-0000-000000000021', '77777777-0000-0000-0000-000000000001', 3, 'Ceiling-mounted screens preferred', 'DECLINED', 'Every portable projector is out on loan that week.', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-26 10:00+08', '11111111-0000-0000-0000-000000000006', '2026-09-27 11:00+08')
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, equipment_type_id = EXCLUDED.equipment_type_id, quantity = EXCLUDED.quantity,
    technical_notes = EXCLUDED.technical_notes, status = EXCLUDED.status, status_notes = EXCLUDED.status_notes,
    created_by_id = EXCLUDED.created_by_id, submitted_by_id = EXCLUDED.submitted_by_id, submitted_at = EXCLUDED.submitted_at,
    decided_by_id = EXCLUDED.decided_by_id, decided_at = EXCLUDED.decided_at;

-- More of story 15.2's queue, on 3333..22-26: mostly pending, some accepted, a few declined with
-- Technical Support's reason, each sent by its event's coordinator. Every item but a declined one
-- holds its units (equipment_reservations below).
INSERT INTO event_equipment_requests (id, event_id, equipment_type_id, quantity, technical_notes, status, status_notes, created_by_id, submitted_by_id, submitted_at, decided_by_id, decided_at) VALUES
    ('66666666-0000-0000-0000-000000000009', '33333333-0000-0000-0000-000000000022', '77777777-0000-0000-0000-000000000002', 6, 'Two per panel table', 'PENDING', NULL, '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-01 09:30+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000010', '33333333-0000-0000-0000-000000000022', '77777777-0000-0000-0000-000000000001', 2, 'Main stage and the overflow room', 'PENDING', NULL, '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-01 09:30+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000011', '33333333-0000-0000-0000-000000000022', '77777777-0000-0000-0000-000000000004', 1, 'Backup for the keynote speaker', 'DECLINED', 'The venue''s lectern has a presentation PC.', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-01 09:30+08', '11111111-0000-0000-0000-000000000006', '2026-10-02 10:30+08'),
    ('66666666-0000-0000-0000-000000000012', '33333333-0000-0000-0000-000000000023', '77777777-0000-0000-0000-000000000002', 12, 'Roaming microphones for audience questions', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-02 14:00+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000013', '33333333-0000-0000-0000-000000000023', '77777777-0000-0000-0000-000000000005', 2, NULL, 'ACCEPTED', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-02 14:00+08', '11111111-0000-0000-0000-000000000006', '2026-10-03 15:00+08'),
    ('66666666-0000-0000-0000-000000000014', '33333333-0000-0000-0000-000000000023', '77777777-0000-0000-0000-000000000003', 4, 'For the four workshop leads', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-02 14:00+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000015', '33333333-0000-0000-0000-000000000024', '77777777-0000-0000-0000-000000000001', 5, 'One per breakout room, plus the main hall', 'PENDING', NULL, '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-03 11:15+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000016', '33333333-0000-0000-0000-000000000024', '77777777-0000-0000-0000-000000000005', 3, NULL, 'PENDING', NULL, '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-03 11:15+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000017', '33333333-0000-0000-0000-000000000024', '77777777-0000-0000-0000-000000000002', 8, 'Awards segment', 'ACCEPTED', NULL, '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-03 11:15+08', '11111111-0000-0000-0000-000000000006', '2026-10-04 12:15+08'),
    ('66666666-0000-0000-0000-000000000018', '33333333-0000-0000-0000-000000000024', '77777777-0000-0000-0000-000000000006', 3, 'Recording the keynote and the awards', 'PENDING', NULL, '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-03 11:15+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000019', '33333333-0000-0000-0000-000000000025', '77777777-0000-0000-0000-000000000004', 4, 'Candidate registration desks', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-04 16:40+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000020', '33333333-0000-0000-0000-000000000025', '77777777-0000-0000-0000-000000000001', 1, NULL, 'DECLINED', 'Every hall booked for the fair has a fixed projector.', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-04 16:40+08', '11111111-0000-0000-0000-000000000006', '2026-10-05 17:40+08'),
    ('66666666-0000-0000-0000-000000000021', '33333333-0000-0000-0000-000000000025', '77777777-0000-0000-0000-000000000008', 2, 'Remote interview booths', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-04 16:40+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000022', '33333333-0000-0000-0000-000000000026', '77777777-0000-0000-0000-000000000005', 4, 'Dinner music and speeches', 'ACCEPTED', NULL, '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-05 10:00+08', '11111111-0000-0000-0000-000000000006', '2026-10-06 11:00+08'),
    ('66666666-0000-0000-0000-000000000023', '33333333-0000-0000-0000-000000000026', '77777777-0000-0000-0000-000000000007', 2, 'Either side of the stage', 'ACCEPTED', NULL, '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-05 10:00+08', '11111111-0000-0000-0000-000000000006', '2026-10-06 11:00+08'),
    ('66666666-0000-0000-0000-000000000024', '33333333-0000-0000-0000-000000000026', '77777777-0000-0000-0000-000000000002', 3, NULL, 'DECLINED', 'The venue''s own microphones cover the gala.', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-05 10:00+08', '11111111-0000-0000-0000-000000000006', '2026-10-06 11:00+08'),
    -- Story 16.1's e2e items on 3333..27: all pending, one per spec case, each a different type
    -- so no decision changes another's figures. The laptops are never decided. The projectors and
    -- wireless microphones are decided from the request's own page. The video camera is accepted
    -- from a second page while the first still offers a decision.
    ('66666666-0000-0000-0000-000000000029', '33333333-0000-0000-0000-000000000027', '77777777-0000-0000-0000-000000000001', 2, 'Both breakout rooms', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000030', '33333333-0000-0000-0000-000000000027', '77777777-0000-0000-0000-000000000002', 4, 'Panel questions', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000025', '33333333-0000-0000-0000-000000000027', '77777777-0000-0000-0000-000000000005', 2, 'Breakout sessions', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000026', '33333333-0000-0000-0000-000000000027', '77777777-0000-0000-0000-000000000007', 1, 'For the strategy wall', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000031', '33333333-0000-0000-0000-000000000027', '77777777-0000-0000-0000-000000000006', 1, 'Recording the closing panel', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000027', '33333333-0000-0000-0000-000000000027', '77777777-0000-0000-0000-000000000008', 2, 'Remote board members dial in', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', NULL, NULL),
    ('66666666-0000-0000-0000-000000000028', '33333333-0000-0000-0000-000000000027', '77777777-0000-0000-0000-000000000004', 2, 'Facilitator slides', 'PENDING', NULL, '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', NULL, NULL),
    -- Story 21.1's: accepted, with the technical notes the Safety Officer reads.
    ('66666666-0000-0000-0000-000000000032', '33333333-0000-0000-0000-000000000035', '77777777-0000-0000-0000-000000000005', 2, 'Stage left and right; cables taped down', 'ACCEPTED', NULL, '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-02 09:00+08', '11111111-0000-0000-0000-000000000006', '2026-10-03 09:00+08'),
    ('66666666-0000-0000-0000-000000000033', '33333333-0000-0000-0000-000000000036', '77777777-0000-0000-0000-000000000002', 4, 'Author talks', 'ACCEPTED', NULL, '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-10-02 10:00+08', '11111111-0000-0000-0000-000000000006', '2026-10-03 10:00+08')
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, equipment_type_id = EXCLUDED.equipment_type_id, quantity = EXCLUDED.quantity,
    technical_notes = EXCLUDED.technical_notes, status = EXCLUDED.status, status_notes = EXCLUDED.status_notes,
    created_by_id = EXCLUDED.created_by_id, submitted_by_id = EXCLUDED.submitted_by_id, submitted_at = EXCLUDED.submitted_at,
    decided_by_id = EXCLUDED.decided_by_id, decided_at = EXCLUDED.decided_at;

INSERT INTO equipment_reservations (id, event_id, equipment_request_id, equipment_type_id, quantity, starts_at, ends_at, status, reserved_by_id, reserved_at, notes) VALUES
    ('eeeeeeee-0000-0000-0000-000000000001', '33333333-0000-0000-0000-000000000019', '66666666-0000-0000-0000-000000000004', '77777777-0000-0000-0000-000000000001', 2,
     '2027-05-12 09:00+08', '2027-05-12 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000001', '2026-09-20 09:00+08', 'Held when the request was submitted.'),
    ('eeeeeeee-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000020', '66666666-0000-0000-0000-000000000005', '77777777-0000-0000-0000-000000000005', 1,
     '2027-05-19 09:00+08', '2027-05-19 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-09-24 10:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000003', '33333333-0000-0000-0000-000000000021', '66666666-0000-0000-0000-000000000006', '77777777-0000-0000-0000-000000000003', 10,
     '2027-06-16 09:00+08', '2027-06-16 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-09-26 10:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000004', '33333333-0000-0000-0000-000000000021', '66666666-0000-0000-0000-000000000007', '77777777-0000-0000-0000-000000000002', 4,
     '2027-06-16 09:00+08', '2027-06-16 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-09-26 10:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000005', '33333333-0000-0000-0000-000000000022', '66666666-0000-0000-0000-000000000009', '77777777-0000-0000-0000-000000000002', 6,
     '2027-07-07 08:00+08', '2027-07-07 11:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000004', '2026-10-01 09:30+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000006', '33333333-0000-0000-0000-000000000022', '66666666-0000-0000-0000-000000000010', '77777777-0000-0000-0000-000000000001', 2,
     '2027-07-07 08:00+08', '2027-07-07 11:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000004', '2026-10-01 09:30+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000007', '33333333-0000-0000-0000-000000000023', '66666666-0000-0000-0000-000000000012', '77777777-0000-0000-0000-000000000002', 12,
     '2027-07-07 10:00+08', '2027-07-07 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-02 14:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000008', '33333333-0000-0000-0000-000000000023', '66666666-0000-0000-0000-000000000013', '77777777-0000-0000-0000-000000000005', 2,
     '2027-07-07 10:00+08', '2027-07-07 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-02 14:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000009', '33333333-0000-0000-0000-000000000023', '66666666-0000-0000-0000-000000000014', '77777777-0000-0000-0000-000000000003', 4,
     '2027-07-07 10:00+08', '2027-07-07 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-02 14:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000010', '33333333-0000-0000-0000-000000000024', '66666666-0000-0000-0000-000000000015', '77777777-0000-0000-0000-000000000001', 5,
     '2027-08-18 09:00+08', '2027-08-18 18:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000004', '2026-10-03 11:15+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000011', '33333333-0000-0000-0000-000000000024', '66666666-0000-0000-0000-000000000016', '77777777-0000-0000-0000-000000000005', 3,
     '2027-08-18 09:00+08', '2027-08-18 18:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000004', '2026-10-03 11:15+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000012', '33333333-0000-0000-0000-000000000024', '66666666-0000-0000-0000-000000000017', '77777777-0000-0000-0000-000000000002', 8,
     '2027-08-18 09:00+08', '2027-08-18 18:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000004', '2026-10-03 11:15+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000013', '33333333-0000-0000-0000-000000000024', '66666666-0000-0000-0000-000000000018', '77777777-0000-0000-0000-000000000006', 3,
     '2027-08-18 09:00+08', '2027-08-18 18:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000004', '2026-10-03 11:15+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000014', '33333333-0000-0000-0000-000000000025', '66666666-0000-0000-0000-000000000019', '77777777-0000-0000-0000-000000000004', 4,
     '2027-09-22 10:00+08', '2027-09-22 16:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-04 16:40+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000015', '33333333-0000-0000-0000-000000000025', '66666666-0000-0000-0000-000000000021', '77777777-0000-0000-0000-000000000008', 2,
     '2027-09-22 10:00+08', '2027-09-22 16:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-04 16:40+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000016', '33333333-0000-0000-0000-000000000026', '66666666-0000-0000-0000-000000000022', '77777777-0000-0000-0000-000000000005', 4,
     '2027-11-26 18:00+08', '2027-11-26 23:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000004', '2026-10-05 10:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000017', '33333333-0000-0000-0000-000000000026', '66666666-0000-0000-0000-000000000023', '77777777-0000-0000-0000-000000000007', 2,
     '2027-11-26 18:00+08', '2027-11-26 23:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000004', '2026-10-05 10:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000018', '33333333-0000-0000-0000-000000000027', '66666666-0000-0000-0000-000000000025', '77777777-0000-0000-0000-000000000005', 2,
     '2027-12-08 09:00+08', '2027-12-09 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000019', '33333333-0000-0000-0000-000000000027', '66666666-0000-0000-0000-000000000026', '77777777-0000-0000-0000-000000000007', 1,
     '2027-12-08 09:00+08', '2027-12-09 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000020', '33333333-0000-0000-0000-000000000027', '66666666-0000-0000-0000-000000000027', '77777777-0000-0000-0000-000000000008', 2,
     '2027-12-08 09:00+08', '2027-12-09 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000021', '33333333-0000-0000-0000-000000000027', '66666666-0000-0000-0000-000000000028', '77777777-0000-0000-0000-000000000004', 2,
     '2027-12-08 09:00+08', '2027-12-09 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000022', '33333333-0000-0000-0000-000000000027', '66666666-0000-0000-0000-000000000029', '77777777-0000-0000-0000-000000000001', 2,
     '2027-12-08 09:00+08', '2027-12-09 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000023', '33333333-0000-0000-0000-000000000027', '66666666-0000-0000-0000-000000000030', '77777777-0000-0000-0000-000000000002', 4,
     '2027-12-08 09:00+08', '2027-12-09 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000024', '33333333-0000-0000-0000-000000000027', '66666666-0000-0000-0000-000000000031', '77777777-0000-0000-0000-000000000006', 1,
     '2027-12-08 09:00+08', '2027-12-09 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000003', '2026-10-05 15:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000025', '33333333-0000-0000-0000-000000000035', '66666666-0000-0000-0000-000000000032', '77777777-0000-0000-0000-000000000005', 2,
     '2028-08-16 18:00+08', '2028-08-16 22:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000004', '2026-10-02 09:00+08', 'Held for the coordinator''s equipment request.'),
    ('eeeeeeee-0000-0000-0000-000000000026', '33333333-0000-0000-0000-000000000036', '66666666-0000-0000-0000-000000000033', '77777777-0000-0000-0000-000000000002', 4,
     '2028-08-23 10:00+08', '2028-08-23 17:00+08', 'RESERVED', '11111111-0000-0000-0000-000000000004', '2026-10-02 10:00+08', 'Held for the coordinator''s equipment request.')
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, equipment_request_id = EXCLUDED.equipment_request_id,
    equipment_type_id = EXCLUDED.equipment_type_id, quantity = EXCLUDED.quantity,
    starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at, status = EXCLUDED.status,
    reserved_by_id = EXCLUDED.reserved_by_id, reserved_at = EXCLUDED.reserved_at,
    released_at = NULL, released_quantity = 0, notes = EXCLUDED.notes;

-- Every video camera is out of service over 3333..20's dates, so story 15.1's e2e spec finds a
-- type with none available. Four lapel microphones are out of service over 3333..21's, after
-- its pending item held all ten, so story 15.2's e2e spec finds a shortfall.
INSERT INTO equipment_unavailability_periods (id, equipment_type_id, quantity, reason, starts_at, ends_at, notes, created_by_id) VALUES
    ('dddddddd-0000-0000-0000-000000000001', '77777777-0000-0000-0000-000000000006', 4, 'MAINTENANCE',
     '2027-05-17 00:00+08', '2027-05-22 00:00+08', 'Sensor cleaning and firmware update', '11111111-0000-0000-0000-000000000006'),
    ('dddddddd-0000-0000-0000-000000000002', '77777777-0000-0000-0000-000000000003', 4, 'MAINTENANCE',
     '2027-06-14 00:00+08', '2027-06-18 00:00+08', 'Capsule replacement', '11111111-0000-0000-0000-000000000006'),
    -- Two video cameras are out over 3333..24's day, after its three were held: short by one.
    ('dddddddd-0000-0000-0000-000000000003', '77777777-0000-0000-0000-000000000006', 2, 'DAMAGED',
     '2027-08-16 00:00+08', '2027-08-20 00:00+08', 'Cracked lens housings', '11111111-0000-0000-0000-000000000006')
ON CONFLICT (id) DO UPDATE SET
    equipment_type_id = EXCLUDED.equipment_type_id, quantity = EXCLUDED.quantity, reason = EXCLUDED.reason,
    starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at, notes = EXCLUDED.notes;

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
    ('99999999-0000-0000-0000-000000000009', '33333333-0000-0000-0000-000000000004', 'SUBMITTED', 'REJECTED', '11111111-0000-0000-0000-000000000004', '2026-09-07 11:00+08', 'No outdoor venues are available after 22:00.'),
    ('99999999-0000-0000-0000-000000000010', '33333333-0000-0000-0000-000000000005', NULL, 'DRAFT', '11111111-0000-0000-0000-000000000002', '2026-09-09 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000011', '33333333-0000-0000-0000-000000000005', 'DRAFT', 'SUBMITTED', '11111111-0000-0000-0000-000000000002', '2026-09-10 08:00+08', NULL),
    ('99999999-0000-0000-0000-000000000012', '33333333-0000-0000-0000-000000000005', 'SUBMITTED', 'UNDER_REVIEW', '11111111-0000-0000-0000-000000000003', '2026-09-11 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000013', '33333333-0000-0000-0000-000000000006', NULL, 'DRAFT', '11111111-0000-0000-0000-000000000001', '2026-09-02 15:00+08', NULL),
    ('99999999-0000-0000-0000-000000000014', '33333333-0000-0000-0000-000000000006', 'DRAFT', 'SUBMITTED', '11111111-0000-0000-0000-000000000001', '2026-09-03 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000015', '33333333-0000-0000-0000-000000000006', 'SUBMITTED', 'CLARIFICATION_REQUESTED', '11111111-0000-0000-0000-000000000003', '2026-09-04 10:00+08', 'Please add expected headcount by department.'),
    ('99999999-0000-0000-0000-000000000016', '33333333-0000-0000-0000-000000000007', NULL, 'DRAFT', '11111111-0000-0000-0000-000000000001', '2026-09-14 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000017', '33333333-0000-0000-0000-000000000007', 'DRAFT', 'SUBMITTED', '11111111-0000-0000-0000-000000000001', '2026-09-15 14:00+08', NULL),
    -- 3333..12-15: the last transition into their current status only - full history back to
    -- DRAFT is not needed for any test today (story 6.4 owns displaying the full history).
    ('99999999-0000-0000-0000-000000000018', '33333333-0000-0000-0000-000000000012', 'APPROVED', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-09-14 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000019', '33333333-0000-0000-0000-000000000013', 'PLANNING', 'CONFIRMED', '11111111-0000-0000-0000-000000000003', '2026-09-15 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000020', '33333333-0000-0000-0000-000000000014', 'CONFIRMED', 'COMPLETED', '11111111-0000-0000-0000-000000000003', '2026-08-01 12:00+08', NULL),
    ('99999999-0000-0000-0000-000000000021', '33333333-0000-0000-0000-000000000015', 'CONFIRMED', 'CANCELLED', '11111111-0000-0000-0000-000000000003', '2026-08-27 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000022', '33333333-0000-0000-0000-000000000018', 'APPROVED', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-09-18 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000023', '33333333-0000-0000-0000-000000000019', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-09-22 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000024', '33333333-0000-0000-0000-000000000020', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-09-23 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000025', '33333333-0000-0000-0000-000000000021', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-09-25 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000026', '33333333-0000-0000-0000-000000000022', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000004', '2026-09-28 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000027', '33333333-0000-0000-0000-000000000023', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-09-28 10:00+08', NULL),
    ('99999999-0000-0000-0000-000000000028', '33333333-0000-0000-0000-000000000024', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000004', '2026-09-29 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000029', '33333333-0000-0000-0000-000000000025', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-09-30 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000030', '33333333-0000-0000-0000-000000000026', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000004', '2026-10-01 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000031', '33333333-0000-0000-0000-000000000027', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-10-03 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000032', '33333333-0000-0000-0000-000000000028', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-10-07 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000033', '33333333-0000-0000-0000-000000000029', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-10-08 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000034', '33333333-0000-0000-0000-000000000030', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-10-08 10:00+08', NULL),
    ('99999999-0000-0000-0000-000000000035', '33333333-0000-0000-0000-000000000031', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-10-08 11:00+08', NULL),
    ('99999999-0000-0000-0000-000000000036', '33333333-0000-0000-0000-000000000032', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-10-08 12:00+08', NULL),
    ('99999999-0000-0000-0000-000000000037', '33333333-0000-0000-0000-000000000033', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-10-11 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000038', '33333333-0000-0000-0000-000000000034', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-09-26 09:00+08', NULL),
    -- Story 21.1: the 35 entered the safety check before the 36 last did, so it leads the queue.
    -- The 36 was sent back once, then sent again.
    ('99999999-0000-0000-0000-000000000039', '33333333-0000-0000-0000-000000000035', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000004', '2026-09-30 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000040', '33333333-0000-0000-0000-000000000035', 'PLANNING', 'AWAITING_SAFETY_CHECK', '11111111-0000-0000-0000-000000000004', '2026-10-10 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000041', '33333333-0000-0000-0000-000000000036', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000004', '2026-10-01 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000042', '33333333-0000-0000-0000-000000000036', 'PLANNING', 'AWAITING_SAFETY_CHECK', '11111111-0000-0000-0000-000000000004', '2026-10-06 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000043', '33333333-0000-0000-0000-000000000036', 'AWAITING_SAFETY_CHECK', 'PLANNING', '11111111-0000-0000-0000-000000000009', '2026-10-07 15:00+08', 'Confirm the attendance and the microphones.'),
    ('99999999-0000-0000-0000-000000000044', '33333333-0000-0000-0000-000000000036', 'PLANNING', 'AWAITING_SAFETY_CHECK', '11111111-0000-0000-0000-000000000004', '2026-10-11 09:00+08', NULL),
    -- The 37 entered the check on 5 Oct and was approved; the 38 entered on 4 Oct and was sent back.
    ('99999999-0000-0000-0000-000000000045', '33333333-0000-0000-0000-000000000037', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000004', '2026-09-27 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000046', '33333333-0000-0000-0000-000000000037', 'PLANNING', 'AWAITING_SAFETY_CHECK', '11111111-0000-0000-0000-000000000004', '2026-10-05 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000047', '33333333-0000-0000-0000-000000000037', 'AWAITING_SAFETY_CHECK', 'CONFIRMED', '11111111-0000-0000-0000-000000000009', '2026-10-09 10:00+08', NULL),
    ('99999999-0000-0000-0000-000000000048', '33333333-0000-0000-0000-000000000038', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000004', '2026-09-26 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000049', '33333333-0000-0000-0000-000000000038', 'PLANNING', 'AWAITING_SAFETY_CHECK', '11111111-0000-0000-0000-000000000004', '2026-10-04 09:00+08', NULL),
    ('99999999-0000-0000-0000-000000000050', '33333333-0000-0000-0000-000000000038', 'AWAITING_SAFETY_CHECK', 'PLANNING', '11111111-0000-0000-0000-000000000009', '2026-10-08 10:00+08', 'Add marshals at each road crossing.'),
    -- 3333..39 (fix f12.1.2's e2e event).
    ('99999999-0000-0000-0000-000000000051', '33333333-0000-0000-0000-000000000039', 'UNDER_REVIEW', 'PLANNING', '11111111-0000-0000-0000-000000000003', '2026-10-13 09:00+08', NULL)
ON CONFLICT (id) DO NOTHING;

INSERT INTO event_coordinator_assignments (id, event_id, coordinator_id, assigned_by_id, assigned_at) VALUES
    ('aaaaaaaa-0000-0000-0000-000000000001', '33333333-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-02 09:30+08'),
    ('aaaaaaaa-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-06 09:00+08'),
    -- Assigned automatically on submission: no human assigner.
    ('aaaaaaaa-0000-0000-0000-000000000003', '33333333-0000-0000-0000-000000000002', '11111111-0000-0000-0000-000000000003', NULL, '2026-09-08 10:15+08'),
    ('aaaaaaaa-0000-0000-0000-000000000004', '33333333-0000-0000-0000-000000000005', '11111111-0000-0000-0000-000000000003', NULL, '2026-09-10 08:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000005', '33333333-0000-0000-0000-000000000006', '11111111-0000-0000-0000-000000000003', NULL, '2026-09-03 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000006', '33333333-0000-0000-0000-000000000007', '11111111-0000-0000-0000-000000000003', NULL, '2026-09-15 14:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000007', '33333333-0000-0000-0000-000000000012', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-12 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000008', '33333333-0000-0000-0000-000000000013', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-13 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000009', '33333333-0000-0000-0000-000000000014', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-06-20 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000010', '33333333-0000-0000-0000-000000000015', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-08-25 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000011', '33333333-0000-0000-0000-000000000018', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-16 09:00+08'),
    -- Story 5.2: events 08/09/10/11/16/17 set events.assigned_coordinator_id directly (seeded
    -- before story 5.1's assignment history existed) but had no matching open row here, so
    -- current_assignment() saw them as unassigned - silently skipping AC4's exclusion and AC6's
    -- permission check for exactly these six events. Backfilled with the same self-assigned
    -- shape (assigned_by = coordinator, assigned_at = the event's own submitted_at) already used
    -- for 03/12/13/14/15/18 above.
    ('aaaaaaaa-0000-0000-0000-000000000012', '33333333-0000-0000-0000-000000000008', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-10 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000013', '33333333-0000-0000-0000-000000000009', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-14 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000014', '33333333-0000-0000-0000-000000000010', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-10 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000015', '33333333-0000-0000-0000-000000000011', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-11 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000016', '33333333-0000-0000-0000-000000000016', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-12 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000017', '33333333-0000-0000-0000-000000000017', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-13 09:00+08'),
    -- Story 15.1's e2e events, assigned automatically on submission: no human assigner.
    ('aaaaaaaa-0000-0000-0000-000000000018', '33333333-0000-0000-0000-000000000019', '11111111-0000-0000-0000-000000000003', NULL, '2026-09-20 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000019', '33333333-0000-0000-0000-000000000020', '11111111-0000-0000-0000-000000000003', NULL, '2026-09-21 09:00+08'),
    -- Story 15.2's e2e event, likewise.
    ('aaaaaaaa-0000-0000-0000-000000000020', '33333333-0000-0000-0000-000000000021', '11111111-0000-0000-0000-000000000003', NULL, '2026-09-24 09:00+08'),
    -- 3333..22-26: self-assigned, as 03/12/13 are, so they do not move story 5.1's round robin,
    -- which continues from the last automatic assignment.
    ('aaaaaaaa-0000-0000-0000-000000000021', '33333333-0000-0000-0000-000000000022', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-27 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000022', '33333333-0000-0000-0000-000000000023', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-27 10:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000023', '33333333-0000-0000-0000-000000000024', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-28 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000024', '33333333-0000-0000-0000-000000000025', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-29 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000025', '33333333-0000-0000-0000-000000000026', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-30 09:00+08'),
    -- 3333..27 (story 16.1's e2e event): self-assigned too, for the same reason.
    ('aaaaaaaa-0000-0000-0000-000000000026', '33333333-0000-0000-0000-000000000027', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-02 09:00+08'),
    -- 3333..28 (story 8.4's e2e event): self-assigned too, for the same reason.
    ('aaaaaaaa-0000-0000-0000-000000000027', '33333333-0000-0000-0000-000000000028', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-05 09:00+08'),
    -- 3333..29 and 3333..30 (story 12.5's e2e events): self-assigned too.
    ('aaaaaaaa-0000-0000-0000-000000000028', '33333333-0000-0000-0000-000000000029', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-06 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000029', '33333333-0000-0000-0000-000000000030', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-06 10:00+08'),
    -- 3333..31 (12.1's real send since story 12.5): self-assigned too.
    ('aaaaaaaa-0000-0000-0000-000000000030', '33333333-0000-0000-0000-000000000031', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-06 11:00+08'),
    -- 3333..32 (12.5's withdraw-and-switch flow): self-assigned too.
    ('aaaaaaaa-0000-0000-0000-000000000031', '33333333-0000-0000-0000-000000000032', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-06 12:00+08'),
    -- 3333..33 (11.1's justified real send since story 12.5): self-assigned too.
    ('aaaaaaaa-0000-0000-0000-000000000032', '33333333-0000-0000-0000-000000000033', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-09 09:00+08'),
    -- 3333..34 (story 12.7's e2e event): self-assigned too.
    ('aaaaaaaa-0000-0000-0000-000000000033', '33333333-0000-0000-0000-000000000034', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-09-24 09:00+08'),
    -- 3333..35 and 3333..36 (story 21.1's): self-assigned too.
    ('aaaaaaaa-0000-0000-0000-000000000034', '33333333-0000-0000-0000-000000000035', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-28 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000035', '33333333-0000-0000-0000-000000000036', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-29 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000036', '33333333-0000-0000-0000-000000000037', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-25 09:00+08'),
    ('aaaaaaaa-0000-0000-0000-000000000037', '33333333-0000-0000-0000-000000000038', '11111111-0000-0000-0000-000000000004', '11111111-0000-0000-0000-000000000004', '2026-09-24 09:00+08'),
    -- 3333..39 (fix f12.1.2's real send with a setup): self-assigned too.
    ('aaaaaaaa-0000-0000-0000-000000000038', '33333333-0000-0000-0000-000000000039', '11111111-0000-0000-0000-000000000003', '11111111-0000-0000-0000-000000000003', '2026-10-12 09:00+08')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- Clarification conversation on the CLARIFICATION_REQUESTED event (story 4.6)
-- ---------------------------------------------------------------------
INSERT INTO event_clarifications (id, event_id, author_id, kind, message, created_at) VALUES
    ('bbbbbbbb-0000-0000-0000-000000000001', '33333333-0000-0000-0000-000000000006', '11111111-0000-0000-0000-000000000003', 'REQUEST',
     'Please add expected headcount by department.', '2026-09-04 10:00+08'),
    ('bbbbbbbb-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000006', '11111111-0000-0000-0000-000000000001', 'RESPONSE',
     'About 60 from Engineering, 50 from Sales and 40 from Operations.', '2026-09-05 14:30+08')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- Venue bookings: one APPROVED (blocks Grand Hall on 25 Nov), three PENDING across three
-- different events and dates (story 13.1: the queue needs more than one row that all look
-- alike), plus two more PENDING rows dedicated to the story 13.2 approve e2e test and two more
-- again dedicated to the story 13.2.1 reject e2e test (see their own notes below). Never
-- Boardroom 3.4 - test_venue_records.py::test_deleting_a_venue_removes_its_characteristics
-- deletes it on the assumption that it carries no bookings. ``created_at`` is given an explicit,
-- staggered value per row (each after its event was approved, as story 12.1 AC1 requires, and
-- before its own ``starts_at``) rather than left to the column's
-- ``now()`` default, so the queue's "Requested" timestamp (story 13.1 AC2) doesn't show every
-- seed row landing in the same instant a bulk insert would otherwise give them.
-- ---------------------------------------------------------------------
-- Story 12.7 (the customer's hold, 12 Oct 2026, R11): the approved booking's hold lasts until the
-- start of its booked period, setup included - the latest AC5 allows - so a development database
-- that is not re-seeded keeps it booked. A pending request has no hold to expire.
INSERT INTO venue_bookings (id, event_id, venue_id, requested_by_id, starts_at, ends_at, setup_minutes, teardown_minutes,
                            expected_attendance, required_layout_code, requirement_notes, status, decided_by_id, decided_at, decision_reason, created_at,
                            hold_expires_at) VALUES
    ('44444444-0000-0000-0000-000000000001', '33333333-0000-0000-0000-000000000003', '22222222-0000-0000-0000-000000000001',
     '11111111-0000-0000-0000-000000000003', '2026-11-25 09:00+08', '2026-11-25 18:00+08', 60, 60,
     350, 'THEATRE', 'Projector, sound system and stage required.', 'APPROVED', '11111111-0000-0000-0000-000000000005', '2026-09-04 10:00+08', NULL, '2026-09-03 16:00+08',
     '2026-11-25 08:00+08'),
    ('44444444-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000003', '22222222-0000-0000-0000-000000000002',
     '11111111-0000-0000-0000-000000000003', '2026-11-25 13:00+08', '2026-11-25 18:00+08', 30, 15,
     60, 'CLASSROOM', 'Breakout track B.', 'PENDING', NULL, NULL, NULL, '2026-09-03 16:47+08',
     NULL),
    ('44444444-0000-0000-0000-000000000003', '33333333-0000-0000-0000-000000000008', '22222222-0000-0000-0000-000000000004',
     '11111111-0000-0000-0000-000000000004', '2026-12-03 09:00+08', '2026-12-03 17:00+08', 45, 45,
     180, 'EXHIBITION', 'Wellness booths, a quiet room, and a stage for the keynote.', 'PENDING', NULL, NULL, NULL, '2026-09-12 11:03+08',
     NULL),
    ('44444444-0000-0000-0000-000000000004', '33333333-0000-0000-0000-000000000009', '22222222-0000-0000-0000-000000000001',
     '11111111-0000-0000-0000-000000000003', '2027-01-15 10:00+08', '2027-01-15 12:00+08', 60, 60,
     300, 'THEATRE', 'Livestream feed for remote offices; two roaming microphones.', 'PENDING', NULL, NULL, NULL, '2026-09-18 16:30+08',
     NULL),
    -- Dedicated to the story 13.2 approve e2e test - see 3333..10/11's note above. Distinct
    -- venues, dates and events from every other booking, so approving them cannot conflict
    -- with anything and cannot affect any other test's assertions.
    ('44444444-0000-0000-0000-000000000005', '33333333-0000-0000-0000-000000000010', '22222222-0000-0000-0000-000000000001',
     '11111111-0000-0000-0000-000000000003', '2027-06-01 15:00+08', '2027-06-01 17:00+08', 30, 30,
     200, 'THEATRE', 'Stage mics and a roaming mic for Q&A.', 'PENDING', NULL, NULL, NULL, '2026-09-20 08:00+08',
     NULL),
    ('44444444-0000-0000-0000-000000000006', '33333333-0000-0000-0000-000000000011', '22222222-0000-0000-0000-000000000004',
     '11111111-0000-0000-0000-000000000004', '2027-07-01 09:00+08', '2027-07-01 12:00+08', 45, 30,
     100, 'EXHIBITION', 'Demo booths and a screen for the product walkthrough.', 'PENDING', NULL, NULL, NULL, '2026-09-21 08:00+08',
     NULL),
    -- Dedicated to the story 13.2.1 reject e2e test - see 3333..16/17's note above. Distinct
    -- venues, dates and events from every other booking, so rejecting them cannot conflict with
    -- anything and cannot affect any other test's assertions.
    ('44444444-0000-0000-0000-000000000007', '33333333-0000-0000-0000-000000000016', '22222222-0000-0000-0000-000000000001',
     '11111111-0000-0000-0000-000000000003', '2027-08-01 18:00+08', '2027-08-01 22:00+08', 45, 45,
     220, 'BANQUET', 'Stage, PA system and a dance floor.', 'PENDING', NULL, NULL, NULL, '2026-09-22 08:00+08',
     NULL),
    ('44444444-0000-0000-0000-000000000008', '33333333-0000-0000-0000-000000000017', '22222222-0000-0000-0000-000000000004',
     '11111111-0000-0000-0000-000000000004', '2027-09-01 09:00+08', '2027-09-01 17:00+08', 45, 30,
     100, 'EXHIBITION', 'Registration desk and campus tour meeting point.', 'PENDING', NULL, NULL, NULL, '2026-09-23 08:00+08',
     NULL)
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, venue_id = EXCLUDED.venue_id, requested_by_id = EXCLUDED.requested_by_id,
    starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at, setup_minutes = EXCLUDED.setup_minutes,
    teardown_minutes = EXCLUDED.teardown_minutes, expected_attendance = EXCLUDED.expected_attendance,
    required_layout_code = EXCLUDED.required_layout_code, requirement_notes = EXCLUDED.requirement_notes,
    status = EXCLUDED.status, decided_by_id = EXCLUDED.decided_by_id, decided_at = EXCLUDED.decided_at,
    decision_reason = EXCLUDED.decision_reason, created_at = EXCLUDED.created_at,
    hold_expires_at = EXCLUDED.hold_expires_at, hold_reminded_at = NULL, hold_completed_at = NULL;

-- Story 12.5: the Coastal Resilience Workshop's (3333..30) one venue requirement, already booked:
-- Seminar Room 2.1, approved by Vera. Its e2e spec reads the "All required venues booked" state
-- and requests an additional venue beside it. Not Boardroom 3.4, which story 8.3's tests delete.
-- Story 12.7 (R11): its hold lasts until its booked start, as the approved booking's above does.
INSERT INTO venue_bookings (id, event_id, venue_id, requested_by_id, starts_at, ends_at, setup_minutes, teardown_minutes,
                            expected_attendance, required_layout_code, requirement_notes, status, decided_by_id, decided_at, decision_reason, created_at,
                            venue_requirement_id, hold_expires_at) VALUES
    ('44444444-0000-0000-0000-000000000009', '33333333-0000-0000-0000-000000000030', '22222222-0000-0000-0000-000000000002',
     '11111111-0000-0000-0000-000000000003', '2028-06-06 09:00+08', '2028-06-06 12:00+08', 0, 0,
     12, 'CLASSROOM', NULL, 'APPROVED', '11111111-0000-0000-0000-000000000005', '2026-10-08 15:00+08', NULL, '2026-10-08 11:00+08',
     'cccccccc-0000-0000-0030-000000000001', '2028-06-06 09:00+08'),
    -- Story 12.7: the Community Craft Fair's (3333..34) Craft hall, Exhibition Foyer, requested on
    -- 28 Sep 2026 and approved by Vera the next day with a hold until 5 Oct 2026 at 10:00. The
    -- event was not confirmed by then, so the hold expired. Its e2e spec finds the booking in the
    -- event's history and requests the foyer again.
    ('44444444-0000-0000-0000-000000000010', '33333333-0000-0000-0000-000000000034', '22222222-0000-0000-0000-000000000004',
     '11111111-0000-0000-0000-000000000003', '2028-07-12 10:00+08', '2028-07-12 16:00+08', 0, 0,
     120, 'EXHIBITION', E'Required facilities: Wi-Fi.\nThirty stalls and a workshop corner.', 'EXPIRED', '11111111-0000-0000-0000-000000000005', '2026-09-29 10:00+08', NULL, '2026-09-28 10:00+08',
     'cccccccc-0000-0000-0034-000000000001', '2026-10-05 10:00+08'),
    -- Story 21.1: each awaiting event's one venue, approved by Vera, held until its booked start.
    -- The concert's Exhibition Foyer holds 250, fewer than the 300 it expects.
    ('44444444-0000-0000-0000-000000000011', '33333333-0000-0000-0000-000000000035', '22222222-0000-0000-0000-000000000004',
     '11111111-0000-0000-0000-000000000004', '2028-08-16 18:00+08', '2028-08-16 22:00+08', 0, 0,
     300, 'STANDING', NULL, 'APPROVED', '11111111-0000-0000-0000-000000000005', '2026-10-01 15:00+08', NULL, '2026-10-01 11:00+08',
     'cccccccc-0000-0000-0035-000000000001', '2028-08-16 18:00+08'),
    ('44444444-0000-0000-0000-000000000012', '33333333-0000-0000-0000-000000000036', '22222222-0000-0000-0000-000000000001',
     '11111111-0000-0000-0000-000000000004', '2028-08-23 10:00+08', '2028-08-23 17:00+08', 0, 0,
     150, 'EXHIBITION', NULL, 'APPROVED', '11111111-0000-0000-0000-000000000005', '2026-10-02 15:00+08', NULL, '2026-10-02 11:00+08',
     'cccccccc-0000-0000-0036-000000000001', '2028-08-23 10:00+08')
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, venue_id = EXCLUDED.venue_id, requested_by_id = EXCLUDED.requested_by_id,
    starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at, setup_minutes = EXCLUDED.setup_minutes,
    teardown_minutes = EXCLUDED.teardown_minutes, expected_attendance = EXCLUDED.expected_attendance,
    required_layout_code = EXCLUDED.required_layout_code, requirement_notes = EXCLUDED.requirement_notes,
    status = EXCLUDED.status, decided_by_id = EXCLUDED.decided_by_id, decided_at = EXCLUDED.decided_at,
    decision_reason = EXCLUDED.decision_reason, created_at = EXCLUDED.created_at,
    venue_requirement_id = EXCLUDED.venue_requirement_id, hold_expires_at = EXCLUDED.hold_expires_at,
    hold_reminded_at = NULL, hold_completed_at = NULL;

-- Story 12.5: the earlier seeded bookings name the requirement they were made for: each its
-- event's Main venue (2.7 AC13), as migration 017 links bookings made before it, except Nimbus's
-- second, the breakout track, which is for its Breakout room.
UPDATE venue_bookings AS b
SET venue_requirement_id = link.requirement_id
FROM (VALUES
    ('44444444-0000-0000-0000-000000000001'::uuid, 'cccccccc-0000-0000-0000-000000000003'::uuid),
    ('44444444-0000-0000-0000-000000000002'::uuid, 'cccccccc-0000-0000-0003-000000000002'::uuid),
    ('44444444-0000-0000-0000-000000000003'::uuid, 'cccccccc-0000-0000-0000-000000000008'::uuid),
    ('44444444-0000-0000-0000-000000000004'::uuid, 'cccccccc-0000-0000-0000-000000000009'::uuid),
    ('44444444-0000-0000-0000-000000000005'::uuid, 'cccccccc-0000-0000-0000-000000000010'::uuid),
    ('44444444-0000-0000-0000-000000000006'::uuid, 'cccccccc-0000-0000-0000-000000000011'::uuid),
    ('44444444-0000-0000-0000-000000000007'::uuid, 'cccccccc-0000-0000-0000-000000000016'::uuid),
    ('44444444-0000-0000-0000-000000000008'::uuid, 'cccccccc-0000-0000-0000-000000000017'::uuid)
) AS link (booking_id, requirement_id)
WHERE b.id = link.booking_id;

-- ---------------------------------------------------------------------
-- Story 21.1: the Safety Officer's reviews. The earlier review of the Riverside Book Fair (3333..36)
-- sent it back. Its facts are the event as Sam saw it then: 120 people and two microphones
-- (its Grand Hall booking was already for 150, in the Exhibition layout that holds 300),
-- where it now expects 150 and has four, so the next check shows both as changed.
-- ---------------------------------------------------------------------
INSERT INTO event_safety_reviews (id, event_id, reviewed_by_id, reviewed_at, outcome, notes, facts) VALUES
    ('ffffffff-0000-0000-0000-000000000001', '33333333-0000-0000-0000-000000000036', '11111111-0000-0000-0000-000000000009', '2026-10-07 15:00+08',
     'CHANGES_REQUESTED', 'Confirm the attendance and the microphones.',
     '{"description": "Publisher stalls with author talks through the day.",
       "expected_attendance": 120,
       "starts_at": "2028-08-23T02:00:00+00:00", "ends_at": "2028-08-23T09:00:00+00:00",
       "venues": [{"id": "22222222-0000-0000-0000-000000000001", "name": "Grand Hall", "capacity": 300, "people_to_hold": 150,
                   "layout": "EXHIBITION", "layout_name": "Exhibition"}],
       "accessibility": [], "accessibility_notes": null,
       "equipment": [{"equipment_type": "WIRELESS_MIC", "equipment_type_name": "Wireless microphone", "quantity": 2, "technical_notes": "Author talks"}]}'),
    -- The Marina Food Festival (3333..37), approved, and the Lantern Night Walk (3333..38), sent
    -- back: story 21.1's Accepted and Declined tabs.
    ('ffffffff-0000-0000-0000-000000000002', '33333333-0000-0000-0000-000000000037', '11111111-0000-0000-0000-000000000009', '2026-10-09 10:00+08',
     'APPROVED', NULL,
     '{"description": "Food stalls along the waterfront promenade.",
       "expected_attendance": 200,
       "starts_at": "2028-09-02T03:00:00+00:00", "ends_at": "2028-09-02T13:00:00+00:00",
       "venues": [], "accessibility": [], "accessibility_notes": null, "equipment": []}'),
    ('ffffffff-0000-0000-0000-000000000003', '33333333-0000-0000-0000-000000000038', '11111111-0000-0000-0000-000000000009', '2026-10-08 10:00+08',
     'CHANGES_REQUESTED', 'Add marshals at each road crossing.',
     '{"description": "A guided evening walk with paper lanterns.",
       "expected_attendance": 80,
       "starts_at": "2028-09-09T11:00:00+00:00", "ends_at": "2028-09-09T14:00:00+00:00",
       "venues": [], "accessibility": [], "accessibility_notes": null, "equipment": []}')
ON CONFLICT (id) DO UPDATE SET
    event_id = EXCLUDED.event_id, reviewed_by_id = EXCLUDED.reviewed_by_id, reviewed_at = EXCLUDED.reviewed_at,
    outcome = EXCLUDED.outcome, notes = EXCLUDED.notes, facts = EXCLUDED.facts;
