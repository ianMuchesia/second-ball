import { expect, test } from "@playwright/test";

test("demo bundle: jump to 63', open the evidence, Stonebridge is highlighted", async ({ page }) => {
  await page.goto("/runs/e2e");
  await expect(page.getByTestId("scoreboard")).toBeVisible();
  await expect(page.getByText("SCRIPTED DEMO")).toBeVisible();

  await page.locator('[data-testid^="marker-red_card-"]').first().click();
  await expect(page.getByTestId("clock")).toHaveText(/^63:/);

  await page.getByTestId("evidence-open").click();
  const drawer = page.getByTestId("evidence-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("Ilya Stonebridge (Riverside, left centre-back) fouls: red card");
  await expect(drawer).toContainText("last-man foul on a counter");

  await expect(page.getByTestId("player-riverside_athletic-5")).toHaveClass(/highlighted/);
  await expect(page.getByTestId("tag-riverside_athletic-5")).toHaveText("Stonebridge");
});

test("producer: a test error goes through the real Verifier and is labelled", async ({ page }) => {
  await page.goto("/runs/e2e/producer");
  await page.getByRole("button", { name: "Inject a test error" }).click();
  const box = page.getByTestId("injection");
  await expect(box).toContainText("TEST INJECTION");
  await expect(box).toContainText("Verifier: rejected");
  await expect(page.locator(".audit")).toContainText("inject test error");
});

test("producer: a pulled line leaves the broadcast, and comes back when restored", async ({ page, request }) => {
  const run = await (await request.get("/api/runs/e2e")).json();
  const line = run.overlays.find(
    (o: { slot: string; status: string; kind: string; overlay_id: string }) =>
      o.slot === "narrative" && o.status === "aired" && o.kind === "goal" && o.overlay_id.endsWith("-casual"),
  );
  const at = `/runs/e2e?t=${line.t + 5}`;
  await page.goto(at);
  await expect(page.getByTestId("lower-third")).toContainText(line.text.en);

  await page.goto("/runs/e2e/producer");
  await page.getByTestId(`pull-${line.overlay_id}`).click();
  await expect(page.getByTestId("on-air")).toContainText("pulled");
  await page.goto(at);
  await expect(page.getByTestId("scoreboard")).toBeVisible();
  await expect(page.getByText(line.text.en)).toHaveCount(0);

  await page.goto("/runs/e2e/producer");
  await page.getByRole("button", { name: "Restore" }).first().click();
  await page.goto(at);
  await expect(page.getByTestId("lower-third")).toContainText(line.text.en);
});
