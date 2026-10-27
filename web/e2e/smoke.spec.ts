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
  await expect(page.getByTestId("tag-riverside_athletic-5")).toHaveText(/stonebridge/i);
});

test("control room: with approve before air, a line reaches the broadcast only once approved", async ({ page, request }) => {
  const run = await (await request.get("/api/runs/e2e")).json();
  // The analyst's goal line (the fan's is the pull test's below).
  const line = run.overlays.find(
    (o: { slot: string; status: string; kind: string; overlay_id: string }) =>
      o.slot === "narrative" && o.status === "aired" && o.kind === "goal" && o.overlay_id.endsWith("-analyst"),
  );
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto(`/runs/e2e/producer?t=${line.t + 3}`);
  await expect(page.getByTestId("gate")).toBeChecked(); // on at a first visit
  const broadcast = page.locator(".room-broadcast");
  await broadcast.getByTestId("persona").selectOption("analyst");
  await expect(broadcast.getByTestId("scoreboard")).toBeVisible();
  await expect(broadcast.getByText(line.text.en)).toHaveCount(0);
  await page.getByTestId(`approve-${line.overlay_id}`).click();
  await expect(broadcast.getByTestId("lower-third")).toContainText(line.text.en);
  await expect(page.getByTestId("evidence-drawer")).toHaveCount(0); // not over the desk
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
  // A big chance's fan line: the goal's lines are other tests' (they run at
  // the same time against the same server, and a pull is saved there).
  const line = run.overlays.find(
    (o: { slot: string; status: string; kind: string; overlay_id: string }) =>
      o.slot === "narrative" && o.status === "aired" && o.kind === "big_chance" && o.overlay_id.endsWith("-casual"),
  );
  const at = `/runs/e2e?t=${line.t + 5}`;
  await page.goto(at);
  await expect(page.getByTestId("lower-third")).toContainText(line.text.en);

  // The control room at that minute (a line reaches the desk when the match
  // does), airing as recorded: the line is on air.
  await page.goto(`/runs/e2e/producer?t=${line.t + 5}`);
  await page.getByTestId("gate").uncheck();
  const pull = page.getByTestId(`pull-${line.overlay_id}`);
  await expect(pull).toBeDisabled(); // never without a reason
  await page.getByLabel("Reason (logged)").fill("wrong player named");
  await pull.click();
  await expect(page.getByTestId("incoming")).toContainText("rejected");
  await page.goto(at);
  await expect(page.getByTestId("scoreboard")).toBeVisible();
  await expect(page.getByText(line.text.en)).toHaveCount(0);

  await page.goto(`/runs/e2e/producer?t=${line.t + 5}`);
  await page.getByLabel("Reason (logged)").fill("checked: it was right");
  await page.getByRole("button", { name: "Restore" }).first().click();
  await page.goto(at);
  await expect(page.getByTestId("lower-third")).toContainText(line.text.en);
});
