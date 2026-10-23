import type { IndicatorRow, IndicatorValue } from "../api";
import { teamName } from "../api";
import { useAppDispatch } from "../store";
import { actions, type IndicatorPick } from "../store/playback";

/** ONLY three indicators: control (each team), openness, momentum. */
export function Indicators({
  row,
  home,
  away,
  persona,
}: {
  row: IndicatorRow | undefined;
  home: string;
  away: string;
  persona: string;
}) {
  const dispatch = useAppDispatch();
  const items: IndicatorPick[] = [
    { metric: "control_index", key: `control_index.${home}`, label: `${teamName(home)} control` },
    { metric: "control_index", key: `control_index.${away}`, label: `${teamName(away)} control` },
    { metric: "openness_index", key: "openness_index", label: "Openness" },
    { metric: "momentum", key: "momentum", label: `Momentum (+ = ${teamName(home)})` },
  ];
  return (
    <aside className="indicators" aria-label="indicators">
      {items.map((it) => {
        const v = row?.[it.key] as IndicatorValue | null | undefined;
        return (
          <button
            key={it.key}
            className="indicator"
            onClick={() => dispatch(actions.openIndicator(it))}
            data-testid={`indicator-${it.key}`}
          >
            <span className="label">{it.label}</span>
            <span className="value">{v ? fmt(it.metric, v.value, persona) : "–"}</span>
          </button>
        );
      })}
    </aside>
  );
}

function fmt(metric: string, v: number, persona: string): string {
  if (persona === "casual" && metric !== "momentum") return `${Math.round(v * 100)}%`;
  return v.toFixed(2);
}
