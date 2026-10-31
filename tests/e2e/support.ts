import { expect, type Page, type Request } from '@playwright/test'

/**
 * Seed accounts from backend/db/seed/020_sample_data.sql (mirrored in
 * backend/tests/support/seed.py). Every account shares one password.
 */
export const PASSWORD = 'Password123!'

export const ACCOUNTS = {
  organiser: 'organiser@acme.example',
  organiser2: 'organiser@nimbus.example',
  coordinator: 'coordinator@connectsphere.example',
  // Story 5.4: the Event Coordinator Lead, who assigns submitted requests to coordinators.
  lead: 'lead@connectsphere.example',
  coordinator2: 'coordinator2@connectsphere.example',
  venueStaff: 'venue@connectsphere.example',
  techSupport: 'tech@connectsphere.example',
  safetyOfficer: 'safety@connectsphere.example',
  attendee: 'attendee@example.com',
  // Story 18.1: holds the one place at the portfolio review, and races for the mentoring slot.
  attendee2: 'attendee2@example.com',
  // Story 18.4: one attendee for each flow that changes their details (attendee-profile.spec.ts).
  // Cara has never been asked for them; Dion changes them on an event's page; Esme on My profile;
  // Finn changes their name.
  attendee3: 'attendee3@example.com',
  attendee4: 'attendee4@example.com',
  attendee5: 'attendee5@example.com',
  attendee6: 'attendee6@example.com',
  // Story 18.5: one attendee for each flow with guests (register-guests.spec.ts). Gina registers
  // with guests; Hana, registered on her own, adds one afterwards.
  attendee7: 'attendee7@example.com',
  attendee8: 'attendee8@example.com',
  // Story 20.2: an organiser with nine notifications of her own, which only
  // notifications.spec.ts reads (backend/tests/support/seed.py::Users.NOTICE).
  notice: 'nadia@notice.example',
} as const

export const INVALID_CREDENTIALS_MESSAGE = 'Invalid email or password.'

/** Fixed event IDs from backend/db/seed/020_sample_data.sql (mirrored in
 *  backend/tests/support/seed.py::Events). */
