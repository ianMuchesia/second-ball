import type { IndicatorRow, IndicatorValue, ScreenEvent } from "../api";
import { useRun } from "../hooks/useRun";
import { useAppDispatch } from "../store";
import { actions, type IndicatorPick } from "../store/playback";
import { useEvidenceQuery, useMetricQuery } from "../store/serverApi";

/** An indicator's registered definition, its value now, and the latest events
 * behind it (click one to see it on the pitch). Loaded on demand (lazy). */
export default function IndicatorModal({
  item,
  row,
}: {
  item: IndicatorPick;
  row: IndicatorRow | undefined;
}) {
  const dispatch = useAppDispatch();
  const v = row?.[item.key] as IndicatorValue | null | undefined;
  const { data: info } = useMetricQuery(item.metric);
  const ids = (v?.evidence_event_ids ?? []).slice(-8);
  const { data: events = [] } = useEvidenceQuery({ run: useRun(), ids }, { skip: ids.length === 0 });
  const jump = (e: ScreenEvent) =>
    dispatch(actions.focusEvent({ t: e.t, eventId: e.event_id, players: [e.player_id] }));
  return (
    <div className="modal" role="dialog" aria-label={item.label}>
      <header>
        <h3>{item.label}</h3>
        <button onClick={() => dispatch(actions.openIndicator(null))} aria-label="close">
          ×
        </button>
      </header>
      {info && (
        <>
          <p className="definition" data-testid="definition">
            {info.definition}
          </p>
          <p className="small">
            Unit: {info.unit}. Computed by <code>{info.formula}</code> (registry: {info.name}).
          </p>
        </>
      )}
      <p>
        Now: <strong>{v ? v.value.toFixed(3) : "not enough play yet"}</strong>
      </p>
      {events.length > 0 && (
        <>
          <h4>Latest events behind it</h4>
          <ul className="events">
            {events.map((e) => (
              <li key={e.event_id}>
                <button onClick={() => jump(e)}>{e.words}</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
