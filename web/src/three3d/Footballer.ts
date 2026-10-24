// A footballer: the Quaternius mannequin (Universal Animation Library, CC0)
// with its idle / walk / jog / sprint cycles, dressed in a club kit by a shader, and moved by
// a steering layer so it runs, accelerates and turns like a person.
//
// Why the feet do not slide: the walk and run cycles are not played at a fixed
// rate. Each frame the cycle advances by (distance covered / stride length), so
// one stride on screen is one stride over the grass, at any speed and any
// playback rate.
import * as THREE from "three";
import { type GLTF, GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";
import type { Kit } from "./kits";

const SKINS = ["#3b2219", "#4a2c1e", "#5a3825", "#6e452c", "#8d5f3f", "#b07c55", "#c99a76", "#e0b893"];
const HAIR = ["#0b0908", "#15100c", "#1f150e", "#3a2817", "#0b0908", "#5c3d1e"];

// Metres covered by one cycle (two steps) of each loop at its natural pace.
const STRIDE = { walk: 1.85, jog: 3.1, sprint: 4.6 };
const MAX_SPEED = 9.2; // m/s: a sprinting footballer
const MAX_ACCEL = 7.5; // m/s²
const STIFF = 3.6; // how tightly a player tracks the engine's path (rad/s)

let proto: Promise<GLTF> | null = null;
export const loadRig = () => (proto ??= new GLTFLoader().loadAsync("/models/mannequin.glb"));

const hash = (s: string) => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
};

/** The kit shader: colours by where a vertex sits on the body in the bind
 * (T-) pose, so the kit moves with the skin. */
function kitMaterial(kit: Kit, skin: string, hair: string): THREE.MeshStandardMaterial {
  const PATTERN = { plain: 0, stripes: 1, hoops: 2, sash: 3, halves: 4 };
  const u = {
    uShirt: { value: new THREE.Color(kit.shirt) },
    uTrim: { value: new THREE.Color(kit.trim) },
    uShorts: { value: new THREE.Color(kit.shorts) },
    uSocks: { value: new THREE.Color(kit.socks) },
    uBoots: { value: new THREE.Color(kit.boots) },
    uSkin: { value: new THREE.Color(skin) },
    uHair: { value: new THREE.Color(hair) },
    uPattern: { value: PATTERN[kit.pattern] },
  };
  const m = new THREE.MeshStandardMaterial({ roughness: 0.62, metalness: 0 });
  m.onBeforeCompile = (s) => {
    Object.assign(s.uniforms, u);
    s.vertexShader = "varying vec3 vBind;\n" + s.vertexShader.replace("#include <begin_vertex>", "#include <begin_vertex>\nvBind = position;");
    s.fragmentShader =
      `varying vec3 vBind;
uniform vec3 uShirt, uTrim, uShorts, uSocks, uBoots, uSkin, uHair;
uniform int uPattern;
vec3 kitColour() {
  float y = vBind.y, x = vBind.x, ax = abs(x), z = vBind.z;
  // Measured on the mannequin's T-pose (1.83 m): head from 1.6, neck 1.53, chest
  // 1.25-1.5 and 0.28 either side, arms out from |x| 0.28 to the fingertips at
  // 0.97, hips 0.9-1.0, knees about 0.5, boots below 0.12.
  if (y > 1.76 || (y > 1.66 && z < -0.03)) return uHair;
  if (y > 1.53) return uSkin;
  if (ax > 0.29) return ax < 0.5 ? uShirt : (ax < 0.535 ? uTrim : uSkin);
  if (y > 0.95) {
    if (y > 1.5 && ax < 0.12) return uTrim; // collar
    vec3 c = uShirt;
    if (uPattern == 1) c = mod(floor((x + 1.0) / 0.075), 2.0) < 1.0 ? uShirt : uTrim;
    else if (uPattern == 2) c = mod(floor(y / 0.085), 2.0) < 1.0 ? uShirt : uTrim;
    else if (uPattern == 3) c = abs(x * 0.9 - (y - 1.2)) < 0.055 ? uTrim : uShirt;
    else if (uPattern == 4) c = x > 0.0 ? uShirt : uTrim;
    return c;
  }
  if (y > 0.66) return y < 0.69 ? uTrim : uShorts;
  if (y > 0.48) return uSkin;
  if (y > 0.12) return y > 0.45 ? uTrim : uSocks;
  return uBoots;
}
` + s.fragmentShader.replace("vec4 diffuseColor = vec4( diffuse, opacity );", "vec4 diffuseColor = vec4( kitColour(), opacity );");
  };
  m.customProgramCacheKey = () => "kit-mannequin-v1";
  return m;
}