export const EVENTS = {
  submitted: '33333333-0000-0000-0000-000000000002', // organiser: organiser, no decision yet
  approved: '33333333-0000-0000-0000-000000000003', // organiser: organiser2, approved by coordinator
  rejected: '33333333-0000-0000-0000-000000000004', // organiser: organiser2, rejected by coordinator2
  clarificationRequested: '33333333-0000-0000-0000-000000000006', // organiser: organiser
  draft: '33333333-0000-0000-0000-000000000001',
  planning: '33333333-0000-0000-0000-000000000012', // organiser: organiser, coordinator, Theatre only
  partnerBriefing: '33333333-0000-0000-0000-000000000018', // coordinator; no spec writes a request for it
  // Story 6.2, Cancelled by its organiser, organiser2, with a reason; only read.
  cancelled: '33333333-0000-0000-0000-000000000015',
  // Story 6.2 AC14-AC16, Planning, organiser: organiser, coordinator, March 2029: an approved
  // booking of Sunrise Studio, a Harbour Pavilion booking an earlier change cancelled, and four
  // wireless microphones sent to Technical Support. The 6.2 spec cancels it.
  charityRun: '33333333-0000-0000-0000-000000000062',
  // Fix f7.1.2, organiser: a two-day booking of Sunrise Studio; events.spec.ts cancels it.
  leadershipRetreat: '33333333-0000-0000-0000-000000007012',
  confirmed: '33333333-0000-0000-0000-000000000013', // organiser: organiser2, coordinator, Confirmed
  completed: '33333333-0000-0000-0000-000000000014', // organiser: organiser, Completed
  // Cancelled, organiser: organiser2, dated April 2027 - not yet over, so only its status hides
  // what a cancelled event no longer offers.
  cancelledFunRun: '33333333-0000-0000-0000-000000000075',
  // Confirmed, organiser: organiser2, and over since 3 Oct 2026 - nothing marks it Completed (Q57).
  bookSwap: '33333333-0000-0000-0000-000000000076',
  // Story 15.1, both Planning, organiser: organiser, coordinator, dated May 2027. Only the
  // equipment flow changes the workshop's equipment; nothing changes the showcase's.
  equipmentWorkshop: '33333333-0000-0000-0000-000000000019',
  equipmentShowcase: '33333333-0000-0000-0000-000000000020',
  // Story 15.2, Planning, organiser: organiser2, coordinator, dated June 2027. One equipment item
  // per Technical Support tab; nothing changes them.
  equipmentRoadshow: '33333333-0000-0000-0000-000000000021',
  // Story 16.1, Planning, organiser: organiser2, coordinator, dated December 2027. Six pending
  // equipment items; the 16.1 spec accepts and declines them.
  equipmentDecisions: '33333333-0000-0000-0000-000000000027',
  // Story 17.1, organiser: organiser2, coordinator. The Summer Rooftop Mixer was cancelled with
  // three items on it, all released; nothing changes them. The waterfront demo is Planning,
  // dated January 2028, with one pending item the 17.1 spec has Technical Support accept.
  cancelled: '33333333-0000-0000-0000-000000000015',
  waterfrontDemo: '33333333-0000-0000-0000-000000000080',
  // Story 8.4, Planning, organiser: organiser2, coordinator, dated March 2028. Three venue
  // requirements, each finding different venues; the 8.4 spec only reads it.
  smartCitiesExpo: '33333333-0000-0000-0000-000000000028',
  // Story 12.5, Planning, organiser: organiser2, coordinator. The 12.5 spec sends requests for
  // them: the forum has three venue requirements and no bookings, dated April 2028; the
  // workshop's one requirement is booked (Seminar Room 2.1, approved), dated June 2028.
  mobilityForum: '33333333-0000-0000-0000-000000000029',
  resilienceWorkshop: '33333333-0000-0000-0000-000000000030',
  // Planning, organiser: organiser2, coordinator, May 2028: one venue requirement and no
  // bookings. 12.1's real send since story 12.5 (one request per requirement).
  onboardingDay: '33333333-0000-0000-0000-000000000031',
  // Story 12.5, Planning, organiser: organiser2, coordinator, July 2028: three venue
  // requirements and no bookings. The 12.5 spec requests venues for it, then withdraws one
  // and switches another from the catalogue.
  tradeFair: '33333333-0000-0000-0000-000000000032',
  // Planning, organiser: organiser2, coordinator, March 2027: one venue requirement shaped
  // like the partner briefing's, and no bookings. Story 11.1's real send with a justification
  // since story 12.5 (one request per requirement).
  pricingClinic: '33333333-0000-0000-0000-000000000033',
  // Story 12.7, Planning, organiser: organiser2, coordinator, July 2028: one venue requirement,
  // whose request expired. The 12.7 spec requests a venue for it again.
  craftFair: '33333333-0000-0000-0000-000000000034',
  // Story 21.1, Awaiting Safety Check, organiser: organiser2, coordinator2, August 2028. The
  // concert expects 300 at the 250-seat Exhibition Foyer, whose operating hours are not recorded,
  // and leads the queue. The book fair is within capacity and was sent back once.
  harbourConcert: '33333333-0000-0000-0000-000000000035',
  bookFair: '33333333-0000-0000-0000-000000000036',
  // Story 21.1, reviewed and no longer awaiting the check, organiser: organiser2, coordinator2,
  // September 2028: the food festival was approved (Confirmed), the night walk sent back
  // (Planning).
  foodFestival: '33333333-0000-0000-0000-000000000037',
  nightWalk: '33333333-0000-0000-0000-000000000038',
  // Fix f12.1.2, Planning, organiser: organiser2, coordinator, February 2027: one venue
  // requirement (Classroom with a projector, 30) and no bookings. The 12.1 spec's real send with
  // a setup that starts before Seminar Room 2.1 opens.
  supplierInduction: '33333333-0000-0000-0000-000000000046',
  // Story 9.4, Planning, organiser: organiser2, coordinator, October 2028. Each has one pending
  // request at a venue dedicated to the 9.4 spec (see VENUES below); only that spec saves a
  // closure over them.
  choirShowcase: '33333333-0000-0000-0000-000000000060',
  artMarket: '33333333-0000-0000-0000-000000000061',
  // Story 12.6, organiser: organiser2, February 2029. Each has a booking at Exhibition Foyer that
  // its day's closure has marked "Venue unavailable - alternative needed" (the closure and the mark
  // are seeded); Grand Hall is free for every one. Coordinator's unless said otherwise.
  lanternShowcase: '33333333-0000-0000-0000-000000012662', // approved; read only
  makerFaire: '33333333-0000-0000-0000-000000012663', // an approved additional venue, marked
  springExpo: '33333333-0000-0000-0000-000000012664', // the spec raises a replacement
  awardsEvening: '33333333-0000-0000-0000-000000012665', // ... and Venue Staff approve it
  pitchNight: '33333333-0000-0000-0000-000000012666', // ... withdrawn, then asked for again
  neighbourhoodSummit: '33333333-0000-0000-0000-000000012667', // ... the closure removed first
  heritageWalk: '33333333-0000-0000-0000-000000012668', // CANCELLED, its booking still marked
  productShowcase: '33333333-0000-0000-0000-000000012669', // a marked PENDING booking
  roboticsOpenHouse: '33333333-0000-0000-0000-000000012678', // coordinator2's; read only
  wellnessExpo: '33333333-0000-0000-0000-000000012679', // coordinator2's; the spec asks for one
  craftMarket: '33333333-0000-0000-0000-000000012680', // an additional venue, marked; its closure is removed, then a request
  harvestFair: '33333333-0000-0000-0000-000000012681', // an additional venue, marked; replaced, then Back
  openStudios: '33333333-0000-0000-0000-000000012682', // a marked pending replacement; read only
  nightBazaar: '33333333-0000-0000-0000-000000012683', // a marked pending additional venue; read only
  springFair: '33333333-0000-0000-0000-000000012684', // a replacement is raised, then rejected
  gardenFair: '33333333-0000-0000-0000-000000012685', // a pending request and an older withdrawn one; a switch is sent
  // Story 21.2: four events of the organiser's, coordinated by the coordinator, each with Seminar
  // Room 2.1 booked in November 2028; one flow of safety-decision.spec.ts each. The bootcamp is secured and never reviewed;
  // the clinic and the workshop await the check; the summit was sent back with its venue flagged
  // and still has the same venue.
  codingBootcamp: '33333333-0000-0000-0000-000000000050',
  cyberClinic: '33333333-0000-0000-0000-000000000047',
  dataSummit: '33333333-0000-0000-0000-000000000048',
  aiWorkshop: '33333333-0000-0000-0000-000000000049',
  // Story 19.2 AC8: set up as the bootcamp is - secured, never reviewed, Seminar Room 2.1 booked
  // in November 2028 - for change-request-decisions.spec.ts to send to its safety check.
  designSprint: '33333333-0000-0000-0000-000000000051',
  // Story 18.1's, Confirmed, organiser: organiser2, coordinator2. Story 18.3 reads their
  // registration lists: the portfolio review's one place is held by attendee2, so it is full;
  // the wine appreciation closed with no one registered.
  portfolioReview: '33333333-0000-0000-0000-000000000043',
  wineAppreciation: '33333333-0000-0000-0000-000000000044',
  // Story 18.2's, Confirmed, organiser: organiser2. Aiden withdrew on 8 Oct 2026; 18.2 and 18.3
  // only read it.
  heritageTrail: '33333333-0000-0000-0000-000000000074',
  // Story 20.2: Nadia Notice's, in planning with coordinator2 (dated February 2028). Nothing
  // changes it; her notifications are about it.
  noticeGala: '33333333-0000-0000-0000-000000020202',
  // Story 18.4, Confirmed, organiser: organiser2, coordinator2, December 2028. Esme registered for
  // the charity quiz before the spec changes her details; the food tasting walk closed on 1 Oct
  // 2026 with Aiden and Bella registered, so its list never changes and is only read.
  charityQuiz: '33333333-0000-0000-0000-000000018407',
  foodTastingWalk: '33333333-0000-0000-0000-000000018408',
  // Story 18.5, both Confirmed and open, organiser: organiser2, January 2029. Gina registers for the
  // batik workshop with two guests; Hana, registered alone for the kite afternoon, adds one.
  batikWorkshop: '33333333-0000-0000-0000-000000018503',
  kiteAfternoon: '33333333-0000-0000-0000-000000018504',
} as const

