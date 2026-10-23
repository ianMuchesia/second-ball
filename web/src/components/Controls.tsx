import { useAppDispatch, useAppSelector } from "../store";
import { actions } from "../store/playback";

const SPEEDS = [1, 4, 10];
const LANGS: Record<string, string> = { en: "English", sw: "Kiswahili", fr: "Français", es: "Español", ar: "العربية" };

/** Play/pause, speed, jump, persona and language. */
export function Controls({ languages, end }: { languages: string[]; end: number }) {
  const dispatch = useAppDispatch();
  const { playing, speed, t, persona, lang } = useAppSelector((s) => s.playback);
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
      <span className="spacer" />
      <label>
        Viewer{" "}
        <select value={persona} onChange={(e) => dispatch(actions.setPersona(e.target.value as "casual" | "analyst"))}>
          <option value="casual">Fan</option>
          <option value="analyst">Analyst</option>
        </select>
      </label>
      <label>
        Language{" "}
        <select value={lang} onChange={(e) => dispatch(actions.setLang(e.target.value))}>
          {languages.map((l) => (
            <option key={l} value={l}>
              {LANGS[l] ?? l}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
