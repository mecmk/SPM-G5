/**
 * Story 19.3 - fe: assess a change request's impact before deciding it.
 *
 * AC1 the assigned coordinator sees what a pending change would affect - on the request, in the
 *     queue, and in the approval dialog - as one row each for venue bookings, equipment and registrations that
 *     says at a glance how much is affected and opens onto each arrangement, listed on its own
 *     with why; and a change that touches nothing arranged says so.
 * AC2 each affected arrangement says what approving does to it: a booking the change no longer
 *     fits is cancelled, Venue Staff are told and need do nothing, and a replacement is requested
 *     from the event page (story 19.2's own behaviour). Each booking also says where it stands
 *     now, so a decision Venue Staff make meanwhile shows on it.
 * AC7 an impact that changed after the approval dialog opened - here, another session adding
 *     equipment the new dates must hold - is shown again, marked as updated, and nothing is
 *     applied until the coordinator approves again.
 * Definition of Done: the assessment reads at 1280 x 720 and at 390 x 844, the dialog's buttons
 *     stay on screen, and the page never scrolls sideways.
 *
 * Which bookings, items and registrations are affected and why, the boundaries (AC4),
 * unavailability and shortfalls (AC5), who may see the assessment (AC6), that assessing writes
 * nothing (AC3), and that its predictions are what the approval then does (AC2) are backend
 * cases: backend/tests/change_requests/test_assess_change_request_impact.py.
 *
 * Each test builds its own event (`approvedEvent`). The one that books venues dates it well away
 * from the day other specs' fresh events fall on, so the venues it requests are free and the holds
 * it leaves hide nothing another spec looks for.
 */
import { expect, test, type Page } from "@playwright/test";
import {
  approvedEvent,
  changeRequests,
  inFuture,
  signIn,
  venueCard,
} from "./support";

const CHANGE_REASON = "The keynote speaker can only come a week later.";
const GRAND_HALL = "Grand Hall";
const EXHIBITION_FOYER = "Exhibition Foyer";
const NO_IMPACT = "No existing arrangements are affected.";
const QUEUE_PATH = "/change-requests/review";
const IMPACT_CHANGED =
  "The impact of this change has changed since you opened it. Review the updated impact, then approve again.";

/** A day for an event that books venues: over a year ahead, spread out so reruns rarely meet,
 *  and early enough that a week later is within the two years an event may be planned ahead. */
function farDay(): number {
  return 400 + Math.floor(Math.random() * 120);
}

/** As the organiser, on the event's page: ask to move it a week later. */
async function requestDateChange(page: Page, days: number) {
  await changeRequests(page)
    .getByRole("button", { name: "Request a change" })
    .click();
  await changeRequests(page)
    .getByLabel("What to change")
    .selectOption({ label: "Date and time" });
  await changeRequests(page)
    .getByLabel("New start")
    .fill(inFuture(days + 7, 9));
  await changeRequests(page)
    .getByLabel("New end")
    .fill(inFuture(days + 7, 17));
  await changeRequests(page)
    .getByLabel("Reason for the change")
    .fill(CHANGE_REASON);
  await changeRequests(page)
    .getByRole("button", { name: "Send change request" })
    .click();
  await expect(changeRequests(page).getByRole("listitem")).toContainText(
    "Pending",
  );
}

/** As the coordinator, through story 12.5's own steps: Grand Hall for the event's Main venue,
 *  then Exhibition Foyer as an additional venue. */
async function bookTwoVenues(page: Page, eventId: string, name: string) {
  await page.goto(`/events/${eventId}`);
  await page.getByRole("link", { name: "Find a venue" }).click();
  await expect(
    page.getByRole("region", { name: `Finding a venue for ${name}` }),
  ).toBeVisible();
  await venueCard(page, GRAND_HALL)
    .getByRole("link", { name: "Request this venue" })
    .click();
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();

  await page.getByRole("link", { name: "All required venues booked" }).click();
  await venueCard(page, EXHIBITION_FOYER)
    .getByRole("link", { name: "Request this venue" })
    .click();
  await page.getByRole("button", { name: "Send request" }).click();
  // The event's page reloads its bookings, equipment and change requests: give it time under load.
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible({
    timeout: 15_000,
  });
}

function approvalDialog(page: Page) {
  return page.getByRole("dialog", { name: "Approve this change?" });
}

async function hasNoSidewaysScroll(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
}

