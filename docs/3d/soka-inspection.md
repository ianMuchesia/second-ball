# SOKA (soka.david.ke) — Technical Inspection

Inspected 2026-10-23. Everything here comes from the public HTML, JS bundles and JSON the site serves. Raw downloads are in `raw/`.

## TL;DR — WebAssembly or vanilla JS?

**It's JavaScript: a React + Three.js app built with Vite.** It isn't a WebAssembly game, and it isn't a Unity, Godot or Emscripten export.

The only WebAssembly is in **third-party asset decoders that come with Three.js**:

| WASM module | Purpose | How it ships |
|---|---|---|
| Draco decoder | Decompresses `.glb` mesh geometry | `/draco/gltf/draco_decoder.wasm` (192 KB) + JS wrapper |
| meshoptimizer decoder | Decompresses meshopt-compressed buffers/animations | WASM inlined as a byte array inside the main bundle, run in a Web Worker |

The game logic, match simulation, AI, career mode and UI are all hand-written JavaScript (very likely TypeScript before the build, because the SW comment mentions `vite.config.ts`).

## Stack

| Layer | What they use | Evidence |
|---|---|---|
| Build tool | **Vite** (+ a custom `soka-sw` Vite plugin that stamps the build id into the SW) | hashed `/assets/index-XXXX.js`, `modulepreload`, comment in `sw.js` |
| UI | **React** (own vendor chunk, 218 KB) | `assets/react-*.js` |
| 3D | **Three.js** (own vendor chunk, 599 KB), plain Three, **not** react-three-fiber | `assets/three-*.js`; no R3F/drei strings |
| Models | glTF/GLB via `GLTFLoader` + `DRACOLoader` + meshopt + KTX2 | `/models/street/ch_*.glb` |
| Animation | Custom binary `clips.bin` + `clips.json` index, Three `SkinnedMesh`/AnimationMixer | `$g()` loader fetches `clips.bin`, `clips.json` and `characters.json` together |
| Physics | **Custom** (no Rapier, Cannon, Ammo, Oimo or Matter found) | none of those strings appear in the bundles |
| State | **Custom** (no Redux, Zustand, Jotai or MobX) | none found |
| Routing | **Custom hash router** (no react-router) | routes `#/quick`, `#/new`, `#/squad`, `#/settings`, `#/trailer` |
| Persistence | `localStorage` + **IndexedDB** (career saves) | keys listed below |
| Offline | Hand-written **service worker** + PWA manifest | `/sw.js`, `/manifest.webmanifest` |
| Audio | Web Audio `AudioContext`, MP3 music, commentary packs | `/music/manifest.json`, `/commentary/index.json` |
| Hosting | **Vercel** (edge PoP `cpt1` = Cape Town) | `Server: Vercel`, `X-Vercel-Id` |
| Fonts | Google Fonts: Bebas Neue, Barlow, Barlow Condensed | `<link>` in `index.html` |
| Analytics/trackers | **None found** (no GA, Sentry, PostHog or Plausible) | |
| Backend | None used today. The SW does reserve `/api/` and `/socket.io/` as network-only, which suggests multiplayer is planned | `sw.js` fetch handler |
| Source maps | Not published (`.map` returns 404) | |

Author link in the bundle: `https://x.com/davidamunga_`

## Bundle layout (code splitting)

```
index.html (6 KB, inline boot spinner + SEO/OG/JSON-LD)
└─ assets/index-BMZChnEf.js   675 KB  ← game engine, sim, career, UI
   ├─ assets/react-*.js       219 KB  (modulepreload)
   ├─ assets/three-*.js       599 KB  (modulepreload)
   ├─ assets/index-*.css       89 KB
   └─ lazy import():
      ├─ QuickMatchScreen-*.js 14 KB  ← the /#/quick page
      ├─ MatchScreen-*.js       3 KB
      ├─ DrillScreen-*.js       2 KB
      └─ TrailerScreen-*.js     0.5 KB
```

The screen chunks are thin React wrappers. They import the engine classes from the main bundle, which construct the match with something like `new xd({canvas, state, setup, clubs, humanSide, versus, weather})`.

## The `/#/quick` (Quick Match) screen

