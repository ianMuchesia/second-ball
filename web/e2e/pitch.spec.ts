import { expect, test, type Page } from "@playwright/test";

interface Ev {
  t: number;
  minute: number;
  second: number;
  period: number;
  type: string;
  outcome: string;
}

/** Overlaps between name tags and player dots (SVG units), measured in the page. */
async function collisions(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const box = (el: SVGGraphicsElement) => el.getBBox();
    const tags = [...document.querySelectorAll<SVGTextElement>("svg.pitch text.tag")];
    const dots = [...document.querySelectorAll<SVGCircleElement>("svg.pitch .player circle.dot")];
    const hit = (a: DOMRect, b: DOMRect) =>
      a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
    const out: string[] = [];
    tags.forEach((t, i) => {
      const a = box(t);
      dots.forEach((d) => hit(a, box(d)) && out.push(`${t.textContent} covers a player`));
      tags.slice(i + 1).forEach((u) => hit(a, box(u)) && out.push(`${t.textContent} overlaps ${u.textContent}`));
    });
    return out;
  });
}

test("names never cover a player or another name (36:05 and 9 more moments)", async ({ page, request }) => {
  const events: Ev[] = await (await request.get("/api/runs/e2e/events")).json();
  const at3605 = events.find((e) => e.minute === 36 && e.second >= 5)!.t;
  const end = events[events.length - 1].t;
  const times = [at3605, ...Array.from({ length: 9 }, (_, k) => Math.round((end * (k + 1)) / 10))];
  for (const t of times) {
    await page.goto(`/runs/e2e?t=${t}`);
    await expect(page.getByTestId("scoreboard")).toBeVisible();
    // Measure what a viewer sees: the broadcast font, not the fallback.
    await page.evaluate(() => document.fonts.ready);
    expect(await collisions(page), `at t=${t}`).toEqual([]);
  }
});

test("a goal's evidence is the move from Harbour's regain, and the regain shows the exposed full-back", async ({ page, request }) => {
  const events: Ev[] = await (await request.get("/api/runs/e2e/events")).json();
  const goal = events.find((e) => e.minute === 34 && e.type.startsWith("shot") && e.outcome === "success")!;
  await page.goto(`/runs/e2e?t=${goal.t + 10}`);
  await page.getByTestId("why").click();
  const drawer = page.getByTestId("evidence-drawer");
  await expect(drawer).toContainText("The move");
  const steps = drawer.getByTestId("evidence-events").locator("li");
  const n = await steps.count();
  expect(n).toBeGreaterThanOrEqual(3);
  expect(n).toBeLessThan(20);
  await expect(steps.first()).toContainText("regain");
  await expect(steps.first()).toContainText(/Harbour.*(intercepts|tackles)/);
  await expect(drawer.locator(".badge", { hasText: "regain" })).toHaveCount(1);
  await expect(steps.last()).toContainText("goal");
  // The numbers are summaries, collapsed: their windows are not in the move.
  await expect(drawer.getByTestId("evidence-numbers").locator("details[open]")).toHaveCount(0);
  await expect(drawer).toContainText("Kofi Lindqvane");
  await drawer.getByTestId("freeze-regain").click();
  await expect(page.getByTestId("player-riverside_athletic-3")).toHaveClass(/highlighted/);
  await expect(page.getByTestId("tag-riverside_athletic-3")).toHaveText("LINDQVANE");
});

test("opening evidence moves the whole replay to the regain, then plays the move", async ({ page, request }) => {
  const events: (Ev & { event_id: string; player_id: string; end: number[]; freeze_frame: { player_id: string; xy: number[] }[] })[] =
    await (await request.get("/api/runs/e2e/events")).json();
  const run = await (await request.get("/api/runs/e2e")).json();
  const goal = run.moments.find((m: { kind: string; clock: { minute: number } }) => m.kind === "goal" && m.clock.minute === 34);
  const [first, last] = [goal.move.ids[0], goal.move.ids[goal.move.ids.length - 1]].map(
    (id: string) => events.find((e) => e.event_id === id)!,
  );
  const mmss = (e: Ev) => `${String(e.minute).padStart(2, "0")}:${String(e.second).padStart(2, "0")}`;
  // Time stands still until the test moves it, so the first frame can be checked.
  const t0 = new Date("2026-11-07T15:00:00Z");
  await page.clock.install({ time: t0 });
  await page.goto(`/runs/e2e?t=${first.t + 120}`); // two minutes later, like 36:05
  await expect(page.getByTestId("feed")).toBeVisible();
  await page.clock.pauseAt((await page.evaluate(() => Date.now())) + 100);
  // From the Key moments feed, as a viewer would at 36'.
  await page.getByTestId("feed").locator("li", { hasText: "34'" }).first().locator("button").click();
  await expect(page.getByTestId("evidence-drawer")).toContainText("Evidence: goal (34')");

  // Clock, ball and every player are the regain's instant.
  await expect(page.getByTestId("clock")).toHaveText(mmss(first));
  const ball = page.locator("svg.pitch circle.ball");
  expect(Number(await ball.getAttribute("cx"))).toBeCloseTo(first.end[0], 1);
  for (const p of first.freeze_frame) {
    const dot = page.getByTestId(`player-${p.player_id}`).locator("circle.dot");
    expect(Number(await dot.getAttribute("cx")), p.player_id).toBeCloseTo(p.xy[0], 1);
    expect(Number(await dot.getAttribute("cy")), p.player_id).toBeCloseTo(68 - p.xy[1], 1);
  }
  // Only the move's players are named.
  const named = await page.locator("svg.pitch text.tag").count();
  expect(named).toBeLessThanOrEqual(goal.move.players.length + 1);

  // It plays the move at 1x and stops at its last action.
  await page.clock.runFor((last.t - first.t + 5) * 1000);
  await expect(page.getByTestId("clock")).toHaveText(mmss(last));
  await expect(page.getByTestId("play")).toHaveText("Play");
});

test("latency is honest: placeholders never show a fake AI time", async ({ page }) => {
  await page.goto("/runs/e2e?t=2100");
  const latency = page.getByTestId("latency");
  await expect(latency).toBeVisible();
  // The test bundle is the fake model: real verified lines, real (tiny) times.
  await expect(latency).toContainText(/AI latency \d+\.\d s · (within 8 s|missed 8 s target)|template/);
});
