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
  focusEventId: string | null; // the clicked evidence event (that instant)
  move: string[] | null; // the open moment's move: its actions are drawn
  until: number | null; // playing the move: stop here (its last action)
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
  move: null,
  until: null,
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
      const stop = Math.min(a.payload.end, s.until ?? Infinity);
      s.t = clamp(s.t + a.payload.dt * s.speed, stop);
      if (s.t >= stop) {
        s.playing = false;
        s.until = null;
      }
    },
    jump(s, a: PayloadAction<{ t: number; end: number }>) {
      s.t = clamp(a.payload.t, a.payload.end);
      s.until = null;
    },
    setPlaying(s, a: PayloadAction<boolean>) {
      s.playing = a.payload;
      s.until = null;
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
    // Evidence opened: the whole replay goes to the start of the move (clock,
    // players, ball together) and plays it at 1x, stopping at its last action.
    openDrawer(s, a: PayloadAction<{ momentId: string; players: string[]; move: string[]; from: number; to: number }>) {
      s.momentId = a.payload.momentId;
      s.drawerOpen = true;
      s.highlighted = a.payload.players;
      s.move = a.payload.move;
      s.focusEventId = null;
      s.t = clamp(a.payload.from);
      s.until = a.payload.to;
      s.speed = 1;
      s.playing = a.payload.to > a.payload.from;
    },
    closeDrawer(s) {
      s.drawerOpen = false;
      s.highlighted = [];
      s.focusEventId = null;
      s.move = null;
      s.until = null;
    },
    openIndicator(s, a: PayloadAction<IndicatorPick | null>) {
      s.indicator = a.payload;
    },
    // Evidence clicked: the pitch jumps there and lights the players.
    focusEvent(s, a: PayloadAction<{ t: number; eventId: string; players: string[] }>) {
      s.t = clamp(a.payload.t);
      s.playing = false;
      s.until = null;
      s.focusEventId = a.payload.eventId;
      s.highlighted = a.payload.players;
    },
  },
});

export const actions = playback.actions;
