// The stands: two tiers of terraces with stairways, a fascia banner, a roof
// with a light strip, and a crowd of low-poly people who sway, wave, wave
// flags and leap up for goals. All crowd motion runs in the vertex shader (one
// uniform per frame), so 15,000 fans cost the CPU nothing.
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { Kit } from "./kits";
import { glowTexture } from "./textures";

const NEUTRAL = ["#ede8df", "#2c2a26", "#a39d92", "#3d5a80", "#d9d4c7", "#22201d", "#f4f4ef", "#8c2f39"];
const SKIN = ["#3b2219", "#4a2c1e", "#5a3825", "#7a4e33", "#8d5f3f", "#b07c55", "#d8ad86"];

const DEPTH = 0.8; // row depth (m)
const RISE = 0.45; // lower tier rise per row
const RISE_UP = 0.6; // upper tier is steeper
const AISLE_EVERY = 13;
const AISLE_W = 1.2;
const SEAT = 0.58;

export interface StandSpec {
  len: number;
  at: number; // distance from the centre spot to the stand's front
  rotation: number; // about Y: local +Z (away from the pitch) -> world
  lower: number; // rows
  upper: number; // rows (0: no upper tier)
  roof: boolean;
  fans: "home" | "away";
  tifo?: string; // text on a giant flag over the lower rows
  screen?: boolean;
  banner: string;
}

/** One person: torso, arms (part 1 left, 2 right), head (part 3). Faces -Z (the pitch). */
function personGeometry(): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  const tag = (g: THREE.BufferGeometry, part: number) => {
    const n = g.getAttribute("position").count;
    g.setAttribute("aPart", new THREE.BufferAttribute(new Float32Array(n).fill(part), 1));
    g.deleteAttribute("uv");
    return g;
  };
  parts.push(tag(new THREE.BoxGeometry(0.42, 0.55, 0.26).translate(0, 0.3, 0), 0));
  parts.push(tag(new THREE.BoxGeometry(0.1, 0.46, 0.1).translate(-0.27, 0.33, 0), 1));
  parts.push(tag(new THREE.BoxGeometry(0.1, 0.46, 0.1).translate(0.27, 0.33, 0), 2));
  parts.push(tag(new THREE.IcosahedronGeometry(0.13, 0).translate(0, 0.73, 0), 3));
  return mergeGeometries(parts.map((g) => (g.index ? g.toNonIndexed() : g)))!;
}

/** Crowd material: instance colour is the shirt; aSkin the head; arms and
 * bodies move by aPhase/aMood and the shared uTime/uCheer. */
function crowdMaterial(uniforms: { uTime: { value: number }; uCheer: { value: number } }) {
  const m = new THREE.MeshStandardMaterial({ roughness: 0.85, color: "#ffffff" });
  m.onBeforeCompile = (s) => {
    Object.assign(s.uniforms, uniforms);
    s.vertexShader =
      `attribute float aPart; attribute float aPhase; attribute float aMood; attribute vec3 aSkin;
uniform float uTime; uniform float uCheer;
varying float vPart; varying vec3 vSkin;
float armAngle() {
  float t = uTime + aPhase * 6.2831;
  float a = 0.18 + 0.05 * sin(t * 1.3);                                  // sitting, arms down
  if (aMood > 0.5 && aMood < 1.5) a = 1.6 + 0.9 * sin(t * 4.0);           // waving
  if (aMood > 1.5) a = 2.6 + 0.15 * sin(t * 2.0);                         // arms up / scarf
  float leap = smoothstep(0.15, 1.0, uCheer) * step(0.2, fract(aPhase * 7.3));
  return mix(a, 2.75 + 0.25 * sin(t * 9.0), leap);
}
vec3 armRotate(vec3 p, float side) {
  vec2 pivot = vec2(side * 0.27, 0.55);
  vec2 q = p.xy - pivot;
  float a = side * armAngle();
  float c = cos(a), s = sin(a);
  return vec3(vec2(q.x * c - q.y * s, q.x * s + q.y * c) + pivot, p.z);
}
` + s.vertexShader
        .replace(
          "#include <beginnormal_vertex>",
          `#include <beginnormal_vertex>
if (aPart > 0.5 && aPart < 2.5) { float sd = aPart < 1.5 ? -1.0 : 1.0; float a = sd * armAngle(); objectNormal.xy = mat2(cos(a), sin(a), -sin(a), cos(a)) * objectNormal.xy; }`,
        )
        .replace(
          "#include <begin_vertex>",
          `#include <begin_vertex>
vPart = aPart; vSkin = aSkin;
if (aPart > 0.5 && aPart < 2.5) transformed = armRotate(transformed, aPart < 1.5 ? -1.0 : 1.0);
float tt = uTime + aPhase * 6.2831;
transformed.y += 0.02 * sin(tt * 2.1) + uCheer * abs(sin(tt * 8.5)) * 0.38 * step(0.2, fract(aPhase * 7.3));`,
        );
    s.fragmentShader =
      "varying float vPart; varying vec3 vSkin;\n" +
      s.fragmentShader.replace("#include <color_fragment>", "#include <color_fragment>\nif (vPart > 2.5) diffuseColor.rgb = vSkin;");
  };
  m.customProgramCacheKey = () => "crowd-v1";
  return m;
}

