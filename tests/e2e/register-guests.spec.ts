import { expect, test, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  EVENTS,
  confirmDetailsDialog,
  confirmRegistration,
  corsHeaders,
  signIn,
} from './support'

/**
 * Story 18.5 - register guests with my registration. END-TO-END tests: what an attendee and an
 * organiser click through.
 *
 * Level: e2e. The rules behind these pages - at most 10 guests, a guest's name and dietary limits,
 * the places a group takes, when guests can no longer change, who may change them, and two
 * requests for the last places - are proven in
 * backend/tests/registrations/test_register_guests_*.py, not repeated here. The exceptions are
 * AC6/AC7's checks in the browser, which stop an 11th guest or a guest with no name before any
 * request is sent, so no backend test can see them.
 *
 * AC1 When registering, the attendee can add guests, each with a name and optional dietary
 *     requirements. The attendee and their guests are registered together as one group.
 * AC2 Each guest takes a place: an attendee with N guests takes N+1 places against the event's
 *     capacity.
 * AC3 After registering, the attendee can add, change or remove guests.
 * AC4 The attendee sees their guests on My registrations and on the event's page.
 * AC5 The organiser and assigned coordinator see each attendee's guests (name and dietary
 *     requirements) in the registration list (18.3), and its active count includes guests.
 * AC6 An attendee can bring at most 10 guests (a group of at most 11).
 * AC7 A guest's name is required, at most 200 characters; dietary requirements are optional, at
 *     most 500 characters. Guests are not asked for a phone number or email.
 * AC12 If a group, or added guests, would not fit in the places left, the whole request is refused.
 *     (Here: the dialogs offer no more guests than there are places for, and say why; the refusal
 *     itself is a backend case.)
 * AC9 Guests can be changed only while registration is open. (Here: the page offers Change guests
 *     only when the server says so; the rule itself is a backend case.)
 *
 * Each flow has a seeded attendee of its own (backend/db/seed/020_sample_data.sql, story 18.5's
 * block), since specs run in parallel and a registration happens once: Gina registers for the
 * batik workshop with two guests; Hana, registered alone for the kite afternoon, adds a guest and
 * removes them again. The browser-only checks open Gina's dialog for the kite afternoon and send
 * nothing. Aiden's registrations are only read: the food tasting walk's registration closed on 1
 * Oct 2026 (story 18.4's seed), and his registration with guests is stubbed, so nothing is written.
 */

const UPCOMING_EVENTS_PATH = '/browse'
const MY_REGISTRATIONS_PATH = '/registrations'
const CHANGE_GUESTS_DIALOG = 'Change your guests'
const MAX_GUESTS = 10
const TOO_MANY_GUESTS_MESSAGE = 'You can bring at most 10 guests.'
// Story 18.5 AC12 (PO, 30 Oct 2026): the places left, not the 10-guest limit, stop more guests.
const NO_PLACES_FOR_MORE_GUESTS_MESSAGE = 'There are not enough places left for more guests.'
const GUEST_NAME_REQUIRED_MESSAGE = "Enter your guest's name."
const GUEST_DIETARY_MAX_LENGTH = 500

const BATIK_WORKSHOP = 'Batik Printing Workshop' // 30 places; Gina registers with two guests
const KITE_AFTERNOON = 'Kite Flying Afternoon' // 30 places; Hana registered alone
const FOOD_TASTING_WALK = 'Food Tasting Walk' // registration closed; Aiden registered (18.4)
const GINA = { name: 'Gina Attendee' }
const RAVI = { name: 'Ravi Kumar', dietary: 'Vegetarian' }
const MEI = { name: 'Mei Lin' }
const ANA = { name: 'Ana Cruz', dietary: 'No shellfish' }

/** An event's card, found by its name (as in attendee-registration.spec.ts). */
function eventCard(page: Page, name: string) {
  return page.getByRole('listitem').filter({ has: page.getByRole('heading', { level: 3, name }) })
}

function guestGroup(page: Page, n: number) {
  return page.getByRole('group', { name: `Guest ${n}`, exact: true })
}

function addGuestButton(page: Page) {
  return page.getByRole('button', { name: 'Add a guest' })
}

/** Add a guest at the end of the open dialog's list, as the attendee types them. */
async function addGuest(page: Page, n: number, guest: { name: string; dietary?: string }) {
  await addGuestButton(page).click()
  const group = guestGroup(page, n)
  await group.getByLabel("Guest's name").fill(guest.name)
  if (guest.dietary !== undefined) {
    await group.getByLabel("Guest's dietary requirements").fill(guest.dietary)
  }
}

/** The places left an event's card shows, as a number. */
async function placesLeft(page: Page, name: string): Promise<number> {
  const text = await eventCard(page, name).getByText(/\d+ places? left/).innerText()
  return Number(text.match(/\d+/)![0])
}

function registrations(page: Page) {
  return page.getByRole('region', { name: 'Registered attendees', exact: true })
}

