import { expect, type Page, test } from "@playwright/test";

// Phase 5: personalization changes selection and wording, never facts.

interface Ev {
  t: number;
  minute: number;
  type: string;
  outcome: string;
}

async function feedTexts(page: Page): Promise<string[]> {
  await page.getByTestId("tab-moments").click();
  return page.getByTestId("feed").locator("li .text").allInnerTexts();
}

test("the profile is kept for this viewer after a reload", async ({ page }) => {
  await page.goto("/runs/e2e?t=600");
  await page.getByTestId("persona").selectOption("analyst");
  await page.getByTestId("favourite").selectOption("harbour_town");
  await page.getByTestId("follow").selectOption("harbour_town-8");
  await page.getByTestId("pin").selectOption("pass_accuracy");
  await page.reload();
  await expect(page.getByTestId("persona")).toHaveValue("analyst");
  await expect(page.getByTestId("favourite")).toHaveValue("harbour_town");
  await expect(page.getByTestId("follow")).toHaveValue("harbour_town-8");
  await expect(page.getByTestId("pin")).toHaveValue("pass_accuracy");
});

test("a favourite club changes the order of key moments, not their content", async ({ page, request }) => {
  const events: Ev[] = await (await request.get("/api/runs/e2e/events")).json();
  await page.goto(`/runs/e2e?t=${events[events.length - 1].t}`);
  const neutral = await feedTexts(page);
  await page.getByTestId("favourite").selectOption("riverside_athletic");
  const riverside = await feedTexts(page);
  await page.getByTestId("favourite").selectOption("harbour_town");
  const harbour = await feedTexts(page);
  expect([...riverside].sort()).toEqual([...neutral].sort());
  expect([...harbour].sort()).toEqual([...neutral].sort());
  expect(riverside).not.toEqual(harbour);
  // Neutral wording: the same lines, word for word, whoever you support.
  for (const line of riverside) expect(neutral).toContain(line);
});

test("fan and analyst get two different screens", async ({ page, request }) => {
  const events: Ev[] = await (await request.get("/api/runs/e2e/events")).json();
  const goal = events.find((e) => e.minute === 34 && e.type.startsWith("shot") && e.outcome === "success")!;
  await page.goto(`/runs/e2e?t=${goal.t + 10}`);
  // Fan: plain words, no evidence drawer until asked, no extra indicators.
  await expect(page.getByTestId("lower-third")).toBeVisible();
  await expect(page.getByTestId("evidence-drawer")).toHaveCount(0);
  await page.getByTestId("tab-stats").click();
  await expect(page.getByTestId("analyst-metrics")).toHaveCount(0);
  // Analyst: the drawer is open on the line on air, more indicators with
  // units and Wilson ranges.
  await page.getByTestId("persona").selectOption("analyst");
  await expect(page.getByTestId("evidence-drawer")).toContainText("Evidence: goal (34')");
  await page.getByLabel("close").first().click();
  await expect(page.getByTestId("evidence-drawer")).toHaveCount(0);
  await expect(page.getByTestId("metric-pass_accuracy")).toContainText("95%");
  await expect(page.getByTestId("analyst-metrics")).toContainText("xG");
});

test("following a player: name always on, his card by position, every number with its events", async ({ page }) => {
  await page.goto("/runs/e2e?t=3000");
  await page.getByTestId("follow").selectOption("harbour_town-8");
  await expect(page.getByTestId("tag-harbour_town-8")).toHaveText("QUILL");
  await page.getByTestId("tab-player").click();
  const card = page.getByTestId("player-card");
  await expect(card).toContainText("Matthias Quill");
  await expect(card.locator("[data-testid^=player-stat-]")).toHaveCount(3); // a fan's top three
  await expect(page.getByTestId("touch-map")).toHaveCount(0);
  await expect(page.getByTestId("omitted")).toContainText("distance covered");
  await expect(page.getByTestId("player-recap")).toContainText("HALF-TIME");
  await page.getByTestId("persona").selectOption("analyst");
  await expect(card.locator("[data-testid^=player-stat-]")).toHaveCount(6);
  await expect(page.getByTestId("player-stat-pass_pct")).toContainText(/\d+% \(\d+–\d+%\)/);
  await expect(page.getByTestId("touch-map").locator("circle.touch").first()).toBeVisible();
  // No number without its events.
  await page.getByTestId("player-stat-passes_completed").locator("button").click();
  const modal = page.getByTestId("events-modal");
  await expect(modal).toContainText("Counted by code from");
  await expect(modal.locator("li").first()).toContainText("Matthias Quill");
});

test("a pinned metric stays on screen with its plain definition and evidence", async ({ page }) => {
  await page.goto("/runs/e2e?t=2400");
  await page.getByTestId("pin").selectOption("pass_accuracy");
  const pinned = page.getByTestId("pinned-metric");
  await expect(pinned).toContainText("Completed passes");
  await expect(pinned).toContainText("RIV");
  await pinned.getByTestId("metric-evidence").click();
  await expect(page.getByTestId("events-modal").locator("li").first()).toBeVisible();
  await page.getByTestId("tab-stats").click(); // still there on another tab
  await expect(pinned).toBeVisible();
});
