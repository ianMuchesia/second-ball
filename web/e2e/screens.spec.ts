import { test } from "@playwright/test";

// Review screenshots at 2', 34', 63' and 88' (SCREENS=1 RUN=<bundle>):
// written to docs/screens/. Not part of the normal test run.
test.skip(!process.env.SCREENS, "set SCREENS=1 to write the review screenshots");

const RUN = process.env.RUN ?? "e2e";

test("review screenshots", async ({ page, request }) => {
  const events: { t: number; minute: number; type: string; outcome: string }[] = await (
    await request.get(`/api/runs/${RUN}/events`)
  ).json();
  const at = (minute: number, pick?: (e: (typeof events)[0]) => boolean) =>
    (events.find((e) => e.minute === minute && (!pick || pick(e))) ?? events.find((e) => e.minute >= minute))!.t;
  const goal = (e: { type: string; outcome: string }) => e.type.startsWith("shot") && e.outcome === "success";
  const shots: [string, number, "none" | "red" | "why"][] = [
    ["02", at(2), "none"],
    ["34", at(34, goal) + 20, "why"],
    ["63", at(63, (e) => e.outcome === "red_card"), "red"],
    ["88", at(88, goal) + 20, "none"],
  ];
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const [name, t, evidence] of shots) {
    await page.goto(`/runs/${RUN}?t=${t}`);
    await page.getByTestId("scoreboard").waitFor();
    if (evidence === "red") {
      await page.locator('[data-testid^="marker-red_card-"]').first().click();
      await page.getByTestId("evidence-open").click();
    }
    if (evidence === "why") await page.getByTestId("why").click();
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `../docs/screens/${name}.png` });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/runs/${RUN}?t=${at(34, goal) + 20}`);
  await page.getByTestId("scoreboard").waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({ path: "../docs/screens/34-phone.png", fullPage: true });
});

test("review screenshots: personalization (analyst and fan)", async ({ page, request }) => {
  const events: { t: number; minute: number; type: string; outcome: string }[] = await (
    await request.get(`/api/runs/${RUN}/events`)
  ).json();
  const at = (minute: number) => events.find((e) => e.minute >= minute)!.t;
  const views: [string, Record<string, unknown>, number][] = [
    [
      "p5-analyst",
      { persona: "analyst", favouriteClub: "harbour_town", followedPlayer: "harbour_town-8", pinnedMetric: "pass_accuracy" },
      at(47),
    ],
    ["p5-fan", { persona: "casual", followedPlayer: "harbour_town-11", pinnedMetric: "xg" }, at(47)],
  ];
  await page.setViewportSize({ width: 1440, height: 1100 });
  for (const [name, profile, t] of views) {
    await page.addInitScript((p) => localStorage.setItem("second-ball.profile.v1", JSON.stringify(p)), profile);
    await page.goto(`/runs/${RUN}?t=${t}`);
    await page.getByTestId("scoreboard").waitFor();
    await page.getByTestId("tab-player").click();
    await page.getByTestId("player-card").waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `../docs/screens/${name}.png`, fullPage: true });
  }
});

test("review screenshots: the 3D pitch at 63'", async ({ page, request }) => {
  test.setTimeout(120_000);
  const events: { t: number; minute: number; outcome: string }[] = await (
    await request.get(`/api/runs/${RUN}/events`)
  ).json();
  const red = events.find((e) => e.outcome === "red_card")!.t;
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(() => localStorage.setItem("second-ball.profile.v1", JSON.stringify({ view: "3d" })));
  await page.goto(`/runs/${RUN}?t=${red}`);
  await page.getByTestId("pitch-3d").and(page.locator("[data-ready=yes]")).waitFor({ timeout: 60_000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "../docs/screens/3d-63.png" });
});

