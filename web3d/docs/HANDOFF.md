# Second Ball 3D: handoff

How this 3D match viewer came about, what it does, what was decided and why, and what is still open. It is written so you, or a coding assistant on another machine, can pick the work up cold. The full build conversation (the user's messages and Claude's replies) is in [CONVERSATION.md](CONVERSATION.md).

## 1. What it is

It lives in `web3d/` on the `feat/web3d` branch of second-ball, next to the 2D screen in `web/`. A browser 3D broadcast of a match from the **Second Ball** engine ([github.com/ianMuchesia/second-ball](https://github.com/ianMuchesia/second-ball)). It is frontend only: no Kafka, no API, no agents. It loads the engine's `.jsonl` match file from `public/matches/` and plays it as a floodlit stadium with 22 animated players, a referee, a crowd, a score bug, a timeline, replays and stats.

- **The engine decides the football:** who passes, where, how fast, and where every player stands (one freeze frame of all 22 per event, about every 3 s).
- **The viewer fills in the motion** between those snapshots so players run instead of jumping. It invents no football.

## 2. Run it (Linux, macOS or Windows)

```sh
cd second-ball/web3d
npm ci            # Node 20+ (built with Node 22)
npm run matches   # generates the two demo matches with the engine (needs uv, run once)
npm run dev       # http://localhost:5173
npm run build     # typecheck + dist/
```

Match files are **generated, not committed**: second-ball's `.gitignore` says "never commit data" and ignores `*.jsonl`. `npm run matches` runs the engine from the repo root and writes them into `public/matches/`.

To add another match, from the repo root:

```sh
uv run python -m engine.generate --home riverside_athletic --away kilele_chui --seed 7 --weather dry > riverside-kilele.jsonl
```

Copy the file into `public/matches/` and add a line to `public/matches/index.json`. Weather is one of `dry | rain | wind | heat`.

**Inspection mode:** open `/?debug`. The browser console then has `window.stage`:
- `stage.seek(t)` jumps to match second `t`.
- `stage.debugStep(1/30)` steps one frame by hand.
- `stage.debugCamera([x,y,z], "player")` parks the camera on the player on the ball.

The Playwright checks used during the build stepped frames this way and took screenshots.

## 3. How we got here: the timeline

1. **Inspected SOKA** ([soka.david.ke](https://soka.david.ke/#/quick)), a Kenyan browser football game. It turned out to be plain **React + Three.js + Vite on Vercel**, frontend only. The only WebAssembly in it is the Draco and meshopt model decoders that come with three.js. The full report is in `docs/soka-inspection.md`.
2. **Reviewed second-ball's 2D screen** (`web/`). Players jumped between freeze frames with no smoothing, which is why 1x looked like play and 4x looked jumpy.
3. **The user wanted SOKA-style 3D in a separate project**, with second-ball's look, and **without editing the second-ball repo**. So this project borrows second-ball's UI (Msodoki night palette, Barlow Condensed, score bug, timeline, controls, crests) and reads the engine's files.
4. **First 3D version:** primitive block figures. Rejected: they looked nothing like SOKA, and players **slid** instead of running. The cause, measured from the data: the median player speed between frames is 1.3 m/s, and 34% of the time they're nearly still. The block figures barely animated at those speeds.
5. **Second version:**
   - Real rigged characters, with gaits advanced by **distance covered / stride length**, so feet don't slide at any playback speed.
   - A **steering layer** (top speed 9.2 m/s, acceleration 7.5 m/s²) so players chase the engine's path like people.
   - The **ball glued to the feet**: on the dribbler's boot, leaving the passer's, arriving at the receiver's.
   - A **kit shader** that colours the body by bind-pose height: shirt, pattern, sleeves, shorts, socks, boots, skin, hair.
6. **Third version (SOKA reference captured with Playwright):**
   - Two-tier stands with stairways, roofs with light strips, a home-end tifo and a big screen.
   - About 15,000 low-poly fans animated in the vertex shader (sway, wave, flags, leap on goals).
   - Stronger turf stripes, and a broadcast camera that keeps about 46 m of pitch in view.
   - A procedural kick, timed to contact, and a keeper dive.
   - Measured at about 50 fps on an Intel UHD 620.
7. **Licence fix:** the first character was three.js's Xbot (made with Mixamo; a grey area in a public repo). Mixamo itself would not load on the office network. It also looks to be in maintenance mode: no meaningful updates since 2015, and outages in 2025. It was replaced with the **Quaternius Universal Animation Library mannequin (CC0)**, trimmed to idle, walk, jog, sprint, dance, roll, sit and jump. Gaits now blend idle → walk → jog → sprint, and the scorer dances after a goal.

## 4. Where things live

| File | What it does |
|---|---|
| `src/match.ts` | Parses the `.jsonl` file and turns the away team's coordinates round (home attacks +x). Spreads same-second events across their second. Also: the ball model, the plain-word ticker, stats and key moments. |
| `src/three/Stage.ts` | Clock and render loop; Catmull-Rom paths through the freeze frames; ball on the feet; kick, dive and celebration timing; four cameras; the `?debug` hooks. |
| `src/three/Footballer.ts` | Rig, kit shader, steering, gait blending, kick, dive, dance. |
| `src/three/kits.ts` | Invented kits for the 13 fictional clubs; clash detection; goalkeeper and referee kits. |
| `src/three/stands.ts` | Stands, crowd (GPU-animated), flags, tifo, big screen, roofs, sky. |
| `src/three/stadium.ts`, `textures.ts` | Turf, goals, nets, boards, floodlights, rain; every texture is drawn in code. |
| `src/components/*`, `src/styles.css` | HUD taken from second-ball: score bug, controls, timeline, Match Centre, player card. |
| `docs/ASSETS.md` | Every asset with its source and licence. |

## 5. The advisor's four concerns

| # | Concern | Status |
|---|---|---|
| 1 | **Be honest about the motion.** Say on screen that motion between events is interpolated. At evidence moments, show the engine's *exact* positions, not the in-between guess. | On-screen note: **done**. Snapping to exact positions at evidence moments: **to do**. When paused, or at a clicked evidence event, set every player to `ff[i]` with no steering offset. |
| 2 | **Check asset licences**, in the app and the video. | **Done.** The character is CC0 (Quaternius); everything else is our own code or uses OFL or MIT licences. See `docs/ASSETS.md`. |
| 3 | **One repo for judges.** Move the viewer into `second-ball`, for example as `web3d/`. | **Done, on branch `feat/web3d`.** Merge it into `main` when ready. |
| 4 | **Keep 2D as the fallback** for weak laptops and phones. Load 3D on demand, with a 2D/3D toggle. | **To do.** This is easiest once it lives in second-ball next to `web/`. |

**Not now (post-submission ideas for the README):**
- **Live 3D streaming from the backend.** It needs an 8–10 s playout buffer, because the smooth path needs the next one or two events first.
- **The engine writing positions about 10 times a second** (tracking data) instead of one snapshot per event. That is a change in `engine/core/sim.py`.

**Integration gotcha:** second-ball's API (`stream/api/words.py → absolute()`) already flips away-team coordinates. If this viewer ever reads from the API instead of raw `.jsonl`, skip the flip in `src/match.ts`.

## 6. Known limits

- The free Quaternius set has **no football kick, header or keeper-dive animation**. Kicks and dives are procedural bone and body rotations, checked in close-up captures.
- The scorer's dance is wired up, but no capture has shown it clearly yet (the keeper stood in front of the scorer in the test shot).
- Not yet checked: the Free camera in depth, the rain match, and phone-size screens.
- No substitutes or dugouts (SOKA has them; the library's `Sitting_Idle_Loop` is already in the model for this).
- Better animation options for later:
  - **DeepMotion** (film yourself on a phone; it turns the video into a 3D animation).
  - **Meshy** (motion from a text prompt; paid tier for the good clips).
  - **Quaternius Universal Animation Library 2** (130+ clips).

## 7. Sources

- SOKA: https://soka.david.ke/
- Quaternius Universal Animation Library (CC0): https://quaternius.com/packs/universalanimationlibrary.html · https://opengameart.org/content/universal-animation-library
- Quaternius Universal Base Characters: https://quaternius.itch.io/universal-base-characters
- Mixamo status and alternatives: https://www.meshy.ai/blog/mixamo-alternative · https://charios.com/blog/mixamo-future-and-2d-game-dev · https://mocaponline.com/blogs/mocap-news/mixamo-alternatives · https://community.adobe.com/questions-696/mixamo-is-down-24-september-2025-589891
- Licence caveat for newer Quaternius releases: https://app.cinevva.com/guides/free-rigged-3d-character-models