export class Footballer {
  root = new THREE.Group();
  speed = 0;
  private model: THREE.Object3D;
  private mixer: THREE.AnimationMixer;
  private idle: THREE.AnimationAction;
  private walk: THREE.AnimationAction;
  private jog: THREE.AnimationAction;
  private sprint: THREE.AnimationAction;
  private dance: THREE.AnimationAction;
  private phase = Math.random();
  private pos = new THREE.Vector2();
  private vel = new THREE.Vector2();
  private lastTarget = new THREE.Vector2();
  private placed = false;
  private heading = 0;
  private kickBone: THREE.Bone | null = null;
  private armBone: THREE.Bone | null = null;
  private armBoneR: THREE.Bone | null = null;
  private halo: THREE.Mesh;
  private marker: THREE.Mesh;
  private q = new THREE.Quaternion();
  private ax = new THREE.Vector3(1, 0, 0);

  constructor(gltf: GLTF, id: string, kit: Kit) {
    const h = hash(id);
    const mat = kitMaterial(kit, SKINS[h % SKINS.length], HAIR[(h >>> 5) % HAIR.length]);
    this.model = cloneSkinned(gltf.scene);
    this.model.traverse((o) => {
      const m = o as THREE.SkinnedMesh;
      if (m.isSkinnedMesh) {
        m.material = mat;
        m.castShadow = true;
        m.frustumCulled = false;
      }
      if ((o as THREE.Bone).isBone) {
        if (o.name === "DEF-thigh.R") this.kickBone = o as THREE.Bone;
        if (o.name === "DEF-upper_arm.L") this.armBone = o as THREE.Bone;
        if (o.name === "DEF-upper_arm.R") this.armBoneR = o as THREE.Bone;
      }
    });
    // Slight variety in build: not 22 identical people.
    const s = 0.97 + ((h >>> 9) % 100) / 1000;
    this.model.scale.set(s * (0.98 + ((h >>> 3) % 40) / 1000), s, s);
    this.root.add(this.model);

    this.mixer = new THREE.AnimationMixer(this.model);
    const clip = (name: string) => gltf.animations.find((a) => a.name === name)!;
    this.idle = this.mixer.clipAction(clip("Idle_Loop"));
    this.walk = this.mixer.clipAction(clip("Walk_Loop"));
    this.jog = this.mixer.clipAction(clip("Jog_Fwd_Loop"));
    this.sprint = this.mixer.clipAction(clip("Sprint_Loop"));
    this.dance = this.mixer.clipAction(clip("Dance_Loop"));
    for (const a of [this.idle, this.walk, this.jog, this.sprint, this.dance]) {
      a.play();
      a.setEffectiveWeight(0);
    }
    this.idle.time = Math.random() * this.idle.getClip().duration;
    // The gaits are driven by distance covered (below), not by the clock.
    for (const a of [this.walk, this.jog, this.sprint]) a.setEffectiveTimeScale(0);

    this.halo = new THREE.Mesh(
      new THREE.RingGeometry(0.55, 0.7, 40),
      new THREE.MeshBasicMaterial({ color: "#e08a3c", transparent: true, depthWrite: false, toneMapped: false }),
    );
    this.halo.rotation.x = -Math.PI / 2;
    this.halo.position.y = 0.03;
    this.marker = new THREE.Mesh(
      new THREE.ConeGeometry(0.22, 0.38, 3),
      new THREE.MeshBasicMaterial({ color: "#e08a3c", toneMapped: false }),
    );
    this.marker.rotation.x = Math.PI; // point down
    this.marker.position.y = 2.35;
    this.halo.visible = this.marker.visible = false;
    this.root.add(this.halo, this.marker);
  }

