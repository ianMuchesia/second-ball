import { lazy, Suspense, useMemo } from "react";
import { Controls } from "../components/Controls";
import { MatchCentre } from "../components/MatchCentre";
import { MomentCard } from "../components/MomentCard";
import { Pitch } from "../components/Pitch";
import { ScoreBug } from "../components/ScoreBug";
import { Timeline } from "../components/Timeline";
import { useRun } from "../hooks/useRun";
import { useAppDispatch, useAppSelector } from "../store";
import { actions } from "../store/playback";
import {
  evidenceOf,
  feedOf,
  type FeedItem,
  lineupOf,
  makeViewSelector,
  markersOf,
  type Marker,
  onAir,
} from "../store/selectors";
import { useEventsQuery, useProducerQuery, useRunQuery } from "../store/serverApi";
import { useTicker } from "../useTicker";

// Opened on demand: separate chunks.
const EvidenceDrawer = lazy(() => import("../components/Evidence"));
const IndicatorModal = lazy(() => import("../components/IndicatorModal"));

export default function BroadcastPage() {
  const run = useRun();
  const { data } = useRunQuery(run);
  const { data: events = [] } = useEventsQuery(run);
  // The producer's decisions (pulled lines, approved held lines) decide what airs.
  const { data: producer } = useProducerQuery(run);
  const dispatch = useAppDispatch();
  const pb = useAppSelector((s) => s.playback);
  const end = events.length ? events[events.length - 1].t : 0;
  useTicker(end);

  const byId = useMemo(() => new Map(events.map((e) => [e.event_id, e])), [events]);
  const airable = useMemo(() => (data ? onAir(data, producer?.audit) : []), [data, producer]);
  const lineup = useMemo(() => (data ? lineupOf(data) : new Map()), [data]);
  const feed = useMemo(
    () => (data ? feedOf(data, events, byId, lineup, pb.persona, producer?.audit) : []),
    [data, events, byId, lineup, pb.persona, producer],
  );
  const selectView = useMemo(makeViewSelector, []);
  const view = useAppSelector((s) => (data ? selectView(s, data, events, airable) : null));
  const markers = useMemo(() => (data ? markersOf(data, events) : []), [data, events]);
  const momentumScale = useMemo(
    () =>
      Math.max(
        1e-6,
        ...(data?.indicators ?? []).map((r) => Math.abs((r.momentum as { value: number } | null)?.value ?? 0)),
      ),
    [data],
  );
  if (!data || !view) return null;

  const { match } = data;
  const moment = data.moments.find((m) => m.moment_id === pb.momentId);
  const current = feed.find((i) => i.overlay.overlay_id === view.line?.overlay_id);

  const narrationFor = (momentId: string) =>
    data.narrations.find((n) => n.overlay_id === `${momentId}-${pb.persona}`) ??
    data.narrations.find((n) => n.overlay_id.startsWith(momentId));
  const evidenceFor = (momentId: string) => {
    const m = data.moments.find((x) => x.moment_id === momentId);
    return m ? evidenceOf(m, narrationFor(momentId), events, byId, lineup) : null;
  };
  const openEvidence = (momentId: string) => {
    const ev = evidenceFor(momentId);
    dispatch(
      actions.openDrawer({
        momentId,
        players: ev?.players ?? [],
        eventId: ev?.ids[ev.ids.length - 1] ?? null,
      }),
    );
  };
  const onJump = (m: Marker | null, t: number) => {
    dispatch(actions.jump({ t, end }));
    dispatch(actions.selectMoment(m?.momentId ?? null));
  };
  const openFeed = (item: FeedItem) => {
    dispatch(actions.jump({ t: item.overlay.t, end }));
    if (item.moment) openEvidence(item.moment.moment_id);
  };

  return (
    <main className="broadcast">
      <div className="stage">
        <div className="screen">
          <Pitch
            event={view.event}
            frame={view.frame}
            path={view.path}
            homeTeam={match.home_team}
            lineup={lineup}
            highlighted={new Set(pb.highlighted)}
          />
          <ScoreBug
            events={events}
            upto={view.index}
            home={match.home_team}
            away={match.away_team}
            scripted={match.mode === "scenario"}
          />
          {view.card && <div className="stat-card">{view.card.text.en}</div>}
          <MomentCard
            item={current}
            lang={pb.lang}
            onEvidence={() => view.lineMoment && openEvidence(view.lineMoment)}
          />
        </div>
        <MatchCentre
          feed={feed}
          t={pb.t}
          row={view.row}
          home={match.home_team}
          away={match.away_team}
          momentumScale={momentumScale}
          onOpen={openFeed}
        />
      </div>
      <Controls languages={data.meta.languages} end={end} />
      <Timeline events={events} end={end} t={pb.t} markers={markers} onJump={onJump} />
      {moment && !pb.drawerOpen && (
        <div className="selected">
          <span>
            {moment.kind.replace(/_/g, " ")} · {moment.clock.minute}'
          </span>
          <button onClick={() => openEvidence(moment.moment_id)} data-testid="evidence-open">
            Evidence ›
          </button>
        </div>
      )}
      <Suspense fallback={null}>
        {pb.drawerOpen && moment && (
          <EvidenceDrawer
            moment={moment}
            overlays={data.overlays}
            narrations={data.narrations}
            persona={pb.persona}
            evidence={evidenceFor(moment.moment_id)!}
            lineup={lineup}
          />
        )}
        {pb.indicator && <IndicatorModal item={pb.indicator} row={view.row} />}
      </Suspense>
    </main>
  );
}
