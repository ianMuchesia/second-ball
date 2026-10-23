// The 3D match. It owns the playback clock and the animation frame; React only
// hears about the clock ~10 times a second (onTick), so the HUD never slows the
// picture down. Each frame: the engine's path for every player at this instant
// (a curve through the freeze frames), then each footballer steers along it.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { GLTF } from "three/examples/jsm/loaders/GLTFLoader.js";
import { ballAt, type BallState, DRIBBLES, indexAt, isGoal, SHOTS, teamCode, teamName, type Timeline } from "../match";
import { Footballer, loadRig } from "./Footballer";
import { GK_KITS, matchKits, REF_KIT } from "./kits";
import { Stadium, wx, wz } from "./stadium";
import { ballTexture } from "./textures";

export type CameraMode = "broadcast" | "tactical" | "behind" | "free";

const BALL_R = 0.16; // a little over life size (0.11) so it reads from the gantry

export interface Tick {
  t: number;
  index: number;
  playing: boolean;
  holder: string | null;
  goalAt: number | null; // index of a goal being celebrated
}

export class Stage {
  t = 0;
  playing = false;
  speed = 4;
  mode: CameraMode = "broadcast";
  onTick: ((s: Tick) => void) | null = null;
  kits: ReturnType<typeof matchKits>;

  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(40, 16 / 9, 0.5, 700);
  private controls: OrbitControls;
  private stadium: Stadium;
  private players: Footballer[] = [];
  private referee: Footballer;
  private ball: THREE.Mesh;
  private ballShadow: THREE.Mesh;
  private b: BallState = { x: 52.5, y: 34, h: 0, holder: null, kicker: null, kick: 0, flight: 0, inNet: false };
  private camPos = new THREE.Vector3(0, 20, 50);
  private camLook = new THREE.Vector3();
  private wantPos = new THREE.Vector3();
  private wantLook = new THREE.Vector3();
  private v3 = new THREE.Vector3();
  private raf = 0;
  private last = 0;
  private lastTick = 0;
  private lastBall = new THREE.Vector3();
  private cheerUntil = 0;
  private celebrating: number | null = null;
  private resize: ResizeObserver;
  private gone = false;
  private snapNext = true;
  private lastIndex = -1;
  private ballOff = new THREE.Vector2();
  private feet = new THREE.Vector2();

  static async create(canvas: HTMLCanvasElement, tl: Timeline): Promise<Stage> {
    return new Stage(canvas, tl, await loadRig());
  }

  private constructor(private canvas: HTMLCanvasElement, private tl: Timeline, rig: GLTF) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.12;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.kits = matchKits(tl.home, tl.away);
    const sky = new THREE.Color("#0c1524");
    this.scene.background = sky;
    this.scene.fog = new THREE.Fog(sky, 170, 460);

    // Floodlit evening: a strong sky fill (turf reads green, not black), one
    // warm key light with shadows, and a cool rim from the far side.
    this.scene.add(new THREE.HemisphereLight("#d6e4ff", "#2c4a22", 1.15));
    const key = new THREE.DirectionalLight("#fff4e2", 2.7);
    key.position.set(-40, 95, 60);
    key.castShadow = true;
    key.shadow.mapSize.set(4096, 4096);
    const sc = key.shadow.camera;
    sc.left = -72;
    sc.right = 72;
    sc.top = 52;
    sc.bottom = -52;
    sc.near = 20;
    sc.far = 260;
    key.shadow.bias = -0.0003;
    key.shadow.normalBias = 0.03;
    this.scene.add(key);
    const rim = new THREE.DirectionalLight("#cfe0ff", 0.9);
    rim.position.set(55, 60, -70);
    this.scene.add(rim);

    this.stadium = new Stadium(this.renderer, tl.meta.weather, this.kits.home, this.kits.away, { home: teamName(tl.home), away: teamName(tl.away) });
    this.scene.add(this.stadium.group);

    for (const p of tl.slots) {
      const home = p.team_id === tl.home;
      const kit = p.position === "GK" ? GK_KITS[home ? 0 : 1] : home ? this.kits.home : this.kits.away;
      const f = new Footballer(rig, p.player_id, kit);
      this.players.push(f);
      this.scene.add(f.root);
    }
    this.referee = new Footballer(rig, "referee", REF_KIT);
    this.scene.add(this.referee.root);

