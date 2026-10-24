import { expect, type Page, test } from "@playwright/test";

// The 3D pitch (Ian's viewer, integrated): it reads the API's events, which
// are already in the broadcast frame, so it must not flip them again; paused,
// every player and the ball sit exactly where the engine put them.

interface Ev {
  event_id: string;
  t: number;
  minute: number;
  period: number;
  team_id: string;
  end: [number, number];
  freeze_frame: { player_id: string; team_id: string; xy: [number, number] }[];
}

// One WebGL page at a time: software rendering is slow to draw a first frame.
test.describe.configure({ mode: "serial" });

const PROFILE = "second-ball.profile.v1";
const as3d = (page: Page) =>
  page.addInitScript((key) => localStorage.setItem(key, JSON.stringify({ view: "3d" })), PROFILE);

/** The event the 2D pitch shows at t: the last at or before it. */
function shownAt(events: Ev[], t: number): Ev {
  let i = 0;
  while (i + 1 < events.length && events[i + 1].t <= t) i++;
  return events[i];
}

test("2D is the default; 3D loads only when asked", async ({ page }) => {
  const chunks: string[] = [];
  page.on("request", (r) => chunks.push(r.url()));
  await page.goto("/runs/e2e?t=600");
  await expect(page.locator("svg.pitch")).toBeVisible();
  await expect(page.getByTestId("pitch-3d")).toHaveCount(0);
  expect(chunks.some((u) => u.includes("Pitch3D") || u.includes("mannequin"))).toBe(false);
  await page.getByTestId("view").selectOption("3d");
  await expect(page.getByTestId("pitch-3d")).toHaveAttribute("data-ready", "yes", { timeout: 60_000 });
  expect(chunks.some((u) => u.includes("Pitch3D"))).toBe(true);
  await expect(page.getByTestId("interpolated-note")).toHaveText(
    "Motion between events is interpolated; positions at events come from the engine.",
  );
  await page.getByTestId("view").selectOption("2d");
  await expect(page.locator("svg.pitch")).toBeVisible();
});

for (const minute of [10, 50, 63]) {
  test(`3D at ${minute}': both teams where the engine (and the 2D pitch) put them, no second flip`, async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000);
    const events: Ev[] = await (await request.get("/api/runs/e2e/events")).json();
    const t = events.find((e) => e.minute === minute)!.t;
    const shown = shownAt(events, t);
    await as3d(page);
    await page.goto(`/runs/e2e?t=${t}`);
    await expect(page.getByTestId("pitch-3d")).toHaveAttribute("data-ready", "yes", { timeout: 60_000 });
    const placed = async () =>
      page.evaluate(() => {
        const s = (window as unknown as { stage3d: { positions(): { player_id: string; x: number; y: number }[]; ballAt(): { x: number; y: number } } }).stage3d;
        return { players: s.positions(), ball: s.ballAt() };
      });
    // Paused: exact engine positions for every player on the pitch.
    await expect
      .poll(async () => {
        const { players } = await placed();
        const at = new Map(players.map((p) => [p.player_id, p]));
        return shown.freeze_frame.filter((f) => {
          const p = at.get(f.player_id);
          return !p || Math.abs(p.x - f.xy[0]) > 0.05 || Math.abs(p.y - f.xy[1]) > 0.05;
        }).length;
      }, { timeout: 30_000 })
      .toBe(0);
    const { ball, players } = await placed();
    expect(ball.x).toBeCloseTo(shown.end[0], 1);
    expect(ball.y).toBeCloseTo(shown.end[1], 1);
    // Home attacks left to right in both halves (the API's frame): keepers.
    const run = await (await request.get("/api/runs/e2e")).json();
    const keeper = (team: string) =>
      run.match.lineups.find((p: { team_id: string; position: string }) => p.team_id === team && p.position === "GK")
        .player_id;
    const x = (id: string) => players.find((p) => p.player_id === id)?.x;
    expect(x(keeper(run.match.home_team))).toBeLessThan(35);
    expect(x(keeper(run.match.away_team))).toBeGreaterThan(70);
  });
}

test("on a phone the pitch stays 2D, even if 3D was chosen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await as3d(page);
  await page.goto("/runs/e2e?t=600");
  await expect(page.locator("svg.pitch")).toBeVisible();
  await expect(page.getByTestId("pitch-3d")).toHaveCount(0);
  const view = page.getByTestId("view");
  await expect(view).toHaveValue("2d");
  await expect(view.locator("option[value='3d']")).toHaveAttribute("disabled", "");
  await expect(view.locator("option[value='3d']")).toContainText("needs a larger screen");
});