  set lit(on: boolean) {
    this.halo.visible = this.marker.visible = on;
  }

  get x() {
    return this.pos.x;
  }
  get facing() {
    return this.heading;
  }
  /** Where the ball sits when this player has it: just in front of the boots. */
  feet(out: THREE.Vector2, reach = 0.5) {
    return out.set(this.pos.x + Math.sin(this.heading) * reach, this.pos.y + Math.cos(this.heading) * reach);
  }
  get z() {
    return this.pos.y;
  }

  /** Steer towards the engine's path at (tx, tz) and animate.
   * dtMatch: match seconds this frame (0 when paused); snap: jump there (a seek).
   * kick: 0..1 through a strike, or -1. */
  step(tx: number, tz: number, ballX: number, ballZ: number, dtMatch: number, dtReal: number, kick: number, snap: boolean, dive = 0, power = 1, celebrate = 0) {
    if (Number.isNaN(tx)) {
      this.root.visible = false;
      return;
    }
    this.root.visible = true;
    const far = Math.hypot(tx - this.pos.x, tz - this.pos.y) > 16;
    if (!this.placed || snap || far) {
      this.pos.set(tx, tz);
      this.vel.set(0, 0);
      this.lastTarget.set(tx, tz);
      this.placed = true;
    } else if (dtMatch > 0) {
      // The path's own velocity, fed forward, so tracking does not lag.
      const tvx = (tx - this.lastTarget.x) / dtMatch;
      const tvz = (tz - this.lastTarget.y) / dtMatch;
      this.lastTarget.set(tx, tz);
      const n = Math.ceil(dtMatch / (1 / 60));
      const h = dtMatch / n;
      for (let i = 0; i < n; i++) {
        let ax = STIFF * STIFF * (tx - this.pos.x) + 2 * STIFF * (tvx - this.vel.x);
        let az = STIFF * STIFF * (tz - this.pos.y) + 2 * STIFF * (tvz - this.vel.y);
        const a = Math.hypot(ax, az);
        if (a > MAX_ACCEL) {
          ax *= MAX_ACCEL / a;
          az *= MAX_ACCEL / a;
        }
        this.vel.x += ax * h;
        this.vel.y += az * h;
        const v = this.vel.length();
        if (v > MAX_SPEED) this.vel.multiplyScalar(MAX_SPEED / v);
        this.pos.x += this.vel.x * h;
        this.pos.y += this.vel.y * h;
      }
    }
    if (dtMatch === 0 && !snap) this.vel.multiplyScalar(Math.exp(-dtReal * 10)); // paused: settle into idle
    // Face where you run; when (nearly) still, watch the ball.
    const v0 = this.vel.length();
    const want = v0 > 0.7 ? Math.atan2(this.vel.x, this.vel.y) : Math.atan2(ballX - this.pos.x, ballZ - this.pos.y);
    const turn = Math.min(1, (snap ? 1 : 0) + Math.max(dtMatch, dtReal * 0.5) * 7);
    this.pose(want, turn, ballX, ballZ, dtMatch, kick, dive, power, celebrate);
  }