/** Venue names from backend/db/seed/020_sample_data.sql (mirrored in
 *  backend/tests/support/seed.py::Venues). The three below are dedicated to the 9.4 spec. */
export const VENUES = {
  // No booking: the spec adds, edits and ends closures here.
  gardenAtrium: 'Garden Atrium',
  // One pending request, the choir showcase's, at 14 October 2028: the preview lists it.
  harbourPavilion: 'Harbour Pavilion',
  // One pending request, the art market's, at 21 October 2028: a closure marks it.
  sunriseStudio: 'Sunrise Studio',
} as const

/** Story 18.1 AC9 (fix f18.1.2): from Upcoming events, open an event's page by its card's link,
 *  its title. */
export async function openEventPage(page: Page, name: string) {
  await page.goto('/browse')
  await page
    .getByRole('listitem')
    .filter({ has: page.getByRole('heading', { level: 3, name }) })
    .getByRole('link', { name })
    .click()
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
}

/** Story 18.1 AC9: where an event's page says where registration stands, and offers Register. */
export function registrationSection(page: Page) {
  return page.getByRole('region', { name: 'Registration', exact: true })
}

export function registerButton(page: Page, name: string) {
  return registrationSection(page).getByRole('button', { name: `Register for ${name}` })
}

/** Story 18.4: the dialog every registration opens, showing the attendee's details to confirm -
 *  filled in from their profile, or asked for the first time. */