test('18.5 AC1/AC2/AC4/AC5: an attendee registers with two guests, who take places and are listed for the organiser', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee7)
  await page.goto(UPCOMING_EVENTS_PATH)
  await eventCard(page, BATIK_WORKSHOP)
    .getByRole('button', { name: `Register for ${BATIK_WORKSHOP}` })
    .click()

  const dialog = confirmDetailsDialog(page)
  await expect(dialog.getByRole('group', { name: 'Guests' })).toBeVisible()
  await addGuest(page, 1, RAVI)
  await addGuest(page, 2, MEI)
  // AC7: nothing but a name and dietary requirements is asked of a guest.
  await expect(guestGroup(page, 1).getByRole('textbox')).toHaveCount(2)
  await confirmRegistration(page)
  await expect(dialog).toHaveCount(0)

  // AC2: the group took three of the thirty places.
  const card = eventCard(page, BATIK_WORKSHOP)
  await expect(card.getByText('Registered', { exact: true })).toBeVisible()
  await expect(card).toContainText('27 places left')

  // AC4: My registrations names the guests.
  await page.goto(MY_REGISTRATIONS_PATH)
  const mine = eventCard(page, BATIK_WORKSHOP)
  await expect(mine).toContainText(RAVI.name)
  await expect(mine).toContainText(MEI.name)

  // AC5: the organiser sees the guests under Gina, with Ravi's dietary requirements, and the count
  // includes them.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/registrations/report?event=${EVENTS.batikWorkshop}`)
  const list = registrations(page)
  await expect(list).toContainText('3 / 30')
  const gina = list.getByRole('row').filter({ hasText: GINA.name })
  await expect(gina).toContainText(RAVI.name)
  await expect(gina).toContainText(RAVI.dietary)
  await expect(gina).toContainText(MEI.name)
})

test('18.5 AC3/AC4: an attendee registered alone adds a guest on My registrations, then removes them', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee8)
  await page.goto(MY_REGISTRATIONS_PATH)
  const card = eventCard(page, KITE_AFTERNOON)
  await card.getByRole('button', { name: `Change guests for ${KITE_AFTERNOON}` }).click()

  const dialog = page.getByRole('dialog', { name: CHANGE_GUESTS_DIALOG })
  await addGuest(page, 1, ANA)
  await dialog.getByRole('button', { name: 'Save guests' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(card).toContainText(ANA.name)

  // Reloading shows what was saved.
  await page.reload()
  await expect(card).toContainText(ANA.name)

  await card.getByRole('button', { name: `Change guests for ${KITE_AFTERNOON}` }).click()
  await expect(guestGroup(page, 1).getByLabel("Guest's name")).toHaveValue(ANA.name)
  await expect(guestGroup(page, 1).getByLabel("Guest's dietary requirements")).toHaveValue(
    ANA.dietary,
  )
  await dialog.getByRole('button', { name: 'Remove guest 1' }).click()
  await dialog.getByRole('button', { name: 'Save guests' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(card).not.toContainText(ANA.name)
  await expect(card.getByText('Registered', { exact: true })).toBeVisible()
})

test('18.5 AC6: after ten guests the dialog offers no more, and says why, before sending anything', async ({
  page,
}) => {
  const sent: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST') sent.push(request.url())
  })
  await signIn(page, ACCOUNTS.attendee7)
  await page.goto(UPCOMING_EVENTS_PATH)
  sent.length = 0
  await eventCard(page, KITE_AFTERNOON)
    .getByRole('button', { name: `Register for ${KITE_AFTERNOON}` })
    .click()

  const dialog = confirmDetailsDialog(page)
  for (let n = 1; n <= MAX_GUESTS; n++) {
    await addGuest(page, n, { name: `Guest ${n}` })
  }

  await expect(addGuestButton(page)).toBeDisabled()
  await expect(dialog).toContainText(TOO_MANY_GUESTS_MESSAGE)
  await expect(guestGroup(page, MAX_GUESTS + 1)).toHaveCount(0)
  expect(sent).toEqual([])
})

test("18.5 AC7: a guest left without a name is refused before sending, and a guest's dietary requirements take no more than 500 characters", async ({
  page,
}) => {
  const sent: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST') sent.push(request.url())
  })
  await signIn(page, ACCOUNTS.attendee7)
  await page.goto(UPCOMING_EVENTS_PATH)
  sent.length = 0
  await eventCard(page, KITE_AFTERNOON)
    .getByRole('button', { name: `Register for ${KITE_AFTERNOON}` })
    .click()

  const dialog = confirmDetailsDialog(page)
  await addGuestButton(page).click()
  const dietary = guestGroup(page, 1).getByLabel("Guest's dietary requirements")
  await dietary.fill('v'.repeat(GUEST_DIETARY_MAX_LENGTH + 1))
  await expect(dietary).toHaveValue('v'.repeat(GUEST_DIETARY_MAX_LENGTH))

  await confirmRegistration(page)

  await expect(guestGroup(page, 1)).toContainText(GUEST_NAME_REQUIRED_MESSAGE)
  await expect(dialog).toBeVisible()
  expect(sent).toEqual([])
})