  /** Play the engine's movement exactly: position, velocity and facing come
   * from the 10 Hz track (world metres, heading in radians as root.rotation.y);
   * only the body's animation is drawn here. */
  follow(x: number, z: number, vx: number, vz: number, heading: number, ballX: number, ballZ: number, dtMatch: number, kick: number, dive = 0, power = 1, celebrate = 0) {
    if (Number.isNaN(x)) {
      this.root.visible = false;
      return;
    }
    this.root.visible = true;
    this.pos.set(x, z);
    this.vel.set(vx, vz);
    this.lastTarget.set(x, z);
    this.placed = true;
    this.pose(heading, 1, ballX, ballZ, dtMatch, kick, dive, power, celebrate);
  }

  private pose(want: number, turn: number, ballX: number, ballZ: number, dtMatch: number, kick: number, dive: number, power: number, celebrate: number) {
    this.root.position.set(this.pos.x, 0, this.pos.y);
    const v = this.vel.length();
    this.speed = v;
    let d = want - this.heading;
    d = Math.atan2(Math.sin(d), Math.cos(d));
    this.heading += d * turn;
    this.root.rotation.y = this.heading;

    // Gait: idle -> walk -> jog -> sprint by speed; the cycle advances by ground covered.
    const idleW = THREE.MathUtils.clamp(1 - v / 0.55, 0, 1);
    const jogW = THREE.MathUtils.smoothstep(v, 1.8, 3.0);
    const sprintW = THREE.MathUtils.smoothstep(v, 5.0, 6.6);
    const walkW = (1 - idleW) * (1 - jogW);
    const runW = (1 - idleW) * jogW;
    const stride =
      THREE.MathUtils.lerp(THREE.MathUtils.lerp(STRIDE.walk, STRIDE.jog, jogW), STRIDE.sprint, sprintW) * (v > 7.5 ? 1 + (v - 7.5) * 0.05 : 1);
    this.phase = (this.phase + (v * dtMatch) / stride) % 1;
    // A scorer celebrating dances instead (weights fade the gait out).
    const keep = 1 - celebrate;
    this.idle.setEffectiveWeight(idleW * keep);
    this.walk.setEffectiveWeight(walkW * keep);
    this.jog.setEffectiveWeight(runW * (1 - sprintW) * keep);
    this.sprint.setEffectiveWeight(runW * sprintW * keep);
    this.dance.setEffectiveWeight(celebrate);
    for (const a of [this.walk, this.jog, this.sprint]) a.time = this.phase * a.getClip().duration;
    this.mixer.update(dtMatch > 0 ? dtMatch : 0);

    // A dive: the whole body rolls towards the ball, off the ground, arms reaching.
    if (dive > 0) {
      const side = Math.sign((ballX - this.pos.x) * -Math.cos(this.heading) + (ballZ - this.pos.y) * Math.sin(this.heading)) || 1;
      const d = Math.sin(Math.min(1, dive) * Math.PI * 0.5);
      this.model.rotation.z = side * d * 1.25;
      this.model.position.y = Math.sin(dive * Math.PI) * 0.45;
      if (this.armBone) this.armBone.quaternion.multiply(this.q.setFromAxisAngle(this.ax, -1.6 * d));
      if (this.armBoneR) this.armBoneR.quaternion.multiply(this.q.setFromAxisAngle(this.ax, -1.6 * d));
    } else if (this.model.rotation.z !== 0) {
      this.model.rotation.z = 0;
      this.model.position.y = 0;
    }

    if (kick >= 0 && this.kickBone) {
      // Wind back, then strike through: on top of whatever the legs were doing.
      const k = (kick < 0.4 ? -(kick / 0.4) * 0.7 : -0.7 + ((kick - 0.4) / 0.6) * 2.0) * power;
      this.kickBone.quaternion.multiply(this.q.setFromAxisAngle(this.ax, k));
      if (this.armBone) this.armBone.quaternion.multiply(this.q.setFromAxisAngle(this.ax, -0.5 * Math.min(1, kick * 2)));
    }
  }

  top(out: THREE.Vector3) {
    return out.set(this.pos.x, 2.4, this.pos.y);
  }
}
