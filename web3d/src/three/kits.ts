// Club colours for the fictional league. Invented for this viewer: no real
// club's kit is copied. The away side switches to its change kit on a clash.

export type Pattern = "plain" | "stripes" | "hoops" | "sash" | "halves";

export interface Kit {
  shirt: string;
  trim: string; // pattern, collar and cuffs
  pattern: Pattern;
  shorts: string;
  socks: string;
  boots: string;
}

const K = (shirt: string, trim: string, pattern: Pattern, shorts: string, socks: string, boots = "#141414"): Kit => ({
  shirt,
  trim,
  pattern,
  shorts,
  socks,
  boots,
});

export const CLUB_KITS: Record<string, { home: Kit; change: Kit }> = {
  riverside_athletic: { home: K("#f2c318", "#13294b", "plain", "#13294b", "#f2c318"), change: K("#13294b", "#f2c318", "plain", "#13294b", "#13294b") },
  kilele_chui: { home: K("#f4f4ef", "#1f8a4c", "sash", "#1f8a4c", "#f4f4ef"), change: K("#1f8a4c", "#f4f4ef", "plain", "#f4f4ef", "#1f8a4c") },
  ashgrove: { home: K("#7a1f2b", "#f4f4ef", "plain", "#f4f4ef", "#7a1f2b"), change: K("#f4f4ef", "#7a1f2b", "plain", "#7a1f2b", "#f4f4ef") },
  ironvale: { home: K("#59646e", "#ef7d2d", "stripes", "#22262b", "#59646e"), change: K("#ef7d2d", "#22262b", "plain", "#22262b", "#ef7d2d") },
  harbour_town: { home: K("#1c2c4c", "#7fb7e6", "hoops", "#1c2c4c", "#7fb7e6"), change: K("#f4f4ef", "#1c2c4c", "plain", "#1c2c4c", "#f4f4ef") },
  kingsbridge_ravens: { home: K("#161616", "#c8102e", "stripes", "#161616", "#161616"), change: K("#f4f4ef", "#c8102e", "plain", "#f4f4ef", "#f4f4ef") },
  lantern_hill: { home: K("#ea8a1a", "#111111", "plain", "#111111", "#ea8a1a"), change: K("#111111", "#ea8a1a", "plain", "#111111", "#111111") },
  port_ilvane: { home: K("#11878a", "#f4f4ef", "halves", "#f4f4ef", "#11878a"), change: K("#f4f4ef", "#11878a", "plain", "#11878a", "#f4f4ef") },
  quarry_end: { home: K("#6b1d3a", "#7ab8e0", "hoops", "#f4f4ef", "#6b1d3a"), change: K("#7ab8e0", "#6b1d3a", "plain", "#6b1d3a", "#7ab8e0") },
  saltmere: { home: K("#7ab4e3", "#13294b", "plain", "#13294b", "#7ab4e3"), change: K("#13294b", "#7ab4e3", "plain", "#13294b", "#13294b") },
  thornfield_athletic: { home: K("#2e7d32", "#f4f4ef", "hoops", "#f4f4ef", "#2e7d32"), change: K("#f4f4ef", "#2e7d32", "plain", "#2e7d32", "#f4f4ef") },
  tidewick: { home: K("#c62828", "#f4f4ef", "plain", "#f4f4ef", "#c62828"), change: K("#f4f4ef", "#c62828", "plain", "#c62828", "#f4f4ef") },
  westmarch: { home: K("#5b2c83", "#f2c318", "sash", "#f4f4ef", "#5b2c83"), change: K("#f2c318", "#5b2c83", "plain", "#5b2c83", "#f2c318") },
};

export const GK_KITS: Kit[] = [K("#9be15d", "#1d3b12", "plain", "#1d3b12", "#9be15d"), K("#d14fa0", "#2a0f22", "plain", "#2a0f22", "#d14fa0")];
export const REF_KIT: Kit = K("#2bb3e8", "#0d1b2a", "plain", "#0d1b2a", "#0d1b2a");

const FALLBACK = { home: K("#ede8df", "#22201d", "plain", "#22201d", "#ede8df"), change: K("#2c2a26", "#ede8df", "plain", "#ede8df", "#2c2a26") };

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const far = (a: string, b: string) => {
  const [x, y] = [rgb(a), rgb(b)];
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) > 120;
};

/** The two kits on the pitch: the away side changes if the shirts are too alike. */
export function matchKits(home: string, away: string): { home: Kit; away: Kit } {
  const h = (CLUB_KITS[home] ?? FALLBACK).home;
  const a = CLUB_KITS[away] ?? FALLBACK;
  return { home: h, away: far(h.shirt, a.home.shirt) ? a.home : a.change };
}
