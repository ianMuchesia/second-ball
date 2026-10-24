// The viewer's profile: persona, language, favourite club, followed player,
// pinned metric. Saved per viewer in this browser (localStorage, every read
// and write in try/catch: a private window or blocked storage just means the
// defaults). Personalization picks and words; it never changes a fact.
import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

export type Persona = "casual" | "analyst"; // "casual" is the fan

export interface Profile {
  persona: Persona;
  lang: string;
  favouriteClub: string | null; // team_id: ranks its moments first, wording neutral
  followedPlayer: string | null; // player_id: name tag on, his card and moments
  pinnedMetric: string | null; // registry metric, always on screen
  view: "2d" | "3d"; // the pitch: 2D by default; 3D only where the device can
}

const KEY = "second-ball.profile.v1";

export const defaults: Profile = {
  persona: "casual",
  lang: "en",
  favouriteClub: null,
  followedPlayer: null,
  pinnedMetric: null,
  view: "2d",
};

export function loadProfile(): Profile {
  try {
    const saved = JSON.parse(window.localStorage.getItem(KEY) ?? "{}");
    return { ...defaults, ...(saved && typeof saved === "object" ? saved : {}) };
  } catch {
    return defaults;
  }
}

export function saveProfile(p: Profile): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    // storage unavailable: the profile lasts for this visit only
  }
}

export const profile = createSlice({
  name: "profile",
  initialState: loadProfile,
  reducers: {
    setPersona(s, a: PayloadAction<Persona>) {
      s.persona = a.payload;
    },
    setLang(s, a: PayloadAction<string>) {
      s.lang = a.payload;
    },
    setFavouriteClub(s, a: PayloadAction<string | null>) {
      s.favouriteClub = a.payload;
    },
    follow(s, a: PayloadAction<string | null>) {
      s.followedPlayer = a.payload;
    },
    pin(s, a: PayloadAction<string | null>) {
      s.pinnedMetric = a.payload;
    },
    setView(s, a: PayloadAction<Profile["view"]>) {
      s.view = a.payload;
    },
  },
});

export const profileActions = profile.actions;
