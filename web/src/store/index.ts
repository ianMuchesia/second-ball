import { configureStore } from "@reduxjs/toolkit";
import { useDispatch, useSelector } from "react-redux";
import { playback } from "./playback";
import { profile, saveProfile } from "./profile";
import { serverApi } from "./serverApi";

export const store = configureStore({
  reducer: {
    playback: playback.reducer,
    profile: profile.reducer,
    [serverApi.reducerPath]: serverApi.reducer,
  },
  // The movement track is typed arrays (big, read-only): kept out of the
  // dev-time serializable and immutability checks; everything else is checked.
  middleware: (getDefault) =>
    getDefault({
      serializableCheck: {
        ignoredPaths: [/^server\.queries\.tracks/],
        ignoredActionPaths: [/^payload\.(t|period|dead|v)$/],
      },
      immutableCheck: { ignoredPaths: [/^server\.queries\.tracks/] },
    }).concat(serverApi.middleware),
});

// The profile is saved whenever it changes (a store listener, not an effect).
let saved = store.getState().profile;
store.subscribe(() => {
  const now = store.getState().profile;
  if (now !== saved) saveProfile((saved = now));
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

// Typed hooks: use these, never the plain useSelector/useDispatch.
export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
export const useTypedSelector = useAppSelector;
