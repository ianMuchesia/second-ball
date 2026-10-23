# Second Ball 3D

A 3D match viewer for the Second Ball engine. It's frontend only: no Kafka, no API, no agents. It reads the engine's match files (`.jsonl`) straight from `public/matches/` and plays them in a floodlit 3D stadium. The UI follows Second Ball's broadcast style: the Msodoki night palette, score bug, timeline, controls and crests.

```sh
npm ci
npm run matches    # generate the demo matches with the engine (needs uv), once
npm run dev        # http://localhost:5173
npm run build      # typecheck + production build in dist/
```

## Adding a match

From the `second-ball` repo:

```sh
uv run python -m engine.generate --home ashgrove --away ironvale --seed 1 --weather rain > match.jsonl
```

Write it into `web3d/public/matches/` and add a line to `public/matches/index.json`. Match files are generated, never committed (the repo ignores `*.jsonl`). The handoff with every decision is in [docs/HANDOFF.md](docs/HANDOFF.md); the full build conversation is in [docs/CONVERSATION.md](docs/CONVERSATION.md). To open a specific match, use `?match=<file>.jsonl`.

## How it works

| File | What it does |
|---|---|
| `src/match.ts` | Parses the `.jsonl` file. Turns the away team's coordinates round so home attacks +x on one pitch. Spreads same-second events across their second. Also holds the ball model (flight time from distance and `ball_speed_kmh`; arcs for crosses, corners and long balls), the plain-word ticker, stats and key moments. |
| `src/three/Stage.ts` | Owns the clock and the animation frame; React only hears from it about 10 times a second. Each frame it works out every player's path at that instant (a Catmull-Rom curve through the freeze frames). It also keeps the ball on the feet: glued to a dribbler, leaving the passer's boot, arriving at the receiver's. Four cameras, plus a `?debug` hook to step the clock frame by frame. |
| `src/three/Footballer.ts` | A rigged character with idle, walk, jog and sprint cycles (and a dance for the scorer), dressed by a kit shader (shirt pattern, sleeves, shorts, socks, boots, skin, hair). A steering layer caps speed at 9.2 m/s and acceleration at 7.5 m/s². Each walk or run cycle advances by the distance covered divided by the stride length, so feet do not slide at any speed. |
| `src/three/kits.ts` | Invented colours for the 13 fictional clubs, with a change kit when the shirts clash. Goalkeeper and referee kits. |
| `src/three/stadium.ts` | Turf, goals with nets, corner flags, LED boards, floodlight towers, and rain when the match weather is rain. |
| `src/three/stands.ts` | Two-tier stands with stairways, fascia banners, roofs with light strips, a tifo at the home end, and a big screen over the away end. About 15,000 low-poly fans who sway, wave, hold flags and leap up for goals. All of their motion runs in the vertex shader. |
| `src/three/textures.ts` | Every texture is drawn on a canvas at start-up. No image assets. |

Controls: Space play/pause · ← → 10 s · 1–4 cameras (Broadcast, Tactical, Behind, Free) · speed 1x/2x/4x/10x · "Replay" on a key moment goes back 9 s and plays it at 1x.

Model: `public/models/mannequin.glb` is the mannequin and animations from Quaternius's Universal Animation Library (CC0), trimmed to the clips the viewer uses. Every asset and its licence is listed in [docs/ASSETS.md](docs/ASSETS.md).

Honesty: every position comes from the engine's freeze frames, and the motion between them is interpolated. Ticker lines are code templates over the events. No model writes them.
