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

test("a goal's evidence is the whole move, and the regain shows the exposed full-back", async ({ page, request }) => {
  const events: Ev[] = await (await request.get("/api/runs/e2e/events")).json();
  const goal = events.find((e) => e.minute === 34 && e.type.startsWith("shot") && e.outcome === "success")!;
  await page.goto(`/runs/e2e?t=${goal.t + 10}`);
  await page.getByTestId("why").click();
  const drawer = page.getByTestId("evidence-drawer");
  await expect(drawer).toContainText("How it happened");
  const steps = drawer.getByTestId("evidence-events").locator("li");
  expect(await steps.count()).toBeGreaterThanOrEqual(3);
  await expect(steps.first()).toContainText("regain");
  await expect(steps.last()).toContainText("goal");
  await expect(drawer).toContainText("Kofi Lindqvane");
  await drawer.getByTestId("freeze-regain").click();
  await expect(page.getByTestId("player-riverside_athletic-3")).toHaveClass(/highlighted/);
  await expect(page.getByTestId("tag-riverside_athletic-3")).toHaveText("LINDQVANE");
});

test("latency is honest: placeholders never show a fake AI time", async ({ page }) => {
  await page.goto("/runs/e2e?t=2100");
  const latency = page.getByTestId("latency");
  await expect(latency).toBeVisible();
  // The test bundle is the fake model: real verified lines, real (tiny) times.
  await expect(latency).toContainText(/AI latency \d+\.\d s · (within 8 s|missed 8 s target)|template/);
});