export const CONFIRM_DETAILS_DIALOG = 'Confirm your details'
export const CONFIRM_AND_REGISTER = 'Confirm and register'

export function confirmDetailsDialog(page: Page) {
  return page.getByRole('dialog', { name: CONFIRM_DETAILS_DIALOG })
}

/** Story 18.4 AC2/AC3: confirm the details the dialog shows, which sends the registration. */
export async function confirmRegistration(page: Page) {
  await confirmDetailsDialog(page)
    .getByRole('button', { name: CONFIRM_AND_REGISTER, exact: true })
    .click()
}

/** Fill and submit the sign-in form, waiting for the backend to answer. */
export async function signIn(page: Page, email: string, password: string = PASSWORD) {
  // A Sign out clicked just before may still be waiting on the server: let the app finish it and
  // open /login itself, since navigating away now would cancel the request.
  if ((await page.getByRole('button', { name: 'Sign out' }).count()) > 0) {
    await page.waitForURL((url) => url.pathname === '/login')
  }
  if (!page.url().endsWith('/login')) await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/auth/login')),
    page.getByRole('button', { name: 'Sign in' }).click(),
  ])
}

export async function expectSignedIn(page: Page) {
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
}

/** A unique name, since specs share one database and run in parallel. */
export function uniqueName(label: string): string {
  return `E2E ${label} ${Date.now()}-${Math.floor(Math.random() * 1e6)}`
}

/** A `datetime-local` value (Singapore time) `days` from today, safely in the future. */
export function inFuture(days: number, hour = 9): string {
  const day = new Date(Date.now() + days * 24 * 60 * 60 * 1000)
  const date = day.toISOString().slice(0, 10)
  return `${date}T${String(hour).padStart(2, '0')}:00`
}

/**
 * Create and submit a fresh, minimal request with one venue requirement as the signed-in
 * organiser; returns its id. A new request starts with one venue requirement (story 2.7 AC14,
 * f2.7.4), so it is only named: its number of people follows the expected attendance of 60, and
 * its times the event's. It runs 09:00-17:00, `days` from today (30 unless said).
 */
export async function createAndSubmitRequest(page: Page, name: string, days = 30): Promise<string> {
  await page.goto('/events/new')
  await page.getByLabel('Event name').fill(name)
  await page.getByLabel('Purpose').fill('Staff training')
  await page.getByLabel('Description').fill('One-day hands-on workshop.')
  await page.getByLabel('Proposed start').fill(inFuture(days, 9))
  await page.getByLabel('Proposed end').fill(inFuture(days, 17))
  await page.getByLabel('Expected attendance').fill('60')
  await page.getByLabel('Contact name').fill('Priya Nair')
  await page.getByLabel('Contact email').fill('priya.nair@example.com')
  await page.getByLabel('Contact phone number').fill('+65 9123 4567')
  await page
    .getByRole('group', { name: 'Venue requirement 1' })
    .getByLabel('Requirement name')
    .fill('Main venue')
  await page.getByRole('checkbox', { name: 'No accessibility needs' }).check()
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(/\/events\/[0-9a-f-]{36}\/edit$/)
  const match = page.url().match(/\/events\/([0-9a-f-]{36})\/edit$/)
  if (!match) throw new Error(`could not read the event id from ${page.url()}`)
  const eventId = match[1]

  await page.getByRole('button', { name: 'Submit request' }).click()
  await expect(page).toHaveURL(/\/events\/mine$/)
  return eventId
}

