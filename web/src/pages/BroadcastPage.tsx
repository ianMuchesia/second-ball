import { lazy, Suspense, useMemo } from "react";
import { Scoreboard, Timeline, LowerThird, type Marker } from "../components/Broadcast";
import { Controls } from "../components/Controls";
import { Indicators } from "../components/Indicators";
import { Pitch } from "../components/Pitch";
import { useRun } from "../hooks/useRun";
import { useAppDispatch, useAppSelector } from "../store";
import { actions } from "../store/playback";
import { lineupOf, makeViewSelector, markersOf } from "../store/selectors";
import { useEventsQuery, useRunQuery } from "../store/serverApi";
import { useTicker } from "../useTicker";

// Opened on demand: separate chunks.
const EvidenceDrawer = lazy(() => import("../components/Evidence"));
const IndicatorModal = lazy(() => import("../components/IndicatorModal"));

export default function BroadcastPage() {
  const run = useRun();
  const { data } = useRunQuery(run);
  const { data: events = [] } = useEventsQuery(run);
  const dispatch = useAppDispatch();
  const pb = useAppSelector((s) => s.playback);
  const end = events.length ? events[events.length - 1].t : 0;
  useTicker(end);

  const selectView = useMemo(makeViewSelector, []);
  const view = useAppSelector((s) => (data ? selectView(s, data, events) : null));
  const markers = useMemo(() => (data ? markersOf(data, events) : []), [data, events]);
  const lineup = useMemo(() => (data ? lineupOf(data) : new Map()), [data]);
  const byId = useMemo(() => new Map(events.map((e) => [e.event_id, e])), [events]);
  if (!data || !view) return null;

  const { match } = data;
  const moment = data.moments.find((m) => m.moment_id === pb.momentId);
  const narration = data.narrations.find((n) => n.overlay_id === view.line?.overlay_id);
  const openEvidence = (momentId: string) => {
    const m = data.moments.find((x) => x.moment_id === momentId);
    const evs = (m?.evidence_event_ids ?? []).map((id) => byId.get(id)).filter((e) => e !== undefined);
    dispatch(
      actions.openDrawer({
        momentId,
        players: [...new Set(evs.map((e) => e.player_id))],
        eventId: evs[0]?.event_id ?? null,
      }),
    );
  };
  const onJump = (m: Marker | null, t: number) => {
    dispatch(actions.jump({ t, end }));
    dispatch(actions.selectMoment(m?.momentId ?? null));
  };

  return (
    <main className="broadcast">
      <Scoreboard
        events={events}
        upto={view.index}
        home={match.home_team}
        away={match.away_team}
        scripted={match.mode === "scenario"}
      />
      <div className="stage">
        <div className="pitch-wrap">
          <Pitch
            event={view.frame}
            path={view.path}
            homeTeam={match.home_team}
            lineup={lineup}
            highlighted={new Set(pb.highlighted)}
          />
          {view.card && <div className="stat-card">{view.card.text.en}</div>}
          <LowerThird
            overlay={view.line}
            lang={pb.lang}
            narration={narration}
            onWhy={() => view.lineMoment && openEvidence(view.lineMoment)}
          />
        </div>
        <Indicators row={view.row} home={match.home_team} away={match.away_team} persona={pb.persona} />
      </div>
      <Controls languages={data.meta.languages} end={end} />
      <Timeline end={end} t={pb.t} markers={markers} onJump={onJump} />
      {moment && !pb.drawerOpen && (
        <div className="selected">
          {moment.kind.replace(/_/g, " ")} ({moment.clock.minute}')
          <button onClick={() => openEvidence(moment.moment_id)} data-testid="evidence-open">
            Evidence
          </button>
        </div>
      )}
      <Suspense fallback={null}>
        {pb.drawerOpen && moment && (
          <EvidenceDrawer moment={moment} overlays={data.overlays} narrations={data.narrations} persona={pb.persona} />
        )}
        {pb.indicator && <IndicatorModal item={pb.indicator} row={view.row} />}
      </Suspense>
    </main>
  );
}
