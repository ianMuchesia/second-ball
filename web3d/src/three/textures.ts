// Every texture is drawn on a canvas at start-up: no image files to download,
// nothing borrowed from another game.
import * as THREE from "three";

const canvas = (w: number, h: number) => {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return [c, c.getContext("2d")!] as const;
};

const tex = (c: HTMLCanvasElement) => {
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
};

export const RUNOFF = 10; // metres of grass beyond each line
const PX = 16; // canvas pixels per metre

/** The turf: mown stripes, a little grain, and the markings, 105 x 68 inside a run-off. */
export function pitchTexture(maxAniso: number): THREE.CanvasTexture {
  const LW = 105 + 2 * RUNOFF;
  const LH = 68 + 2 * RUNOFF;
  const [c, g] = canvas(LW * PX, LH * PX);
  const X = (x: number) => (x + RUNOFF) * PX;
  const Y = (y: number) => (68 + RUNOFF - y) * PX; // canvas top = far touchline (y = 68)

  g.fillStyle = "#2f7428";
  g.fillRect(0, 0, c.width, c.height);
  const stripes = 12;
  for (let i = 0; i < stripes; i++) {
    g.fillStyle = i % 2 ? "#357f2b" : "#5aa83f";
    g.fillRect(X((i * 105) / stripes), Y(68 + RUNOFF * 0.6), ((105 / stripes) * PX) | 0, (68 + RUNOFF * 1.2) * PX);
  }
  // Grain: tiny light and dark flecks.
  for (let i = 0; i < 60000; i++) {
    g.fillStyle = Math.random() < 0.5 ? "rgba(255,255,255,0.035)" : "rgba(0,0,0,0.05)";
    g.fillRect(Math.random() * c.width, Math.random() * c.height, 2, 2);
  }
  // Wear in the goalmouths and the centre circle.
  for (const [x, y, r] of [
    [5, 34, 7],
    [100, 34, 7],
    [52.5, 34, 6],
  ]) {
    const grd = g.createRadialGradient(X(x), Y(y), 0, X(x), Y(y), r * PX);
    grd.addColorStop(0, "rgba(120,110,60,0.22)");
    grd.addColorStop(1, "rgba(120,110,60,0)");
    g.fillStyle = grd;
    g.fillRect(X(x - r), Y(y + r), 2 * r * PX, 2 * r * PX);
  }

  g.strokeStyle = "rgba(245,245,238,0.92)";
  g.fillStyle = "rgba(245,245,238,0.92)";
  g.lineWidth = 0.13 * PX;
  const rect = (x: number, y: number, w: number, h: number) => g.strokeRect(X(x), Y(y + h), w * PX, h * PX);
  const circle = (x: number, y: number, r: number, a0 = 0, a1 = Math.PI * 2) => {
    g.beginPath();
    g.arc(X(x), Y(y), r * PX, a0, a1);
    g.stroke();
  };
  const spot = (x: number, y: number) => {
    g.beginPath();
    g.arc(X(x), Y(y), 0.22 * PX, 0, Math.PI * 2);
    g.fill();
  };
  rect(0, 0, 105, 68);
  g.beginPath();
  g.moveTo(X(52.5), Y(0));
  g.lineTo(X(52.5), Y(68));
  g.stroke();
  circle(52.5, 34, 9.15);
  spot(52.5, 34);
  rect(0, 34 - 20.16, 16.5, 40.32);
  rect(105 - 16.5, 34 - 20.16, 16.5, 40.32);
  rect(0, 34 - 9.16, 5.5, 18.32);
  rect(105 - 5.5, 34 - 9.16, 5.5, 18.32);
  spot(11, 34);
  spot(94, 34);
  const a = Math.acos(5.5 / 9.15);
  circle(11, 34, 9.15, -a, a);
  circle(94, 34, 9.15, Math.PI - a, Math.PI + a);
  circle(0, 0, 1, -Math.PI / 2, 0);
  circle(0, 68, 1, 0, Math.PI / 2);
  circle(105, 0, 1, Math.PI, (3 * Math.PI) / 2);
  circle(105, 68, 1, Math.PI / 2, Math.PI);

  const t = tex(c);
  t.anisotropy = maxAniso;
  return t;
}

/** The perimeter boards: the Second Ball marks on a night panel, lit from inside. */
export function boardTexture(): THREE.CanvasTexture {
  const [c, g] = canvas(1024, 64);
  const grd = g.createLinearGradient(0, 0, 0, 64);
  grd.addColorStop(0, "#1d1b18");
  grd.addColorStop(1, "#0f0e0d");
  g.fillStyle = grd;
  g.fillRect(0, 0, 1024, 64);
  g.fillStyle = "#e08a3c";
  g.fillRect(0, 0, 1024, 4);
  g.font = '800 40px "Barlow Condensed", "Arial Narrow", sans-serif';
  g.textBaseline = "middle";
  g.fillStyle = "#ede8df";
  g.fillText("SECOND BALL", 40, 36);
  g.fillStyle = "#e08a3c";
  g.fillText("3D", 268, 36);
  g.fillStyle = "#a39d92";
  g.font = '600 30px "Barlow Condensed", "Arial Narrow", sans-serif';
  g.fillText("SYNTHETIC LEAGUE · FICTIONAL CLUBS", 560, 36);
  const t = tex(c);
  t.wrapS = THREE.RepeatWrapping;
  return t;
}

/** Goal net mesh: a fine grid on a transparent background. */
export function netTexture(): THREE.CanvasTexture {
  const [c, g] = canvas(128, 128);
  g.strokeStyle = "rgba(240,240,240,0.85)";
  g.lineWidth = 3;
  for (let i = 0; i <= 128; i += 16) {
    g.beginPath();
    g.moveTo(i, 0);
    g.lineTo(i, 128);
    g.moveTo(0, i);
    g.lineTo(128, i);
    g.stroke();
  }
  const t = tex(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

/** A soft round glow for the floodlight heads. */
export function glowTexture(): THREE.CanvasTexture {
  const [c, g] = canvas(128, 128);
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, "rgba(255,250,235,1)");
  grd.addColorStop(0.2, "rgba(255,240,210,0.55)");
  grd.addColorStop(1, "rgba(255,230,190,0)");
  g.fillStyle = grd;
  g.fillRect(0, 0, 128, 128);
  return tex(c);
}

/** The match ball: white with dark panels, so its spin reads. */
export function ballTexture(): THREE.CanvasTexture {
  const [c, g] = canvas(256, 128);
  g.fillStyle = "#f4f2ec";
  g.fillRect(0, 0, 256, 128);
  g.fillStyle = "#1a1917";
  const spots = [
    [32, 30], [96, 64], [160, 30], [224, 64], [32, 98], [160, 98], [96, 8], [224, 8], [96, 120], [224, 120],
  ];
  for (const [x, y] of spots) {
    g.beginPath();
    for (let k = 0; k < 5; k++) {
      const a = (k / 5) * Math.PI * 2 - Math.PI / 2;
      g.lineTo(x + Math.cos(a) * 13, y + Math.sin(a) * 11);
    }
    g.closePath();
    g.fill();
  }
  g.fillStyle = "#e08a3c";
  g.fillRect(0, 62, 256, 4);
  return tex(c);
}

/** The shirt number for a player's back. */
export function numberTexture(n: number, ink: string): THREE.CanvasTexture {
  const [c, g] = canvas(128, 128);
  g.clearRect(0, 0, 128, 128);
  g.fillStyle = ink;
  g.font = '800 92px "Barlow Condensed", "Arial Narrow", sans-serif';
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(String(n || ""), 64, 70);
  return tex(c);
}
