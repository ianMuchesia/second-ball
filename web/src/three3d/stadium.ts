// The ground: turf, goals, flags, boards, four stands with a crowd, roofs and
// floodlights. World frame: X along the pitch (home attacks +X), Z across it
// (the main camera side is +Z, the touchline y = 0), Y up. 1 unit = 1 metre.
import * as THREE from "three";
import type { Kit } from "./kits";
import { Stands } from "./stands";
import { boardTexture, glowTexture, netTexture, pitchTexture, RUNOFF } from "./textures";

export const wx = (x: number) => x - 52.5;
export const wz = (y: number) => 34 - y;

export class Stadium {
  group = new THREE.Group();
  stands: Stands;
  private rain: THREE.LineSegments | null = null;

  constructor(renderer: THREE.WebGLRenderer, weather: string, home: Kit, away: Kit, names: { home: string; away: string }) {
    this.turf(renderer.capabilities.getMaxAnisotropy());
    this.goal(-1);
    this.goal(1);
    this.flags();
    this.boards();
    // Main stand (camera side): one tier, no roof. Far side: two tiers. Home end: the tifo. Away end: the big screen.
    const banner = names.home.toUpperCase() + "  ·  SECOND BALL";
    this.stands = new Stands(
      [
        { len: 124, at: 42, rotation: 0, lower: 14, upper: 0, roof: false, fans: "home", banner },
        { len: 124, at: 42, rotation: Math.PI, lower: 14, upper: 11, roof: true, fans: "home", banner },
        { len: 80, at: 60.5, rotation: Math.PI / 2, lower: 13, upper: 8, roof: true, fans: "home", banner, tifo: names.home.toUpperCase() },
        { len: 80, at: 60.5, rotation: -Math.PI / 2, lower: 13, upper: 8, roof: true, fans: "away", banner: names.away.toUpperCase() + "  ·  AWAY END", screen: true },
      ],
      home,
      away,
    );
    this.group.add(this.stands.group);
    this.floodlights();
    if (weather === "rain") this.makeRain();
  }

  private turf(aniso: number) {
    const geo = new THREE.PlaneGeometry(105 + 2 * RUNOFF, 68 + 2 * RUNOFF);
    const mat = new THREE.MeshStandardMaterial({ map: pitchTexture(aniso), roughness: 0.92, metalness: 0 });
    const turf = new THREE.Mesh(geo, mat);
    turf.rotation.x = -Math.PI / 2;
    turf.receiveShadow = true;
    this.group.add(turf);
    // The concourse around the run-off.
    const apron = new THREE.Mesh(
      new THREE.PlaneGeometry(240, 200),
      new THREE.MeshStandardMaterial({ color: "#121110", roughness: 1 }),
    );
    apron.rotation.x = -Math.PI / 2;
    apron.position.y = -0.02;
    apron.receiveShadow = true;
    this.group.add(apron);
  }

  private goal(side: -1 | 1) {
    const g = new THREE.Group();
    const white = new THREE.MeshStandardMaterial({ color: "#f5f5f0", roughness: 0.35, metalness: 0.2 });
    const post = new THREE.CylinderGeometry(0.06, 0.06, 2.44, 12);
    const bar = new THREE.CylinderGeometry(0.06, 0.06, 7.32 + 0.12, 12);
    for (const z of [-3.66, 3.66]) {
      const p = new THREE.Mesh(post, white);
      p.position.set(0, 1.22, z);
      p.castShadow = true;
      g.add(p);
    }
    const cross = new THREE.Mesh(bar, white);
    cross.rotation.x = Math.PI / 2;
    cross.position.set(0, 2.44, 0);
    cross.castShadow = true;
    g.add(cross);

    const net = netTexture();
    const netMat = (rx: number, ry: number) => {
      const t = net.clone();
      t.repeat.set(rx, ry);
      t.needsUpdate = true;
      return new THREE.MeshBasicMaterial({ map: t, transparent: true, side: THREE.DoubleSide, depthWrite: false, opacity: 0.55 });
    };
    const D = 2.0; // net depth
    const back = new THREE.Mesh(new THREE.PlaneGeometry(7.32, 2.44), netMat(14, 5));
    back.rotation.y = Math.PI / 2;
    back.position.set(D, 1.22, 0);
    const top = new THREE.Mesh(new THREE.PlaneGeometry(D, 7.32), netMat(4, 14));
    top.rotation.x = -Math.PI / 2;
    top.position.set(D / 2, 2.44, 0);
    g.add(back, top);
    for (const z of [-3.66, 3.66]) {
      const s = new THREE.Mesh(new THREE.PlaneGeometry(D, 2.44), netMat(4, 5));
      s.position.set(D / 2, 1.22, z);
      g.add(s);
    }
    g.position.x = side * 52.5;
    if (side < 0) g.rotation.y = Math.PI;
    this.group.add(g);
  }