/** The two seeded Event Coordinators. Since story 5.4 the Lead assigns a submitted request to one
 *  of them (`assignByLead`), always Chloe, so a spec knows in advance who its coordinator is. */
export const COORDINATORS = [
  {
    account: ACCOUNTS.coordinator,
    name: 'Chloe Coordinator',
    id: '11111111-0000-0000-0000-000000000003',
  },
  {
    account: ACCOUNTS.coordinator2,
    name: 'Carl Coordinator',
    id: '11111111-0000-0000-0000-000000000004',
  },
] as const

/**
 * Story 5.4 AC9: a submitted request waits unassigned until the Event Coordinator Lead assigns it.
 * Called on the request's page by its organiser (Olivia), this signs in as the Lead, assigns it to
 * Chloe from the unassigned queue, then signs Olivia back in on the same page. Returns Chloe, plus
 * the other coordinator - the shape story 5.1's round-robin helper returned, so specs that went on
 * as "whoever was assigned" keep working unchanged.
 */
export async function assignByLead(page: Page) {
  const eventPath = new URL(page.url()).pathname
  const name = (await page.getByRole('heading', { level: 1 }).textContent())?.trim() ?? ''
  const [chloe, carl] = COORDINATORS

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.lead)
  await page.goto('/events/unassigned')
  const queued = page
    .getByRole('list', { name: 'Unassigned events' })
    .getByRole('listitem')
    .filter({ hasText: name })
  await queued.getByRole('button', { name: 'Assign' }).click()
  const dialog = page.getByRole('dialog', { name: `Assign "${name}"?` })
  await dialog.getByLabel('Coordinator').selectOption(chloe.id)
  await dialog.getByRole('button', { name: 'Assign' }).click()
  await expect(queued).toHaveCount(0)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(eventPath)
  await expect(page.getByText(chloe.account, { exact: true })).toBeVisible()
  return { ...chloe, other: carl }
}

/** A fresh event of the organiser's, approved by whichever coordinator it was assigned to, with
 *  the organiser signed back in on its page. Returns its id, its name and that coordinator's
 *  account. Stories 19.1 and 19.2 raise and decide change requests on it; story 19.3 dates it
 *  `days` from today (30 unless said), away from the day other specs book venues on. */
