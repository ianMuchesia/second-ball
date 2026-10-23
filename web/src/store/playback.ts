// What the viewer is doing: the playback clock (match seconds), speed,
// persona, language, tab, and what is selected or highlighted.
import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

export interface IndicatorPick {
  metric: string;
  key: string;
  label: string;
}

export interface Playback {
  t: number;
  playing: boolean;
  speed: number;
  persona: "casual" | "analyst";
  lang: string;
  tab: "broadcast" | "producer";
  panel: "moments" | "stats"; // the Match Centre column
  momentId: string | null; // selected moment (timeline marker or "Why?")
  drawerOpen: boolean;
  indicator: IndicatorPick | null;
  highlighted: string[]; // player ids lit on the pitch
  focusEventId: string | null; // the event whose ball path is lit
}

// A deep link (?t=<match seconds>) opens the replay at that moment.
const linked = Number(new URLSearchParams(window.location.search).get("t"));

const initialState: Playback = {
  t: Number.isFinite(linked) && linked > 0 ? linked : 0,
  playing: false,
  speed: 4,
  persona: "casual",
  lang: "en",
  tab: "broadcast",
  panel: "moments",
  momentId: null,
  drawerOpen: false,
  indicator: null,
  highlighted: [],
  focusEventId: null,
};

// The match length is derived from the events, never stored: actions that
// move the clock forward carry it.
const clamp = (t: number, end = Infinity) => Math.max(0, Math.min(end, t));

export const playback = createSlice({
  name: "playback",
  initialState,
  reducers: {
    tick(s, a: PayloadAction<{ dt: number; end: number }>) {
      // dt: wall seconds since the last frame
      s.t = clamp(s.t + a.payload.dt * s.speed, a.payload.end);
      if (s.t >= a.payload.end) s.playing = false;
    },
    jump(s, a: PayloadAction<{ t: number; end: number }>) {
      s.t = clamp(a.payload.t, a.payload.end);
    },
    setPlaying(s, a: PayloadAction<boolean>) {
      s.playing = a.payload;
    },
    setSpeed(s, a: PayloadAction<number>) {
      s.speed = a.payload;
    },
    setPersona(s, a: PayloadAction<Playback["persona"]>) {
      s.persona = a.payload;
    },
    setLang(s, a: PayloadAction<string>) {
      s.lang = a.payload;
    },
    setTab(s, a: PayloadAction<Playback["tab"]>) {
      s.tab = a.payload;
    },
    setPanel(s, a: PayloadAction<Playback["panel"]>) {
      s.panel = a.payload;
    },
    selectMoment(s, a: PayloadAction<string | null>) {
      s.momentId = a.payload;
    },
    // Evidence opened: the moment's players are lit, its first event focused.
    openDrawer(s, a: PayloadAction<{ momentId: string; players: string[]; eventId: string | null }>) {
      s.momentId = a.payload.momentId;
      s.drawerOpen = true;
      s.highlighted = a.payload.players;
      s.focusEventId = a.payload.eventId;
    },
    closeDrawer(s) {
      s.drawerOpen = false;
      s.highlighted = [];
      s.focusEventId = null;
    },
    openIndicator(s, a: PayloadAction<IndicatorPick | null>) {
      s.indicator = a.payload;
    },
    // Evidence clicked: the pitch jumps there and lights the players.
    focusEvent(s, a: PayloadAction<{ t: number; eventId: string; players: string[] }>) {
      s.t = clamp(a.payload.t);
      s.playing = false;
      s.focusEventId = a.payload.eventId;
      s.highlighted = a.payload.players;
    },
  },
});

export const actions = playback.actions;