UI strings show what's on it:
- Pick **Your side** and the **Opposition** (Previous/Next club, "New set of clubs")
- Club tiers: **Community / Regional / National**, with a Nairobi flavour (e.g. "Quick FC")
- **Kit designer**: shirt colour, pattern, pattern colour, shorts colour, socks colour
- **Weather**: `clear` / `rain`
- Start match → Play again

## Gameplay features found in the engine

Counts of feature terms in the main bundle show a deep sim:
seasons, divisions, leagues, cups, promotion and relegation, fixtures, formations (4-4-2, 4-3-3, 3-5-2), stamina, training and drills, injuries, youth, transfers and scouting, offside, penalties and shootouts, corners, free kicks, throw-ins, yellow and red cards, referee, replays, commentary, camera modes, difficulty, and **seeded RNG** (`seed` appears 42 times, which suggests deterministic matches).

## Input

- Keyboard: WASD / arrow keys to move, Space, Shift (sprint), plus Q, E, X, P, U, O, L (actions), Enter, Escape
- **Gamepad API** (`getGamepads`)
- Touch controls on mobile; the `<html data-input="keys">` attribute switches the UI between input modes
- `navigator.vibrate` for haptics

## Graphics quality tiers

```js
high: { pixelRatio: 1.5, shadows: true, shadowMapSize: 2048, crowdStride: 3, crowdDensity: 1,    detail: "high" }
low:  { pixelRatio: 1.5, shadows: true, shadowMapSize: 1024, crowdStride: 5, crowdDensity: 0.55, detail: "low"  }
```
It also stores `soka:graphics-lost`, which looks like WebGL context-loss detection that steps the quality down automatically. Player models are about 18–27k triangles and 250–420 KB each. There are 5 characters (lewis, david, brian, leonard, bryce), recoloured per player through `skin` and `tone` values.

If the models fail to load, the game logs "the player models did not load; drawing simple figures" and falls back to primitive figures.

## Animation clips (`clips.json`)

idle, idle_relaxed, walk, jog, jog_back, run, sprint, pass, pass_L, shoot, shoot_L, strike_jog(_L), … Each clip has a `contact` time, the frame where the foot meets the ball, which the engine uses to time kicks.

## Storage keys

`soka-career`, `soka-music`, `soka.intro.seen`, `soka:announcer`, `soka:commentary`, `soka:drills:v1`, `soka:graphics`, `soka:graphics-lost`, `soka:menu-tab`, `soka:music`, `soka:muted`, `soka:practice-section`, `soka:settings`, `soka:tournament`, plus one IndexedDB database (v1).

## Service worker strategy (worth copying)

The SW comment explains the reason: Kenyan mobile data costs about KES 40–70/MB, so the second launch should cost zero bytes.
- navigations → network-first, falling back to the cached shell (offline play)
- `/assets/*`, js, css → stale-while-revalidate
- `/models/*` → cache-first (content-hashed per build)
- `/sounds|music|commentary|intro/*` → cache-first, **with byte-range (206) responses served from the cached whole file**, so `<audio>` and `<video>` work offline
- `/api/*`, `/socket.io/*` → never cached
- `PURGE` / `SKIP_WAITING` messages drop old caches when a new build ships

The comment also says "the reference game does not" ship a SW, so SOKA is modelled on some existing reference game.

## SEO / PWA

Full OG and Twitter cards, JSON-LD `VideoGame` schema, `<noscript>` fallback text, sitemap and robots, installable PWA with shortcuts "Kick off" (`/#/quick`) and "New career" (`/#/new`), plus a maskable icon.

## Takeaways for "soccer ideas"

1. **No WASM or game engine is needed** to get a 3D football game that runs in the browser. React for menus plus plain Three.js for the pitch is enough, and it keeps the download small (~1.5 MB JS before models).
2. Keep the **sim in plain TS with a seeded RNG**. That gives deterministic matches, replays and possibly multiplayer later.
3. **Draco/meshopt-compressed GLB** with a handful of base characters, recoloured per player, keeps assets tiny.
4. Pack animation clips into a **binary blob plus a JSON index that records contact frames**.
5. An **offline-first service worker** matters a lot in markets where data is expensive.
6. Use **graphics tiers with context-loss fallback** for low-end Android.