test("19.3 AC1/AC2: each booked venue the change cancels is listed with why and what happens next", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const days = farDay();
  const { eventId, name, coordinator } = await approvedEvent(
    page,
    "Impact venues",
    days,
  );
  await requestDateChange(page, days);
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, coordinator);
  await bookTwoVenues(page, eventId, name);

  // On the request, at the desktop size Playwright opens with (1280 x 720): the category's row
  // says it at a glance, and opens onto each booking.
  await changeRequests(page)
    .getByRole("button", { name: "Show impact" })
    .click();
  const venueRow = changeRequests(page).getByRole("button", {
    name: /^Venue bookings/,
  });
  await expect(venueRow).toContainText("2 affected");
  await expect(venueRow).toContainText(
    "2 bookings will be cancelled on approval.",
  );
  await expect(
    changeRequests(page).getByRole("button", { name: /^Registrations/ }),
  ).toHaveCount(0);
  await expect(
    changeRequests(page).getByText("No registrations are affected."),
  ).toBeVisible();
  await venueRow.click();
  const bookings = changeRequests(page).getByRole("region", {
    name: "Venue bookings affected",
  });
  // Each booking's card ends with what happens after approval; its venue checks are a list too.
  const bookingCards = bookings
    .getByRole("listitem")
    .filter({ hasText: "After approval" });
  await expect(bookingCards).toHaveCount(2);
  const hall = bookingCards.filter({ hasText: GRAND_HALL });
  await expect(hall).toContainText("Main venue");
  await expect(hall).toContainText("Pending request for");
  await expect(hall).toContainText("Will be cancelled");
  await expect(hall).toContainText(
    "Its booked times no longer cover the times the change needs.",
  );
  await expect(hall).toContainText(
    "Venue Staff are told, and need do nothing; request a replacement from the event page.",
  );
  const foyer = bookingCards.filter({ hasText: EXHIBITION_FOYER });
  await expect(foyer).toContainText("Additional venue");
  await expect(foyer).toContainText("Will be cancelled");
  expect(await hasNoSidewaysScroll(page)).toBe(true);

  // In the approval dialog, on a phone.
  await page.setViewportSize({ width: 390, height: 844 });
  await changeRequests(page)
    .getByRole("button", { name: "Approve", exact: true })
    .click();
  const dialog = approvalDialog(page);
  await dialog.getByRole("button", { name: /^Venue bookings/ }).click();
  await expect(
    dialog
      .getByRole("region", { name: "Venue bookings affected" })
      .getByRole("listitem")
      .filter({ hasText: "After approval" }),
  ).toHaveCount(2);
  await expect(
    dialog.getByRole("button", { name: "Approve" }),
  ).toBeInViewport();
  await expect(
    dialog.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeInViewport();
  expect(await hasNoSidewaysScroll(page)).toBe(true);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  // The request's own card - the assessment shown under it has list items of its own.
  await expect(
    changeRequests(page).getByRole("listitem").first(),
  ).toContainText("Pending");
});

test("19.3 AC1: a change that touches nothing arranged says so, on the event and in the queue", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const { eventId, name, coordinator } = await approvedEvent(
    page,
    "Impact none",
  );
  await changeRequests(page)
    .getByRole("button", { name: "Request a change" })
    .click();
  await changeRequests(page)
    .getByLabel("What to change")
    .selectOption({ label: "Expected attendance" });
  await changeRequests(page).getByLabel("New expected attendance").fill("150");
  await changeRequests(page)
    .getByLabel("Reason for the change")
    .fill(CHANGE_REASON);
  await changeRequests(page)
    .getByRole("button", { name: "Send change request" })
    .click();
  await expect(changeRequests(page).getByRole("listitem")).toContainText(
    "Pending",
  );

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, coordinator);
  await page.goto(`/events/${eventId}`);
  await changeRequests(page)
    .getByRole("button", { name: "Show impact" })
    .click();

  await expect(changeRequests(page).getByText(NO_IMPACT)).toBeVisible();

  // The same, from the coordinator's queue.
  await page.goto(QUEUE_PATH);
  const entry = page
    .getByRole("list", { name: "Pending change requests" })
    .getByRole("listitem")
    .filter({ hasText: name });
  await entry.getByRole("button", { name: "Show impact" }).click();
  await expect(entry.getByText(NO_IMPACT)).toBeVisible();
});

test("19.3 AC7: an impact that changed after the dialog opened is shown again before anything is applied", async ({
  page,
  browser,
}, testInfo) => {
  test.setTimeout(150_000);
  const { eventId, coordinator } = await approvedEvent(page, "Impact changed");
  await requestDateChange(page, 30);
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, coordinator);
  await page.goto(`/events/${eventId}`);
  await changeRequests(page)
    .getByRole("button", { name: "Approve", exact: true })
    .click();
  const dialog = approvalDialog(page);
  await expect(dialog.getByText(NO_IMPACT)).toBeVisible();

  // Meanwhile, in another session, the coordinator records a projector for the event (15.1),
  // which the new dates would have to hold.
  const elsewhere = await browser.newContext({
    baseURL: testInfo.project.use.baseURL,
  });
  const other = await elsewhere.newPage();
  await signIn(other, coordinator);
  await other.goto(`/events/${eventId}`);
  const addForm = other
    .getByRole("region", { name: "Equipment requirements" })
    .getByRole("form", { name: "Add equipment" });
  await addForm.getByLabel("Equipment type").selectOption("PROJECTOR_PORTABLE");
  await addForm.getByLabel("Quantity").fill("1");
  await addForm.getByRole("button", { name: "Add item" }).click();
  await expect(
    other
      .getByRole("region", { name: "Equipment requirements" })
      .getByRole("listitem"),
  ).toContainText("Portable projector");
  await elsewhere.close();

  // Approving on the assessment seen first is refused, and the updated one is shown instead.
  await dialog.getByRole("button", { name: "Approve" }).click();
  await expect(dialog.getByRole("alert")).toHaveText(IMPACT_CHANGED);
  await expect(dialog).toContainText("Updated impact of approving this change");
  const equipmentRow = dialog.getByRole("button", { name: /^Equipment/ });
  await expect(equipmentRow).toContainText(
    "1 item held again for the new dates.",
  );
  await equipmentRow.click();
  await expect(
    dialog.getByRole("region", { name: "Equipment affected" }),
  ).toContainText("Portable projector");
  await expect(dialog.getByText(NO_IMPACT)).toHaveCount(0);

  // Approving again, on what is now shown, applies the change.
  await dialog.getByRole("button", { name: "Approve" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(changeRequests(page).getByRole("listitem")).toContainText(
    "Approved",
  );
});