test('18.5 AC9: a registration whose registration has closed offers Withdraw but not Change guests', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee)
  await page.goto(MY_REGISTRATIONS_PATH)

  const closed = eventCard(page, FOOD_TASTING_WALK)
  await expect(
    closed.getByRole('button', { name: `Withdraw from ${FOOD_TASTING_WALK}` }),
  ).toBeVisible()
  await expect(
    closed.getByRole('button', { name: `Change guests for ${FOOD_TASTING_WALK}` }),
  ).toHaveCount(0)
})

test('18.5 AC2: the card counts the whole group at once, before the list is read again', async ({
  page,
}) => {
  // The registration is stubbed as taken with two guests, and the list read again after it is
  // held back, so the card can only show what the page worked out itself. Nothing is written.
  let hasRegistered = false
  let releaseList: () => void = () => {}
  const listHeld = new Promise<void>((resolve) => {
    releaseList = resolve
  })
  await page.route(
    (url) => url.pathname === '/registrations' || url.pathname === '/registrations/events',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      const path = new URL(request.url()).pathname
      if (path === '/registrations' && request.method() === 'POST') {
        hasRegistered = true
        const sent = request.postDataJSON() as { event_id: string }
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          headers: corsHeaders(request),
          body: JSON.stringify({
            id: '00000000-0000-4000-8000-000000000185',
            event_id: sent.event_id,
            status: 'REGISTERED',
            registered_at: '2026-10-30T02:00:00Z',
            guests: [
              { full_name: RAVI.name, dietary_requirements: RAVI.dietary },
              { full_name: MEI.name, dietary_requirements: null },
            ],
          }),
        })
      }
      if (path === '/registrations/events' && hasRegistered) await listHeld
      return route.fallback()
    },
  )
  await signIn(page, ACCOUNTS.attendee)
  await page.goto(UPCOMING_EVENTS_PATH)
  const before = await placesLeft(page, KITE_AFTERNOON)

  await eventCard(page, KITE_AFTERNOON)
    .getByRole('button', { name: `Register for ${KITE_AFTERNOON}` })
    .click()
  await addGuest(page, 1, RAVI)
  await addGuest(page, 2, MEI)
  await confirmRegistration(page)

  const card = eventCard(page, KITE_AFTERNOON)
  await expect(card.getByText('Registered', { exact: true })).toBeVisible()
  await expect(card).toContainText(`${before - 3} places left`)
  releaseList()
})

test('18.5 AC12: with 2 places left the dialog allows one guest, and says why, before sending anything', async ({
  page,
}) => {
  // The list is the server's own, with the kite afternoon's places cut to 2: a state the seed
  // cannot reach without filling the event. Nothing is sent.
  await page.route(
    (url) => url.pathname === '/registrations/events',
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      const response = await route.fetch()
      const list = (await response.json()) as { items: { name: string; places_left: number }[] }
      for (const item of list.items) {
        if (item.name === KITE_AFTERNOON) item.places_left = 2
      }
      return route.fulfill({ response, json: list })
    },
  )
  const sent: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST') sent.push(request.url())
  })
  await signIn(page, ACCOUNTS.attendee7)
  await page.goto(UPCOMING_EVENTS_PATH)
  sent.length = 0
  await eventCard(page, KITE_AFTERNOON)
    .getByRole('button', { name: `Register for ${KITE_AFTERNOON}` })
    .click()

  const dialog = confirmDetailsDialog(page)
  await addGuest(page, 1, { name: 'Guest 1' })

  await expect(addGuestButton(page)).toBeDisabled()
  await expect(dialog).toContainText(NO_PLACES_FOR_MORE_GUESTS_MESSAGE)
  await expect(dialog).not.toContainText(TOO_MANY_GUESTS_MESSAGE)
  expect(sent).toEqual([])
})

test('18.5 AC12: Change guests allows only as many guests as there are places for', async ({
  page,
}) => {
  // Hana's registrations are the server's own, with no places left for the kite afternoon's
  // guests: a state the seed cannot reach without filling the event. Nothing is sent.
  await page.route(
    (url) => url.pathname === '/registrations',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || request.method() !== 'GET') {
        return route.fallback()
      }
      const response = await route.fetch()
      const mine = (await response.json()) as {
        event_name: string
        guests: unknown[]
        max_guests: number
      }[]
      for (const registration of mine) {
        if (registration.event_name === KITE_AFTERNOON) {
          registration.guests = []
          registration.max_guests = 0
        }
      }
      return route.fulfill({ response, json: mine })
    },
  )
  await signIn(page, ACCOUNTS.attendee8)
  await page.goto(MY_REGISTRATIONS_PATH)
  await eventCard(page, KITE_AFTERNOON)
    .getByRole('button', { name: `Change guests for ${KITE_AFTERNOON}` })
    .click()

  const dialog = page.getByRole('dialog', { name: CHANGE_GUESTS_DIALOG })
  await expect(addGuestButton(page)).toBeDisabled()
  await expect(dialog).toContainText(NO_PLACES_FOR_MORE_GUESTS_MESSAGE)
})
