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
  const shots: [string, number, boolean][] = [
    ["02", at(2), false],
    ["34", at(34, goal) + 20, false],
    ["63", at(63, (e) => e.outcome === "red_card"), true],
    ["88", at(88, goal) + 20, false],
  ];
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const [name, t, evidence] of shots) {
    await page.goto(`/runs/${RUN}?t=${t}`);
    await page.getByTestId("scoreboard").waitFor();
    if (evidence) {
      await page.locator('[data-testid^="marker-red_card-"]').first().click();
      await page.getByTestId("evidence-open").click();
    }
    await page.waitForTimeout(400);
    await page.screenshot({ path: `../docs/screens/${name}.png` });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/runs/${RUN}?t=${at(34, goal) + 20}`);
  await page.getByTestId("scoreboard").waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({ path: "../docs/screens/34-phone.png", fullPage: true });
});
