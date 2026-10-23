import { expect, test } from "@playwright/test";

interface Ev {
  t: number;
  minute: number;
  second: number;
  team_id: string;
  type: string;
  outcome: string;
  end: [number, number];
}

const SHOTS = new Set(["shot", "shot_penalty", "shot_freekick"]);
const CODES: Record<string, string> = { riverside_athletic: "RIV", harbour_town: "HAR" };
const code = (id: string) => CODES[id] ?? id.slice(0, 3).toUpperCase();
const mmss = (m: number, s: number) => `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;

test("score, clock, ball, possession and the line on air agree at 10 moments", async ({ page, request }) => {
  const events: Ev[] = await (await request.get("/api/runs/e2e/events")).json();
  const run = await (await request.get("/api/runs/e2e")).json();
  const [home, away]: string[] = [run.match.home_team, run.match.away_team];
  const end = events[events.length - 1].t;
  for (let k = 1; k <= 10; k++) {
    const t = Math.round((end * k) / 11);
    let i = 0;
    while (i + 1 < events.length && events[i + 1].t <= t) i++;
    const e = events[i];
    const goals: Record<string, number> = { [home]: 0, [away]: 0 };
    for (const x of events.slice(0, i + 1)) {
      if (SHOTS.has(x.type) && x.outcome === "success") goals[x.team_id]++;
      if (x.outcome === "owngoal") goals[x.team_id === home ? away : home]++;
    }
    await page.goto(`/runs/e2e?t=${t}`);
    await expect(page.getByTestId("clock")).toHaveText(mmss(e.minute, e.second));
    await expect(page.getByTestId("score")).toHaveText(`${goals[home]}–${goals[away]}`);
    // The fouling team is not the one on the ball.
    const holder = e.type === "foul" ? (e.team_id === home ? away : home) : e.team_id;
    await expect(page.getByTestId("possession")).toContainText(code(holder));
    const ball = page.locator("svg.pitch circle.ball");
    expect(Number(await ball.getAttribute("cx"))).toBeCloseTo(e.end[0], 1);
    expect(Number(await ball.getAttribute("cy"))).toBeCloseTo(68 - e.end[1], 1);
    // A line on air is never from the future.
    const card = page.getByTestId("lower-third");
    if (await card.count()) {
      const strip = await card.locator(".strip").innerText();
      const minute = Number(strip.match(/(\d+)'/)?.[1]);
      expect(minute).toBeLessThanOrEqual(e.minute);
    }
  }
});

test("a line never airs before the data it describes: the red card's impact", async ({ page, request }) => {
  const run = await (await request.get("/api/runs/e2e")).json();
  const red = run.overlays.find(
    (o: { kind: string; slot: string; status: string }) =>
      o.kind === "red_card_impact" && o.slot === "narrative" && o.status === "aired",
  );
  const card = run.moments.find((m: { kind: string }) => m.kind === "red_card_impact");
  // The impact compares the 10 minutes after the card: it airs after them.
  expect(red.t).toBeGreaterThan(card.t + 9 * 60);
  await page.goto(`/runs/e2e?t=${card.t + 5}`);
  await expect(page.getByTestId("scoreboard")).toBeVisible();
  await expect(page.getByText(red.text.en)).toHaveCount(0);
});
