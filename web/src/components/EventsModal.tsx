import type { ScreenEvent } from "../api";
import { plural } from "../api";
import { useRun } from "../hooks/useRun";
import { useAppDispatch } from "../store";
import { actions } from "../store/playback";
import { useEvidenceQuery } from "../store/serverApi";

/** The events behind a number, latest first; click one to see that instant
 * on the pitch. Used by the player card and the pinned stat. */
export function EventsModal({
  title,
  definition,
  note,
  ids,
  total,
  onClose,
}: {
  title: string;
  definition: string;
  note?: string;
  ids: string[]; // the events to list (the latest few)
  total: number; // how many events stand behind the number
  onClose: () => void;
}) {
  const dispatch = useAppDispatch();
  const { data: events = [] } = useEvidenceQuery({ run: useRun(), ids }, { skip: ids.length === 0 });
  const jump = (e: ScreenEvent) =>
    dispatch(actions.focusEvent({ t: e.t, eventId: e.event_id, players: [e.player_id] }));
  return (
    <div className="modal" role="dialog" aria-label={title} data-testid="events-modal">
      <header>
        <h3>{title}</h3>
        <button onClick={onClose} aria-label="close">
          ×
        </button>
      </header>
      <p className="definition">{definition}</p>
      {note && <p className="small">{note}</p>}
      <p className="small">
        Counted by code from {plural(total, "event")}
        {total > ids.length ? `; the latest ${ids.length} below` : ""}.
      </p>
      <ul className="events">
        {[...events].reverse().map((e) => (
          <li key={e.event_id}>
            <button onClick={() => jump(e)}>{e.words}</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