    this.ball = new THREE.Mesh(
      new THREE.SphereGeometry(BALL_R, 24, 16),
      new THREE.MeshStandardMaterial({ map: ballTexture(), roughness: 0.35 }),
    );
    this.ball.castShadow = true;
    this.scene.add(this.ball);
    // A soft contact shadow, so a lofted ball's height reads.
    this.ballShadow = new THREE.Mesh(
      new THREE.CircleGeometry(BALL_R * 1.5, 20),
      new THREE.MeshBasicMaterial({ color: "#000", transparent: true, opacity: 0.4, depthWrite: false }),
    );
    this.ballShadow.rotation.x = -Math.PI / 2;
    this.scene.add(this.ballShadow);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI / 2.1;
    this.controls.minDistance = 4;
    this.controls.maxDistance = 220;
    this.controls.enabled = false;

    this.resize = new ResizeObserver(() => this.fit());
    this.resize.observe(canvas.parentElement!);
    this.fit();
    this.frame(0, 1 / 60);
    this.camera.position.copy(this.camPos);
    this.raf = requestAnimationFrame(this.loop);
  }

  // ---- controls the HUD calls ------------------------------------------------

  play(on: boolean) {
    if (on && this.t >= this.tl.end - 0.01) this.seek(0);
    this.playing = on;
    this.lastTick = 0;
  }
  setSpeed(s: number) {
    this.speed = s;
  }
  seek(t: number) {
    this.t = Math.max(0, Math.min(this.tl.end, t));
    this.celebrating = null;
    this.snapNext = true;
    this.lastTick = 0;
  }
  setCamera(mode: CameraMode) {
    this.mode = mode;
    this.controls.enabled = mode === "free";
    if (mode === "free") {
      this.controls.target.copy(this.camLook);
      this.controls.update();
    }
  }
  /** Screen position (px) of a player's head, for the HUD. null when off screen. */
  headOnScreen(id: string): { x: number; y: number } | null {
    const k = this.tl.slotOf.get(id);
    if (k === undefined) return null;
    const p = this.players[k].top(this.v3).project(this.camera);
    if (p.z > 1) return null;
    return { x: ((p.x + 1) / 2) * this.canvas.clientWidth, y: ((1 - p.y) / 2) * this.canvas.clientHeight };
  }

  dispose() {
    this.gone = true;
    cancelAnimationFrame(this.raf);
    this.resize.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if ((o as THREE.SkinnedMesh).isSkinnedMesh) return; // shares the rig's buffers
      m.geometry?.dispose?.();
      const mats = Array.isArray(m.material) ? m.material : m.material ? [m.material] : [];
      for (const x of mats) {
        (x as THREE.MeshStandardMaterial).map?.dispose();
        x.dispose();
      }
    });
  }

  // ---- the frame ---------------------------------------------------------------

  private fit() {
    const el = this.canvas.parentElement!;
    const w = el.clientWidth;
    const h = el.clientHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / Math.max(1, h);
    this.camera.updateProjectionMatrix();
  }

  // ---- inspection (?debug): step the clock by hand and park the camera ---------
  private manual = false;
  debugStep(dtMatch: number) {
    this.manual = true;
    this.t = Math.min(this.tl.end, this.t + dtMatch);
    this.frame(dtMatch, Math.min(dtMatch, 1 / 30));
  }
  debugCamera(pos: [number, number, number] | null, look: [number, number, number] | "player", fov = 30) {
    this.mode = "free";
    this.controls.enabled = false;
    const target = look === "player" ? this.focusPlayer() : new THREE.Vector3(...look);
    this.camera.position.copy(pos ? new THREE.Vector3(...pos) : target.clone().add(new THREE.Vector3(6, 3, 8)));
    this.camera.lookAt(target);
    this.camera.fov = fov;
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(target);
    this.renderer.render(this.scene, this.camera);
  }
  private focusPlayer() {
    const k = this.b.holder ? this.tl.slotOf.get(this.b.holder) ?? 0 : 0;
    return new THREE.Vector3(this.players[k].x, 1, this.players[k].z);
  }

  private loop = (now: number) => {
    if (this.gone) return;
    if (this.manual) {
      this.raf = requestAnimationFrame(this.loop);
      return;
    }
    const dtReal = this.last ? Math.min(0.1, (now - this.last) / 1000) : 1 / 60;
    this.last = now;
    let dtMatch = 0;
    if (this.playing) {
      dtMatch = dtReal * this.speed;
      this.t += dtMatch;
      if (this.t >= this.tl.end) {
        this.t = this.tl.end;
        this.playing = false;
      }
    }
    this.frame(dtMatch, dtReal);
    this.raf = requestAnimationFrame(this.loop);
  };

  private frame(dtMatch: number, dtReal: number) {
    const snap = this.snapNext;
    this.snapNext = false;
    const { events } = this.tl;
    const t = this.t;
    const i = indexAt(events, t);
    const e = events[i];
    const n = events[Math.min(i + 1, events.length - 1)];
    const b = ballAt(this.tl, i, t, this.b);

    // The engine's path at t: a Catmull-Rom curve through the freeze frames around now.
    const p0 = events[Math.max(0, i - 1)].ff;
    const p1 = e.ff;
    const p2 = n.ff;
    const p3 = events[Math.min(events.length - 1, i + 2)].ff;
    const gap = Math.max(0.05, n.t - e.t);
    const u = Math.min(1, Math.max(0, (t - e.t) / gap));
    const u2 = u * u;
    const u3 = u2 * u;
    const cr = (a: number, b0: number, c: number, d: number) =>
      0.5 * (2 * b0 + (-a + c) * u + (2 * a - 5 * b0 + 4 * c - d) * u2 + (-a + 3 * b0 - 3 * c + d) * u3);
    const or = (v: number, w: number) => (Number.isNaN(v) ? w : v);

    // The passer stays on the ball until the strike; the receiver comes to meet it.
    const pullE = DRIBBLES.has(e.type) ? 0.95 : clamp01(1 - (t - e.t) / 0.4);
    const pullN = clamp01(1 - (n.t - t) / 0.9);

    let goal: number | null = null;
    if (isGoal(e) && t > e.t + b.flight && t < e.t + b.flight + 5) goal = i;

    for (let k = 0; k < this.players.length; k++) {
      const f = this.players[k];
      const id = this.tl.slots[k].player_id;
      let x = p1[2 * k];
      let y = p1[2 * k + 1];
      if (!Number.isNaN(x) && !Number.isNaN(p2[2 * k])) {
        x = cr(or(p0[2 * k], x), x, p2[2 * k], or(p3[2 * k], p2[2 * k]));
        y = cr(or(p0[2 * k + 1], y), y, p2[2 * k + 1], or(p3[2 * k + 1], p2[2 * k + 1]));
      }
      let pull = 0;
      if (id === e.player) pull = pullE;
      if (id === n.player && n !== e) pull = Math.max(pull, pullN);
      if (pull > 0 && !b.inNet && !Number.isNaN(x)) {
        // Stand just behind the ball, on the side the player is coming from.
        const dx = x - b.x;
        const dy = y - b.y;
        const d = Math.hypot(dx, dy) || 1;
        x += (b.x + (dx / d) * 0.5 - x) * pull;
        y += (b.y + (dy / d) * 0.5 - y) * pull;
      }
      // The strike: wind back in the 0.35 s before contact (kick 0..0.6, contact at
      // 0.6), then follow through for 0.25 s after it (0.6..1).
      let kick = -1;
      if (n !== e && id === n.player && STRIKES(n) && n.t - t < 0.35) kick = (1 - (n.t - t) / 0.35) * 0.6;
      if (id === e.player && STRIKES(e) && t - e.t < 0.25) kick = 0.6 + ((t - e.t) / 0.25) * 0.4;
      // A keeper dives for a save: down before the ball arrives, up again after.
      let dive = 0;
      if (n.type === "keeper_save" && id === n.player && n !== e) dive = clamp01(1 - (n.t - t) / 0.55);
      if (e.type === "keeper_save" && id === e.player) dive = Math.max(dive, clamp01(1 - (t - e.t) / 0.9));
      // The scorer celebrates while the ball sits in the net.
      const celebrate = goal !== null && id === e.player ? clamp01((t - e.t - b.flight) / 0.6) : 0;
      f.step(wx(x), wz(y), wx(b.x), wz(b.y), dtMatch, dtReal, kick, snap, dive, SHOTS.has(e.type) ? 1.35 : 1, celebrate);
      f.lit = id === b.holder;
    }

    // The referee: level with play, a little off it, towards the middle.
    const rx = b.x + (52.5 - b.x) * 0.25;
    const ry = b.y + (b.y > 34 ? -11 : 11);
    this.referee.step(wx(rx), wz(ry), wx(b.x), wz(b.y), dtMatch, dtReal, -1, snap);

    // The ball belongs to feet, not to the engine's line: glued to a dribbler,
    // leaving the passer's boot, and arriving at the receiver's.
    let bwx = wx(b.x);
    let bwz = wz(b.y);
    const us = t - e.t;
    const kE = this.tl.slotOf.get(e.player);
    const kN = this.tl.slotOf.get(n.player);
    if (i !== this.lastIndex || snap) {
      this.lastIndex = i;
      if (kE !== undefined) {
        this.players[kE].feet(this.feet);
        this.ballOff.set(this.feet.x - wx(e.sx), this.feet.y - wz(e.sy));
      } else this.ballOff.set(0, 0);
    }
    if (!b.inNet && kE !== undefined) {
      if (DRIBBLES.has(e.type)) {
        this.players[kE].feet(this.feet, 0.45 + 0.4 * Math.abs(Math.sin(us * 4.5)));
        bwx = this.feet.x;
        bwz = this.feet.y;
      } else if (us < b.flight) {
        const f = us / Math.max(0.01, b.flight);
        bwx += this.ballOff.x * (1 - f);
        bwz += this.ballOff.y * (1 - f);
      } else if (kN !== undefined && n !== e && !isGoal(e)) {
        const g = THREE.MathUtils.smoothstep((us - b.flight) / Math.max(0.05, gap - b.flight), 0, 1);
        this.players[kN].feet(this.feet);
        bwx += (this.feet.x - bwx) * g;
        bwz += (this.feet.y - bwz) * g;
      }
    }

    // Ball, with spin from how far it travelled.
    this.ball.position.set(bwx, BALL_R + b.h, bwz);
    const moved = this.v3.copy(this.ball.position).sub(this.lastBall);
    if (!snap && moved.lengthSq() < 100) {
      this.ball.rotation.x += moved.z / BALL_R;
      this.ball.rotation.z -= moved.x / BALL_R;
    }
    this.lastBall.copy(this.ball.position);
    this.ballShadow.position.set(this.ball.position.x, 0.025, this.ball.position.z);
    (this.ballShadow.material as THREE.MeshBasicMaterial).opacity = 0.4 / (1 + b.h * 0.4);

    // Goal: the crowd rises.
    if (goal !== null && this.celebrating !== goal) {
      this.celebrating = goal;
      this.cheerUntil = performance.now() + 4500;
    }
    if (goal === null) this.celebrating = null;
    const left = this.cheerUntil - performance.now();
    this.stadium.stands.update(performance.now() / 1000, left > 0 ? clamp01(left / 1500) : 0);
    this.stadium.update(dtReal);
    const sc = this.tl.score;
    this.stadium.stands.screen.show(teamCode(this.tl.home), teamCode(this.tl.away), sc[2 * i], sc[2 * i + 1], Math.floor(e.clock / 60) + 1, goal !== null ? "GOAL" : null);

    this.aim(e.team === this.tl.home ? 1 : -1, dtReal, snap);
    this.renderer.render(this.scene, this.camera);

    const now = performance.now();
    if (now - this.lastTick > 100) {
      this.lastTick = now;
      this.onTick?.({ t, index: i, playing: this.playing, holder: b.holder, goalAt: goal });
    }
  }

  /** The camera follows the ball with a little lag, like an operator would. */
  private aim(dir: number, dtReal: number, snap: boolean) {
    const bx = this.ball.position.x;
    const bz = this.ball.position.z;
    let fov = 40;
    switch (this.mode) {
      case "broadcast":
        // High in the main stand, panning with play (SOKA-like framing).
        // High in the main stand, panning with play; the zoom keeps about
        // 46 m of pitch across the screen wherever the ball is (SOKA-like).
        this.wantPos.set(bx * 0.9, 15, 40);
        this.wantLook.set(bx * 0.97, 0, Math.max(-26, Math.min(24, bz)) * 0.8 - 1);
        {
          const d = this.camPos.distanceTo(this.camLook) || 40;
          const h = 2 * Math.atan(23 / d); // horizontal span 46 m
          fov = THREE.MathUtils.clamp(THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(h / 2) / this.camera.aspect)), 14, 50);
        }
        break;
      case "tactical":
        this.wantPos.set(bx * 0.45, 80, 42);
        this.wantLook.set(bx * 0.45, 0, -2);
        fov = 40;
        break;
      case "behind":
        this.wantPos.set(bx - dir * 24, 10, bz * 0.6);
        this.wantLook.set(bx + dir * 18, 0, bz * 0.8);
        fov = 54;
        break;
      case "free":
        this.controls.update();
        this.camLook.copy(this.controls.target);
        return;
    }
    const k = snap ? 1 : 1 - Math.exp(-dtReal * 2.4);
    this.camPos.lerp(this.wantPos, k);
    this.camLook.lerp(this.wantLook, k);
    this.camera.position.copy(this.camPos);
    this.camera.lookAt(this.camLook);
    if (Math.abs(this.camera.fov - fov) > 0.05) {
      this.camera.fov += (fov - this.camera.fov) * k;
      this.camera.updateProjectionMatrix();
    }
  }
}

const NO_STRIKE = new Set(["dribble", "take_on", "keeper_save", "foul", "interception", "tackle", "bad_touch", "throw_in"]);
const STRIKES = (e: { type: string }) => !NO_STRIKE.has(e.type);
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
