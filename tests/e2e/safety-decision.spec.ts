/**
 * Story 21.2 - fe/be: request a safety review, record the safety decision, confirm the event.
 * AC1 the assigned coordinator requests a safety review of a secured event from its page, and it
 *     moves to Awaiting safety check. What counts as secured is a backend case.
 * AC2 the Safety Officer reviews the event against the review factors and records a decision,
 *     which then shows under the previous reviews.
 * AC4 requesting changes takes findings - a factor, what must change and the arrangement to
 *     rebook - which the coordinator reads on the event page.
 * AC7 the coordinator confirms an approved event, and it moves to Confirmed.
 * AC10 the form will not send a finding that says nothing; no notes (AC9), the length
 *     limits and the other refusals are backend cases.
 * AC12 resubmitting with a flagged arrangement unchanged warns, and the coordinator can submit
 *     anyway.
 * Every other AC (AC3, AC5, AC6, AC8, AC11, AC13-AC21) is a backend case:
 * backend/tests/safety/test_safety_request.py, test_safety_decision.py, test_confirm_event.py.
 *
 * Each test has a seeded event of its own (EVENTS.codingBootcamp, cyberClinic, dataSummit,
 * aiWorkshop), so tests running in parallel never share one.
 */
import { expect, test, type Page } from "@playwright/test";
import { ACCOUNTS, EVENTS, signIn } from "./support";

function section(page: Page, name: string) {
  return page.getByRole("region", { name, exact: true });
}

function statusShown(page: Page, label: string) {
  return page.getByRole("main").getByText(label, { exact: true }).first();
}

test("21.2 AC1: the coordinator requests a safety review of a secured event", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator);
  await page.goto(`/events/${EVENTS.codingBootcamp}`);

  const safety = section(page, "Safety review");
  await expect(safety).toContainText("Not reviewed yet.");
  await safety.getByRole("button", { name: "Request safety review" }).click();

  await expect(statusShown(page, "Awaiting safety check")).toBeVisible();
  await expect(
    safety.getByRole("button", { name: "Request safety review" }),
  ).toHaveCount(0);
});

test("21.2 AC2/AC4/AC10: the officer requests changes with findings the coordinator then reads", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.safetyOfficer);
  await page.goto(`/safety-checks/${EVENTS.cyberClinic}`);

  const factors = section(page, "Review factors");
  await expect(factors).toContainText("Emergency access");
  await expect(factors).toContainText("Crowd movement");

  const decision = section(page, "Decision");
  await decision.getByRole("radio", { name: "Request changes" }).check();
  await decision.getByRole("button", { name: "Record decision" }).click();
  await expect(
    decision.getByText("Say what must change for each finding."),
  ).toBeVisible();

  const finding = decision.getByRole("group", { name: "Finding 1" });
  await finding
    .getByLabel("Factor")
    .selectOption({ label: "Emergency access" });
  await finding
    .getByLabel("What must change")
    .fill("Keep the fire exit beside the stage clear.");
  await finding
    .getByLabel("Arrangement to rebook")
    .selectOption({ label: "Venue bookings" });
  await decision.getByRole("button", { name: "Record decision" }).click();

  const reviews = section(page, "Previous reviews");
  await expect(reviews).toContainText("Changes requested");
  await expect(reviews).toContainText(
    "Keep the fire exit beside the stage clear.",
  );
  await expect(section(page, "Decision")).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, ACCOUNTS.coordinator);
  await page.goto(`/events/${EVENTS.cyberClinic}`);
  const safety = section(page, "Safety review");
  await expect(safety).toContainText("Changes requested");
  await expect(safety).toContainText("Emergency access");
  await expect(safety).toContainText(
    "Keep the fire exit beside the stage clear.",
  );
  await expect(safety).toContainText("Venue bookings must change");
});

test("21.2 AC12: resubmitting with the flagged venue unchanged warns, and can be sent anyway", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator);
  await page.goto(`/events/${EVENTS.dataSummit}`);

  const safety = section(page, "Safety review");
  await expect(safety).toContainText("Book a room with a second exit");
  await safety.getByRole("button", { name: "Request safety review" }).click();

  const warning = page.getByRole("dialog", {
    name: "Flagged arrangements unchanged",
  });
  await expect(warning).toContainText(
    "The venue bookings the Safety Officer flagged have not changed",
  );
  await warning.getByRole("button", { name: "Cancel" }).click();
  await expect(warning).toHaveCount(0);
  await expect(statusShown(page, "Planning")).toBeVisible();

  await safety.getByRole("button", { name: "Request safety review" }).click();
  await warning.getByRole("button", { name: "Submit anyway" }).click();
  await expect(statusShown(page, "Awaiting safety check")).toBeVisible();
});

test("21.2 AC2/AC7: the officer approves, then the coordinator confirms the event", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.safetyOfficer);
  await page.goto(`/safety-checks/${EVENTS.aiWorkshop}`);
  const decision = section(page, "Decision");
  await decision.getByRole("radio", { name: "Approve" }).check();
  await decision.getByRole("button", { name: "Record decision" }).click();
  await expect(section(page, "Previous reviews")).toContainText("Approved");

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, ACCOUNTS.coordinator);
  await page.goto(`/events/${EVENTS.aiWorkshop}`);
  const safety = section(page, "Safety review");
  await expect(safety).toContainText("Approved");
  await safety.getByRole("button", { name: "Confirm event" }).click();

  await expect(statusShown(page, "Confirmed")).toBeVisible();
  await expect(
    safety.getByRole("button", { name: "Confirm event" }),
  ).toHaveCount(0);
});
