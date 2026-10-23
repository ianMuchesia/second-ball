import { useEffect } from "react";
import { useAppDispatch, useAppSelector } from "./store";
import { actions } from "./store/playback";

/** The one effect on the screen: the browser's animation frame moves the
 * playback clock while playing. Everything else is Redux state and RTK Query. */
export function useTicker(end: number) {
  const playing = useAppSelector((s) => s.playback.playing);
  const dispatch = useAppDispatch();
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last: number | null = null;
    const step = (now: number) => {
      if (last !== null) dispatch(actions.tick({ dt: (now - last) / 1000, end }));
      last = now;
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, end, dispatch]);
}
