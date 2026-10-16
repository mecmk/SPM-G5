/**
 * Story 21.1 - fe/be: view events awaiting the operational safety check.
 * AC1 the Safety Officer's sidebar is rbac.spec.ts's; the role's permissions are a backend case.
 * AC2 the queue lists each awaiting event with its name, dates, expected attendance, approved
 *     venues and status, oldest first. Which statuses and bookings count is a backend case.
 *     Team request beyond the AC: Pending (the queue itself), Accepted and Declined tabs, by the
 *     latest review of an event no longer awaiting the check, and All. Which review decides the
 *     tab is a backend case.
 * AC3 an event's page shows its description, attendance, each approved venue, accessibility needs,
 *     accepted equipment with technical notes, and the previous reviews.
 * AC4 a venue whose booking must hold more people than the venue holds in the booked layout is
 *     flagged Over capacity, with both figures shown. The boundary (capacity and capacity + 1),
 *     the layout's capacity and a multi-venue event's smaller rooms are backend cases.
 * AC5 a detail never recorded shows "Not recorded", and what changed since the last review is
 *     listed. Which facts count as changed is a backend case.
 * AC6 another role cannot reach the pages. The API's 401/403 refusals are backend cases:
 *     backend/tests/safety/test_safety_check_queue.py.
 *
 * Both seeded events (EVENTS.harbourConcert, EVENTS.bookFair) are dedicated to this spec and
 * only read here. The concert expects 300 at the 250-seat Exhibition Foyer, whose operating hours
 * are not recorded, and has never been reviewed. The book fair was sent back once, when it
 * expected 120 people and two microphones. The food festival (approved) and the night walk (sent
 * back) are the Accepted and Declined tabs' seeded events, also only read here.
 */
import { expect, test, type Page } from "@playwright/test";
import { ACCOUNTS, EVENTS, signIn } from "./support";

const QUEUE_PATH = "/safety-checks";
const CONCERT = "Harbour Lights Concert";
const BOOK_FAIR = "Riverside Book Fair";
const FOOD_FESTIVAL = "Marina Food Festival";
const NIGHT_WALK = "Lantern Night Walk";
const SEEDED_TITLES = /Harbour|Riverside|Marina|Lantern/;

function queueCard(page: Page, name: string) {
  return page
    .getByRole("listitem")
    .filter({ has: page.getByRole("heading", { name }) });
}

function section(page: Page, name: string) {
  return page.getByRole("region", { name, exact: true });
}

test("21.1 AC2: the Safety Officer opens the queue and sees each awaiting event, oldest first", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.safetyOfficer);
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Safety checks", exact: true })
    .click();

  await expect(page).toHaveURL(new RegExp(`${QUEUE_PATH}$`));
  await expect(
    page.getByRole("heading", { name: "Safety Checks", level: 1 }),
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: "Pending" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  // Story 21.2's spec moves its own events through the queue in parallel, so the count varies.
  await expect(
    page.getByRole("tab", { name: /^Pending \(\d+\)$/ }),
  ).toBeVisible();

  const concert = queueCard(page, CONCERT);
  await expect(concert).toContainText("16 Aug 2028");
  await expect(concert).toContainText("300");
  await expect(concert).toContainText("Exhibition Foyer");
  await expect(concert).toContainText("Awaiting safety check");
  await expect(queueCard(page, BOOK_FAIR)).toContainText("Grand Hall");

  const titles = page
    .getByRole("heading", { level: 3 })
    .filter({ hasText: SEEDED_TITLES });
  await expect(titles).toHaveText([CONCERT, BOOK_FAIR]);
});

test("21.1 AC2: the Accepted, Declined and All tabs list reviewed events by their latest review", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.safetyOfficer);
  await page.goto(QUEUE_PATH);
  const titles = page
    .getByRole("heading", { level: 3 })
    .filter({ hasText: SEEDED_TITLES });
  await expect(titles).toHaveText([CONCERT, BOOK_FAIR]);

  await page.getByRole("tab", { name: "Accepted" }).click();
  await expect(titles).toHaveText([FOOD_FESTIVAL]);

  await page.getByRole("tab", { name: "Declined" }).click();
  await expect(titles).toHaveText([NIGHT_WALK]);

  await page.getByRole("tab", { name: "All" }).click();
  await expect(titles).toHaveText([
    NIGHT_WALK,
    FOOD_FESTIVAL,
    CONCERT,
    BOOK_FAIR,
  ]);
  await expect(queueCard(page, FOOD_FESTIVAL)).toContainText("Confirmed");
  await expect(queueCard(page, NIGHT_WALK)).toContainText("Planning");
});