/** Flags on poles, waving: the cloth ripples in the vertex shader. */
function flagMaterial(uniforms: { uTime: { value: number } }) {
  const m = new THREE.MeshStandardMaterial({ roughness: 0.8, side: THREE.DoubleSide, color: "#ffffff" });
  m.onBeforeCompile = (s) => {
    Object.assign(s.uniforms, uniforms);
    s.vertexShader =
      "attribute float aPhase; uniform float uTime;\n" +
      s.vertexShader.replace(
        "#include <begin_vertex>",
        `#include <begin_vertex>
float k = clamp(position.x / 1.3, 0.0, 1.0);
transformed.z += sin(position.x * 4.0 - uTime * 6.0 + aPhase * 6.28) * 0.16 * k;
transformed.y += sin(position.x * 3.0 - uTime * 5.0 + aPhase * 3.1) * 0.05 * k;`,
      );
  };
  m.customProgramCacheKey = () => "flag-v1";
  return m;
}

function bannerTexture(text: string, kit: Kit): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 2048;
  c.height = 128;
  const g = c.getContext("2d")!;
  g.fillStyle = kit.trim;
  g.fillRect(0, 0, 2048, 128);
  g.fillStyle = kit.shirt;
  g.fillRect(0, 0, 2048, 10);
  g.fillRect(0, 118, 2048, 10);
  g.font = '800 78px "Barlow Condensed", "Arial Narrow", sans-serif';
  g.textBaseline = "middle";
  g.fillStyle = kit.shirt;
  let x = 30;
  while (x < 2048) {
    g.fillText(text, x, 68);
    x += g.measureText(text).width + 90;
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = THREE.RepeatWrapping;
  return t;
}

function tifoTexture(text: string, kit: Kit): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 1024;
  c.height = 400;
  const g = c.getContext("2d")!;
  const bands = 8;
  for (let i = 0; i < bands; i++) {
    g.fillStyle = i % 2 ? kit.trim : kit.shirt;
    g.fillRect((i * 1024) / bands, 0, 1024 / bands + 1, 400);
  }
  g.fillStyle = "rgba(0,0,0,0.25)";
  g.fillRect(0, 130, 1024, 140);
  // Fit the name across the flag, whatever its length.
  let size = 150;
  do g.font = `800 ${size}px "Barlow Condensed", "Arial Narrow", sans-serif`;
  while (g.measureText(text).width > 940 && (size -= 6) > 40);
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.lineWidth = 10;
  g.strokeStyle = kit.trim;
  g.strokeText(text, 512, 206);
  g.fillStyle = kit.shirt;
  g.fillText(text, 512, 206);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** The big screen: redrawn when the score or the minute changes. */
export class BigScreen {
  mesh: THREE.Mesh;
  private c = document.createElement("canvas");
  private tex: THREE.CanvasTexture;
  private last = "";
  constructor(private homeKit: Kit, private awayKit: Kit) {
    this.c.width = 1024;
    this.c.height = 420;
    this.tex = new THREE.CanvasTexture(this.c);
    this.tex.colorSpace = THREE.SRGBColorSpace;
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(17, 7), new THREE.MeshBasicMaterial({ map: this.tex, toneMapped: false }));
  }
  show(home: string, away: string, hs: number, as: number, minute: number, flash: string | null) {
    const key = `${home}${hs}${as}${minute}${flash}`;
    if (key === this.last) return;
    this.last = key;
    const g = this.c.getContext("2d")!;
    g.fillStyle = "#0a0a0c";
    g.fillRect(0, 0, 1024, 420);
    g.fillStyle = "#e08a3c";
    g.fillRect(0, 0, 1024, 14);
    g.textAlign = "center";
    g.textBaseline = "middle";
    if (flash) {
      g.font = '800 230px "Barlow Condensed", "Arial Narrow", sans-serif';
      g.fillStyle = "#e08a3c";
      g.fillText(flash, 512, 225);
    } else {
      g.font = '800 120px "Barlow Condensed", "Arial Narrow", sans-serif';
      g.fillStyle = this.homeKit.shirt;
      g.fillRect(60, 120, 22, 150);
      g.fillStyle = this.awayKit.shirt;
      g.fillRect(942, 120, 22, 150);
      g.fillStyle = "#ede8df";
      g.fillText(home, 230, 195);
      g.fillText(away, 794, 195);
      g.font = '800 170px "Barlow Condensed", "Arial Narrow", sans-serif';
      g.fillText(`${hs} - ${as}`, 512, 190);
      g.font = '700 64px "Barlow Condensed", "Arial Narrow", sans-serif';
      g.fillStyle = "#e08a3c";
      g.fillText(`${minute}'`, 512, 345);
    }
    this.tex.needsUpdate = true;
  }
}

