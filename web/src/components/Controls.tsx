import { useAppDispatch, useAppSelector } from "../store";
import { actions } from "../store/playback";

const SPEEDS = [1, 4, 10];
/** Play/pause, speed and jump. Who is watching: ViewerBar. */
export function Controls({ end }: { end: number }) {
  const dispatch = useAppDispatch();
  const { playing, speed, t } = useAppSelector((s) => s.playback);
  return (
    <div className="controls">
      <button onClick={() => dispatch(actions.setPlaying(!playing))} data-testid="play">
        {playing ? "Pause" : "Play"}
      </button>
      {SPEEDS.map((s) => (
        <button key={s} className={s === speed ? "on" : ""} onClick={() => dispatch(actions.setSpeed(s))}>
          {s}x
        </button>
      ))}
      <button onClick={() => dispatch(actions.jump({ t: t - 30, end }))}>−30 s</button>
      <button onClick={() => dispatch(actions.jump({ t: t + 30, end }))}>+30 s</button>
    </div>
  );
}