test("21.1 AC3: a declined event opens with the review that sent it back", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.safetyOfficer);
  await page.goto(QUEUE_PATH);

  await page.getByRole("tab", { name: "Declined" }).click();
  await queueCard(page, NIGHT_WALK)
    .getByRole("link", { name: NIGHT_WALK })
    .click();

  await expect(page).toHaveURL(
    new RegExp(`${QUEUE_PATH}/${EVENTS.nightWalk}$`),
  );
  await expect(
    page.getByRole("heading", { name: NIGHT_WALK, level: 1 }),
  ).toBeVisible();
  await expect(section(page, "Previous reviews")).toContainText(
    "Changes requested",
  );
});

test("21.1 AC3/AC5: an event shows what affects its safety and what changed since its last review", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.safetyOfficer);
  await page.goto(QUEUE_PATH);

  await queueCard(page, BOOK_FAIR)
    .getByRole("link", { name: BOOK_FAIR })
    .click();

  await expect(page).toHaveURL(new RegExp(`${QUEUE_PATH}/${EVENTS.bookFair}$`));
  await expect(
    page.getByRole("heading", { name: BOOK_FAIR, level: 1 }),
  ).toBeVisible();
  await expect(section(page, "Event")).toContainText(
    "Publisher stalls with author talks through the day.",
  );
  await expect(section(page, "Event")).toContainText("150");
  await expect(section(page, "Venues")).toContainText("Grand Hall");
  await expect(section(page, "Venues")).toContainText("Exhibition");
  await expect(section(page, "Equipment")).toContainText("Author talks");

  const changes = section(page, "Changes since last review");
  await expect(changes).toContainText("Expected attendance");
  await expect(changes).toContainText("120");
  await expect(changes).toContainText("Equipment");
  await expect(changes).toContainText("2 × Wireless microphone");
  await expect(changes).not.toContainText("WIRELESS_MIC");
  await expect(changes).not.toContainText("Description");

  const reviews = section(page, "Previous reviews");
  await expect(reviews).toContainText("Changes requested");
  await expect(reviews).toContainText("Sam Safety");

  await page.getByRole("link", { name: "← Safety Checks" }).click();
  await expect(page).toHaveURL(new RegExp(`${QUEUE_PATH}$`));
});

test("21.1 AC3/AC4: a venue the event outgrows is flagged Over capacity", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.safetyOfficer);

  await page.goto(`${QUEUE_PATH}/${EVENTS.harbourConcert}`);
  await expect(section(page, "Venues")).toContainText("Exhibition Foyer");
  await expect(
    section(page, "Venues").getByText("Over capacity"),
  ).toBeVisible();
  await expect(section(page, "Venues")).toContainText(
    "Capacity in this layout250",
  );
  await expect(section(page, "Venues")).toContainText("People to hold300");
  await expect(section(page, "Accessibility")).toContainText(
    "A ramp up to the viewing area",
  );
  await expect(section(page, "Equipment")).toContainText(
    "Stage left and right; cables taped down",
  );

  await page.goto(`${QUEUE_PATH}/${EVENTS.bookFair}`);
  await expect(section(page, "Venues")).toContainText("Grand Hall");
  await expect(section(page, "Venues").getByText("Over capacity")).toHaveCount(
    0,
  );
});

test("21.1 AC5: details never recorded show Not recorded, and a first check has no changes", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.safetyOfficer);
  await page.goto(`${QUEUE_PATH}/${EVENTS.harbourConcert}`);

  await expect(section(page, "Venues")).toContainText("Operating hours");
  await expect(section(page, "Venues")).toContainText("Not recorded");
  await expect(section(page, "Changes since last review")).toContainText(
    "Not reviewed before, so there is nothing to compare.",
  );
  await expect(section(page, "Previous reviews")).toContainText(
    "No previous reviews.",
  );
});

test("21.1 AC6: another role is refused the safety check pages", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator);

  await page.goto(QUEUE_PATH);
  await expect(
    page.getByRole("heading", { name: "Not permitted" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Safety Checks" }),
  ).toHaveCount(0);

  await page.goto(`${QUEUE_PATH}/${EVENTS.harbourConcert}`);
  await expect(
    page.getByRole("heading", { name: "Not permitted" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: CONCERT })).toHaveCount(0);
});