export class Stands {
  group = new THREE.Group();
  screen: BigScreen;
  private u = { uTime: { value: 0 }, uCheer: { value: 0 } };

  constructor(specs: StandSpec[], private home: Kit, private away: Kit) {
    this.screen = new BigScreen(home, away);
    const person = personGeometry();
    const crowdMat = crowdMaterial(this.u);
    const flagMat = flagMaterial(this.u);
    for (const s of specs) this.group.add(this.stand(s, person, crowdMat, flagMat));
    this.group.add(this.sky());
  }

  /** time: seconds; cheer: 0..1 (a goal). */
  update(time: number, cheer: number) {
    this.u.uTime.value = time;
    this.u.uCheer.value = cheer;
  }

  private stand(s: StandSpec, person: THREE.BufferGeometry, crowdMat: THREE.Material, flagMat: THREE.Material) {
    const g = new THREE.Group();
    g.rotation.y = s.rotation;
    g.position.set(Math.sin(s.rotation) * s.at, 0, Math.cos(s.rotation) * s.at);
    const kit = s.fans === "home" ? this.home : this.away;
    const other = s.fans === "home" ? this.away : this.home;

    const seatMats = [kit.shirt, kit.trim].map((c) => new THREE.MeshStandardMaterial({ color: new THREE.Color(c).multiplyScalar(0.5), roughness: 0.8 }));
    const concrete = new THREE.MeshStandardMaterial({ color: "#3a3833", roughness: 0.95 });
    const dark = new THREE.MeshStandardMaterial({ color: "#1b1a18", roughness: 0.9 });

    // Row r of a tier: front z, step top y.
    const rows: { z: number; y: number; upper: boolean }[] = [];
    for (let r = 0; r < s.lower; r++) rows.push({ z: 1.5 + r * DEPTH, y: 0.6 + (r + 1) * RISE, upper: false });
    const lowerBack = 1.5 + s.lower * DEPTH;
    const upperBase = 0.6 + s.lower * RISE + 3.4;
    for (let r = 0; r < s.upper; r++) rows.push({ z: lowerBack + 2.6 + r * DEPTH, y: upperBase + (r + 1) * RISE_UP, upper: true });

    // Front wall of the lower tier.
    const front = new THREE.Mesh(new THREE.BoxGeometry(s.len, 0.9, 0.3), dark);
    front.position.set(0, 0.45, 1.35);
    g.add(front);
    rows.forEach((row, r) => {
      const step = new THREE.Mesh(new THREE.BoxGeometry(s.len, row.y, DEPTH), r % 6 < 4 ? seatMats[0] : seatMats[1]);
      step.position.set(0, row.y / 2, row.z + DEPTH / 2);
      step.receiveShadow = true;
      g.add(step);
    });
    // Concourse slab and the upper tier's fascia banner.
    if (s.upper) {
      const slab = new THREE.Mesh(new THREE.BoxGeometry(s.len, upperBase, 2.6), concrete);
      slab.position.set(0, upperBase / 2, lowerBack + 1.3);
      g.add(slab);
      const tex = bannerTexture(s.banner, kit);
      tex.repeat.set(s.len / 60, 1);
      const fascia = new THREE.Mesh(new THREE.PlaneGeometry(s.len, 1.6), new THREE.MeshBasicMaterial({ map: tex, toneMapped: false }));
      fascia.position.set(0, upperBase - 0.6, lowerBack + 0.02);
      fascia.rotation.y = Math.PI;
      g.add(fascia);
    }
    const last = rows[rows.length - 1];
    const back = last.z + DEPTH;
    const top = last.y;
    const wall = new THREE.Mesh(new THREE.BoxGeometry(s.len + 2, top + 4, 0.5), dark);
    wall.position.set(0, (top + 4) / 2, back + 0.25);
    g.add(wall);
    // Side walls close the ends of the stand.
    for (const side of [-1, 1]) {
      const end = new THREE.Mesh(new THREE.BoxGeometry(0.5, top + 4, back - 1.2), dark);
      end.position.set((side * (s.len + 0.5)) / 2, (top + 4) / 2, (back + 1.2) / 2);
      g.add(end);
    }

    // Stairways: lighter steps in the aisles.
    const aisles: number[] = [];
    for (let x = -s.len / 2 + AISLE_EVERY; x < s.len / 2 - 4; x += AISLE_EVERY) aisles.push(x);
    const stair = new THREE.InstancedMesh(new THREE.BoxGeometry(AISLE_W, 0.06, DEPTH), new THREE.MeshStandardMaterial({ color: "#8a857b", roughness: 0.9 }), aisles.length * rows.length);
    const m = new THREE.Matrix4();
    let si = 0;
    for (const x of aisles)
      for (const row of rows) {
        m.makeTranslation(x, row.y + 0.03, row.z + DEPTH / 2);
        stair.setMatrixAt(si++, m);
      }
    g.add(stair);

    // The crowd.
    const tifoRows = s.tifo ? [2, Math.min(s.lower - 2, 11)] : null;
    const tifoHalf = 17;
    const spots: { x: number; y: number; z: number; s: number }[] = [];
    rows.forEach((row, r) => {
      for (let x = -s.len / 2 + SEAT; x < s.len / 2 - SEAT / 2; x += SEAT) {
        if (aisles.some((a) => Math.abs(x - a) < AISLE_W / 2 + 0.15)) continue;
        if (tifoRows && !row.upper && r >= tifoRows[0] && r <= tifoRows[1] && Math.abs(x) < tifoHalf) continue;
        const edge = Math.pow(Math.abs(x) / (s.len / 2), 3);
        const fill = 0.94 - 0.35 * edge - (row.upper ? 0.04 * (r - s.lower) / Math.max(1, s.upper) : 0);
        if (Math.random() > fill) continue;
        spots.push({ x: x + (Math.random() - 0.5) * 0.1, y: row.y, z: row.z + DEPTH * 0.45, s: 0.92 + Math.random() * 0.16 });
      }
    });
    const n = spots.length;
    const geo = person.clone();
    const phase = new Float32Array(n);
    const mood = new Float32Array(n);
    const skin = new Float32Array(n * 3);
    const crowd = new THREE.InstancedMesh(geo, crowdMat, n);
    const col = new THREE.Color();
    const q = new THREE.Quaternion();
    const flagSpots: number[] = [];
    spots.forEach((p, i) => {
      m.compose(new THREE.Vector3(p.x, p.y, p.z), q, new THREE.Vector3(p.s, p.s, p.s));
      crowd.setMatrixAt(i, m);
      phase[i] = Math.random();
      const r = Math.random();
      mood[i] = r < 0.72 ? 0 : r < 0.93 ? 1 : 2;
      const c = Math.random();
      col.set(c < 0.6 ? kit.shirt : c < 0.8 ? kit.trim : c < 0.86 ? other.shirt : NEUTRAL[(Math.random() * NEUTRAL.length) | 0]);
      crowd.setColorAt(i, col);
      col.set(SKIN[(Math.random() * SKIN.length) | 0]).toArray(skin, i * 3);
      if (Math.random() < 0.025) flagSpots.push(i);
    });
    geo.setAttribute("aPhase", new THREE.InstancedBufferAttribute(phase, 1));
    geo.setAttribute("aMood", new THREE.InstancedBufferAttribute(mood, 1));
    geo.setAttribute("aSkin", new THREE.InstancedBufferAttribute(skin, 3));
    crowd.frustumCulled = false;
    g.add(crowd);

    // Flags held up by some fans.
    if (flagSpots.length) {
      const fg = new THREE.PlaneGeometry(1.3, 0.85, 8, 2).translate(0.65, 0, 0);
      const fphase = new Float32Array(flagSpots.length);
      const flags = new THREE.InstancedMesh(fg, flagMat, flagSpots.length);
      const poles = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.02, 0.02, 1.9, 4), new THREE.MeshStandardMaterial({ color: "#d9d4c7" }), flagSpots.length);
      flagSpots.forEach((idx, j) => {
        const p = spots[idx];
        m.makeTranslation(p.x + 0.3, p.y + 1.6, p.z);
        poles.setMatrixAt(j, m);
        m.makeTranslation(p.x + 0.3, p.y + 2.1, p.z);
        flags.setMatrixAt(j, m);
        flags.setColorAt(j, col.set(Math.random() < 0.6 ? kit.shirt : kit.trim));
        fphase[j] = Math.random();
      });
      fg.setAttribute("aPhase", new THREE.InstancedBufferAttribute(fphase, 1));
      flags.frustumCulled = false;
      g.add(flags, poles);
    }

    // The tifo: one giant flag over the lower rows.
    if (s.tifo && tifoRows) {
      const r0 = rows[tifoRows[0]];
      const r1 = rows[tifoRows[1]];
      const dz = r1.z + DEPTH - r0.z;
      const dy = r1.y - r0.y + RISE;
      const len = Math.hypot(dz, dy);
      const tifo = new THREE.Mesh(new THREE.PlaneGeometry(tifoHalf * 2, len), new THREE.MeshStandardMaterial({ map: tifoTexture(s.tifo, kit), roughness: 0.9 }));
      tifo.position.set(0, (r0.y + r1.y) / 2 + 0.55, (r0.z + r1.z + DEPTH) / 2);
      tifo.rotation.x = -Math.PI / 2 + Math.atan2(dy, dz);
      tifo.rotation.y = Math.PI;
      tifo.rotation.order = "YXZ";
      tifo.rotation.set(-(Math.PI / 2 - Math.atan2(dy, dz)), Math.PI, 0, "YXZ");
      g.add(tifo);
    }

    // Roof: sloping up to the back wall, a truss along its front, lights under it.
    if (s.roof) {
      const zf = rows[Math.floor(s.lower * 0.45)].z;
      const yf = top + 5.5;
      const yb = top + 8;
      const depth = back - zf;
      const roof = new THREE.Mesh(new THREE.BoxGeometry(s.len + 4, 0.35, Math.hypot(depth, yb - yf)), new THREE.MeshStandardMaterial({ color: "#26262a", roughness: 0.6, metalness: 0.3 }));
      roof.position.set(0, (yf + yb) / 2, (zf + back) / 2);
      roof.rotation.x = -Math.atan2(yb - yf, depth);
      g.add(roof);
      const truss = new THREE.Mesh(new THREE.BoxGeometry(s.len + 4, 1.2, 0.9), new THREE.MeshStandardMaterial({ color: "#3b3b42", metalness: 0.5, roughness: 0.5 }));
      truss.position.set(0, yf - 0.4, zf);
      g.add(truss);
      const strip = new THREE.Mesh(new THREE.BoxGeometry(s.len, 0.25, 0.3), new THREE.MeshBasicMaterial({ color: "#fff6e0", toneMapped: false }));
      strip.position.set(0, yf - 1.05, zf - 0.3);
      g.add(strip);
      const glow = new THREE.SpriteMaterial({ map: glowTexture(), blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0.55 });
      for (let x = -s.len / 2 + 5; x < s.len / 2; x += 9) {
        const sp = new THREE.Sprite(glow);
        sp.scale.set(5, 5, 1);
        sp.position.set(x, yf - 1.1, zf - 0.6);
        g.add(sp);
      }
      // Columns at the back holding it up.
      for (let x = -s.len / 2; x <= s.len / 2; x += 20) {
        const col2 = new THREE.Mesh(new THREE.BoxGeometry(0.6, yb, 0.6), dark);
        col2.position.set(x, yb / 2, back + 0.6);
        g.add(col2);
      }
    }

    if (s.screen) {
      const sc = this.screen.mesh;
      sc.position.set(0, top + 9, back - 1);
      sc.rotation.y = Math.PI;
      const frame = new THREE.Mesh(new THREE.BoxGeometry(17.8, 7.8, 0.6), dark);
      frame.position.set(0, top + 9, back - 0.6);
      g.add(frame, sc);
    }
    return g;
  }

  /** A night sky dome with a warm glow of the city on the horizon. */
  private sky() {
    const m = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
      uniforms: {},
      vertexShader: "varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
      fragmentShader: `varying vec3 vP;
void main(){
  float h = normalize(vP).y;
  vec3 top = vec3(0.02, 0.035, 0.07);
  vec3 mid = vec3(0.07, 0.1, 0.17);
  vec3 glow = vec3(0.32, 0.2, 0.12);
  vec3 c = mix(mid, top, smoothstep(0.05, 0.6, h));
  c = mix(glow, c, smoothstep(-0.02, 0.12, h));
  gl_FragColor = vec4(c, 1.0);
}`,
    });
    const dome = new THREE.Mesh(new THREE.SphereGeometry(420, 32, 16), m);
    dome.renderOrder = -1;
    return dome;
  }
}