export async function approvedEvent(page: Page, label: string, days = 30) {
  await signIn(page, ACCOUNTS.organiser)
  const name = uniqueName(label)
  const eventId = await createAndSubmitRequest(page, name, days)
  await page.goto(`/events/${eventId}`)
  const { account } = await assignByLead(page)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, account)
  await page.goto(`/events/${eventId}`)
  await page.getByRole('button', { name: 'Approve' }).click()
  await page
    .getByRole('dialog', { name: 'Approve this request?' })
    .getByRole('button', { name: 'Approve' })
    .click()
  await expect(page.getByText('Planning', { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${eventId}`)
  return { eventId, name, coordinator: account }
}

/** Story 19.1's change requests on an event's detail page, which story 19.2 decides there. */
export function changeRequests(page: Page) {
  return page.getByRole('region', { name: 'Change requests' })
}

/** The clarification thread on an event's detail page (stories 4.2, 4.6). */
export function clarificationsSection(page: Page) {
  return page.getByRole('region', { name: 'Clarifications', exact: true })
}

/** A venue card in the venue catalogue, matched by the venue's name. */
export function venueCard(page: Page, name: string) {
  return page.getByRole('article').filter({ has: page.getByRole('heading', { name }) })
}

/** The screens the responsive checks use: a phone, a tablet and a desktop. */
export const PHONE = { width: 375, height: 667 }
export const TABLET = { width: 768, height: 1024 }
export const DESKTOP = { width: 1280, height: 800 }
/** The smallest height a control pressed with a thumb may have on a phone. */
export const MIN_TOUCH_TARGET = 44

/** The page fits its viewport: nothing scrolls sideways. */
export async function expectNoSidewaysScroll(page: Page) {
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )
  expect(fits).toBe(true)
}

/** Headers a stubbed `route.fulfill` needs, since the app and API run on different ports. */
export function corsHeaders(request: Request) {
  return {
    'access-control-allow-origin': request.headers()['origin'] ?? '*',
    'access-control-allow-credentials': 'true',
  }
}

/** One of Nadia Notice's seeded notifications, as the bell lists it (story 20.2). */
export interface SeededNotice {
  id: string
  title: string
  message: string
  /** The row's time as `formatDateTime` writes it, in Singapore time. */
  time: string
  isRead: boolean
}

/**
 * Nadia Notice's nine notifications, newest first: the order the bell lists them in, and the
 * order notifications.spec.ts reads them in. Mirrors backend/tests/support/seed.py::Notifications
 * (ids, titles, read state) and backend/db/seed/020_sample_data.sql (messages, created_at). The
 * fifth is about Olivia's draft, which Nadia cannot open.
 */
export const NADIA_NOTICES = {
  confirmed: {
    id: 'dddddddd-0000-0000-0000-000000020207',
    title: '"Harbour Lights Gala" is confirmed',
    message: 'Sam Safety confirmed the event after it passed the safety review.',
    time: 'Mon, 19 Oct 2026, 17:45',
    isRead: false,
  },
  changeApproved: {
    id: 'dddddddd-0000-0000-0000-000000020208',
    title: 'Change approved for Harbour Lights Gala',
    message: 'Carl Coordinator approved your request to change the expected attendance.',
    time: 'Mon, 19 Oct 2026, 17:30',
    isRead: false,
  },
  clarification: {
    id: 'dddddddd-0000-0000-0000-000000020209',
    title: 'Clarification requested on "Harbour Lights Gala"',
    message: 'Which accessibility features should the gala hall provide?',
    time: 'Mon, 19 Oct 2026, 17:15',
    isRead: false,
  },
  venueUnavailable: {
    id: 'dddddddd-0000-0000-0000-000000020210',
    title: 'Exhibition Foyer is unavailable for "Harbour Lights Gala"',
    message:
      'Exhibition Foyer is unavailable on Wed 9 Feb 2028 from 09:00 to 17:00 (Maintenance). Its booking for "Harbour Lights Gala" falls in that period, so the event needs another venue.',
    time: 'Mon, 19 Oct 2026, 17:00',
    isRead: false,
  },
  oliviasDraft: {
    id: 'dddddddd-0000-0000-0000-000000020211',
    title: '"Q1 Sales Kick-off (draft)" was approved',
    message: 'Chloe Coordinator approved your request. It is now being planned.',
    time: 'Mon, 19 Oct 2026, 16:45',
    isRead: false,
  },
  safetyApproved: {
    id: 'dddddddd-0000-0000-0000-000000020212',
    title: '"Harbour Lights Gala" passed the safety review',
    message: 'Sam Safety approved it. The coordinator can now confirm the event.',
    time: 'Mon, 19 Oct 2026, 16:30',
    isRead: false,
  },
  approved: {
    id: 'dddddddd-0000-0000-0000-000000020213',
    title: '"Harbour Lights Gala" was approved',
    message: 'Carl Coordinator approved your request. It is now being planned.',
    time: 'Mon, 19 Oct 2026, 16:15',
    isRead: false,
  },
  rejected: {
    id: 'dddddddd-0000-0000-0000-000000020214',
    title: '"Harbour Lights Gala" was rejected',
    message:
      'Carl Coordinator rejected your request. Reason: The first date clashed with another booking.',
    time: 'Sun, 18 Oct 2026, 15:00',
    isRead: true,
  },
  reassigned: {
    id: 'dddddddd-0000-0000-0000-000000020215',
    title: '"Harbour Lights Gala" has a new coordinator',
    message: 'Carl Coordinator is now the coordinator for "Harbour Lights Gala".',
    time: 'Sat, 17 Oct 2026, 11:20',
    isRead: true,
  },
} as const satisfies Record<string, SeededNotice>

/** The same nine, newest first. */
export const NADIA_NOTICES_NEWEST_FIRST: readonly SeededNotice[] = [
  NADIA_NOTICES.confirmed,
  NADIA_NOTICES.changeApproved,
  NADIA_NOTICES.clarification,
  NADIA_NOTICES.venueUnavailable,
  NADIA_NOTICES.oliviasDraft,
  NADIA_NOTICES.safetyApproved,
  NADIA_NOTICES.approved,
  NADIA_NOTICES.rejected,
  NADIA_NOTICES.reassigned,
]
