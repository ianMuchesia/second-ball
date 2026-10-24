import { useCallback, useMemo, useRef, useState } from "react";
import type { Match, ScreenEvent } from "../api";
import { store } from "../store";
import { fromRun } from "../three3d/match";
import { type Clock, Stage } from "../three3d/Stage";

/** The 3D pitch (loaded on demand: three.js and the player model are their
 * own chunk). It follows the screen's clock straight from the store each
 * animation frame, so the score bug, lower third and evidence stay the 2D
 * screen's own, and both views always show the same instant. Paused, or at a
 * clicked evidence event, players and ball sit exactly where the engine put
 * them; only motion between events is interpolated. */
export default function Pitch3D({ match, events }: { match: Match; events: ScreenEvent[] }) {
  const tl = useMemo(() => fromRun(match, events), [match, events]);
  const live = useRef<{ stage: Stage | null; gone: boolean } | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The canvas's lifecycle is its ref: created when React mounts it, disposed
  // when React lets it go (called with null). No effect needed.
  const attach = useCallback(
    (canvas: HTMLCanvasElement | null) => {
      if (live.current) {
        live.current.gone = true;
        live.current.stage?.dispose();
        live.current = null;
      }
      if (!canvas) return;
      const mine = { stage: null as Stage | null, gone: false };
      live.current = mine;
      const clock = (): Clock => {
        const p = store.getState().playback;
        return { t: p.t, playing: p.playing, focusEventId: p.focusEventId };
      };
      // The boards are drawn in Barlow: wait for it, then for the rig.
      document.fonts
        .load('800 64px "Barlow Condensed"')
        .catch(() => undefined)
        .then(() => (mine.gone ? null : Stage.create(canvas, tl, clock)))
        .then((stage) => {
          if (!stage) return;
          if (mine.gone) return stage.dispose();
          mine.stage = stage;
          (window as unknown as { stage3d?: Stage }).stage3d = stage; // checks (e2e)
          setReady(true);
        })
        .catch((e) => setError(String(e)));
    },
    [tl],
  );

  return (
    <div className="pitch-scene three" data-testid="pitch-3d" data-ready={ready ? "yes" : "no"}>
      <canvas ref={attach} aria-label="3D pitch" />
      {!ready && <div className="loading">{error ?? "Warming up the floodlights…"}</div>}
      <p className="interpolated" data-testid="interpolated-note">
        Motion between events is interpolated; positions at events come from the engine.
      </p>
    </div>
  );
}
