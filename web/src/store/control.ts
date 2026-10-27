// The control room: whether lines wait for a producer before they air, and
// the decisions made in this browser. A public server takes no writes, so a
// visitor's approvals stay here (never sent anywhere) and change only their
// own screen; locally they go to the server's audit log instead.
import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { AuditRow } from "../api";

export interface Control {
  gate: boolean; // approve before air: nothing airs until a producer approves it
  gateTouched: boolean; // the viewer chose: opening the control room no longer switches it on
  local: AuditRow[]; // decisions kept in this browser
}

const initialState: Control = { gate: false, gateTouched: false, local: [] };

export const control = createSlice({
  name: "control",
  initialState,
  reducers: {
    setGate(s, a: PayloadAction<boolean>) {
      s.gate = a.payload;
      s.gateTouched = true;
    },
    // A first visit to the control room: lines wait for the producer.
    openRoom(s) {
      if (!s.gateTouched) {
        s.gate = true;
        s.gateTouched = true;
      }
    },
    decide(s, a: PayloadAction<AuditRow>) {
      s.local.push(a.payload);
    },
  },
});

export const controlActions = control.actions;