  private flags() {
    const pole = new THREE.CylinderGeometry(0.025, 0.025, 1.5, 6);
    const poleMat = new THREE.MeshStandardMaterial({ color: "#ede8df" });
    const flagMat = new THREE.MeshStandardMaterial({ color: "#e08a3c", side: THREE.DoubleSide, emissive: "#3a1d05" });
    const flag = new THREE.PlaneGeometry(0.4, 0.3);
    for (const x of [-52.5, 52.5])
      for (const z of [-34, 34]) {
        const p = new THREE.Mesh(pole, poleMat);
        p.position.set(x, 0.75, z);
        p.castShadow = true;
        const f = new THREE.Mesh(flag, flagMat);
        f.position.set(x + 0.2 * Math.sign(-x), 1.35, z);
        this.group.add(p, f);
      }
  }

  private boards() {
    const t = boardTexture();
    const mk = (len: number) => {
      const map = t.clone();
      map.repeat.set(len / 26, 1);
      map.needsUpdate = true;
      const face = new THREE.MeshBasicMaterial({ map, toneMapped: false });
      const dark = new THREE.MeshStandardMaterial({ color: "#0f0e0d" });
      // Box faces: +x, -x, +y, -y, +z (front), -z (back)
      return new THREE.Mesh(new THREE.BoxGeometry(len, 0.9, 0.12), [dark, dark, dark, dark, face, face]);
    };
    const near = mk(112);
    near.position.set(0, 0.45, 34 + 4.5);
    const far = mk(112);
    far.position.set(0, 0.45, -34 - 4.5);
    const left = mk(70);
    left.rotation.y = Math.PI / 2;
    left.position.set(-52.5 - 5, 0.45, 0);
    const right = mk(70);
    right.rotation.y = Math.PI / 2;
    right.position.set(52.5 + 5, 0.45, 0);
    for (const b of [near, far, left, right]) b.castShadow = true;
    this.group.add(near, far, left, right);
  }

  private floodlights() {
    const glow = new THREE.SpriteMaterial({ map: glowTexture(), blending: THREE.AdditiveBlending, depthWrite: false, transparent: true });
    const mast = new THREE.MeshStandardMaterial({ color: "#3a3833", metalness: 0.6, roughness: 0.5 });
    const lamp = new THREE.MeshBasicMaterial({ color: "#fff8e8", toneMapped: false });
    for (const x of [-1, 1])
      for (const z of [-1, 1]) {
        const g = new THREE.Group();
        const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.6, 38, 8), mast);
        pole.position.y = 19;
        const head = new THREE.Mesh(new THREE.BoxGeometry(6, 3, 0.4), lamp);
        head.position.y = 39;
        head.lookAt(new THREE.Vector3(-x * 60, -30, -z * 40));
        const s = new THREE.Sprite(glow);
        s.scale.set(26, 26, 1);
        s.position.y = 39;
        g.add(pole, head, s);
        g.position.set(x * 72, 0, z * 56);
        this.group.add(g);
      }
  }

  private makeRain() {
    const N = 5000;
    const pos = new Float32Array(N * 6);
    for (let i = 0; i < N; i++) {
      const x = (Math.random() - 0.5) * 140;
      const y = Math.random() * 40;
      const z = (Math.random() - 0.5) * 100;
      pos.set([x, y, z, x + 0.05, y + 0.7, z], i * 6);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    this.rain = new THREE.LineSegments(
      geo,
      new THREE.LineBasicMaterial({ color: "#cfd8e6", transparent: true, opacity: 0.35, depthWrite: false }),
    );
    this.group.add(this.rain);
  }

  /** Rain falls in real time, whatever the playback speed. */
  update(dt: number) {
    if (!this.rain) return;
    const a = this.rain.geometry.getAttribute("position") as THREE.BufferAttribute;
    const p = a.array as Float32Array;
    const fall = 26 * dt;
    for (let i = 0; i < p.length; i += 6) {
      p[i + 1] -= fall;
      p[i + 4] -= fall;
      if (p[i + 1] < 0) {
        p[i + 1] += 40;
        p[i + 4] += 40;
      }
    }
    a.needsUpdate = true;
  }
}
