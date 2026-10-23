import { configureStore } from "@reduxjs/toolkit";
import { useDispatch, useSelector } from "react-redux";
import { playback } from "./playback";
import { serverApi } from "./serverApi";

export const store = configureStore({
  reducer: { playback: playback.reducer, [serverApi.reducerPath]: serverApi.reducer },
  middleware: (getDefault) => getDefault().concat(serverApi.middleware),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

// Typed hooks: use these, never the plain useSelector/useDispatch.
export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
export const useTypedSelector = useAppSelector;
