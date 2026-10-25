import { lazy, Suspense, useMemo } from "react";
import { Controls } from "../components/Controls";
import { MatchCentre } from "../components/MatchCentre";
import { MomentCard } from "../components/MomentCard";
import { MetricRow } from "../components/PinnedMetric";
import { Pitch } from "../components/Pitch";
import { PlayerCard } from "../components/PlayerCard";
import { ScoreBug } from "../components/ScoreBug";
import { Timeline } from "../components/Timeline";
import { ViewerBar } from "../components/ViewerBar";
import { useRun } from "../hooks/useRun";
import { can3d } from "../device";
import { useAppDispatch, useAppSelector } from "../store";
import { actions } from "../store/playback";
import { profileActions } from "../store/profile";
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
import { useEventsQuery, useProducerQuery, useRunQuery, useTracksQuery } from "../store/serverApi";
import { goalLineAt, sampleAt, sceneAt, trackEnd } from "../tracks";
import { useTicker } from "../useTicker";

// Opened on demand: separate chunks.
const EvidenceDrawer = lazy(() => import("../components/Evidence"));
const IndicatorModal = lazy(() => import("../components/IndicatorModal"));
// three.js and the player model: only for viewers who switch to 3D.
const Pitch3D = lazy(() => import("../components/Pitch3D"));

export default function BroadcastPage() {
  const run = useRun();
  const { data } = useRunQuery(run);
  const { data: events = [] } = useEventsQuery(run);
  const { data: tracks } = useTracksQuery(run);
  // The producer's decisions (pulled lines, approved held lines) decide what airs.
  const { data: producer } = useProducerQuery({ run });
  const dispatch = useAppDispatch();
  const pb = useAppSelector((s) => s.playback);
  const me = useAppSelector((s) => s.profile);
  const lastT = events.length ? events[events.length - 1].t : 0;
  // With the engine's movement, play runs to the end of the track.
  const end = tracks && events.length ? Math.max(lastT, trackEnd(tracks, events)) : lastT;
  useTicker(end);

  const byId = useMemo(() => new Map(events.map((e) => [e.event_id, e])), [events]);
  const airable = useMemo(() => (data ? onAir(data, producer?.audit) : []), [data, producer]);
  const lineup = useMemo(() => (data ? lineupOf(data) : new Map()), [data]);
  const feed = useMemo(
    () =>
      data
        ? feedOf(data, byId, lineup, me.persona, producer?.audit, {
            favouriteClub: me.favouriteClub,
            followedPlayer: me.followedPlayer,
          })
        : [],
    [data, byId, lineup, me.persona, me.favouriteClub, me.followedPlayer, producer],
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
  const goalAt = useMemo(() => (tracks ? goalLineAt(tracks, events) : null), [tracks, events]);
  const scene = tracks && events.length ? sceneAt(tracks, sampleAt(tracks, events, pb.t, pb.focusEventId)) : null;
  // An analyst's evidence drawer is open by default on the line on air (until
  // closed for that moment); otherwise it opens when asked.
  const drawerMoment = pb.drawerOpen
    ? pb.momentId
    : me.persona === "analyst" && view.lineMoment && pb.drawerDismissed !== view.lineMoment
      ? view.lineMoment
      : null;
  const moment = data.moments.find((m) => m.moment_id === pb.momentId);
  const shownMoment = data.moments.find((m) => m.moment_id === drawerMoment);
  const current = feed.find((i) => i.overlay.overlay_id === view.line?.overlay_id);

  const narrationFor = (momentId: string) =>
    data.narrations.find((n) => n.overlay_id === `${momentId}-${me.persona}`) ??
    data.narrations.find((n) => n.overlay_id.startsWith(momentId));
  const evidenceFor = (momentId: string) => {
    const m = data.moments.find((x) => x.moment_id === momentId);
    return m ? evidenceOf(m, narrationFor(momentId), lineup) : null;
  };
  // The replay goes to the move's first action and plays it to its last.
  const openEvidence = (momentId: string) => {
    const ev = evidenceFor(momentId);
    const steps = (ev?.ids ?? []).map((id) => byId.get(id)).filter((e) => e !== undefined);
    const m = data.moments.find((x) => x.moment_id === momentId)!;
    dispatch(
      actions.openDrawer({
        momentId,
        players: ev?.players ?? [],
        move: ev?.ids ?? [],
        from: steps[0]?.t ?? m.t,
        to: steps[steps.length - 1]?.t ?? m.t,
      }),
    );
  };
  const onJump = (m: Marker | null, t: number) => {
    dispatch(actions.jump({ t, end }));
    dispatch(actions.selectMoment(m?.momentId ?? null));
  };
  const openFeed = (item: FeedItem) => {
    if (item.moment) openEvidence(item.moment.moment_id);
    else dispatch(actions.jump({ t: item.overlay.t, end }));
  };

  return (
    <main className="broadcast">
      <div className="stage">
        <div className="screen">
          {me.view === "3d" && can3d().ok ? (
            <Suspense fallback={<div className="pitch-scene three loading">Loading the 3D pitch…</div>}>
              <Pitch3D match={match} events={events} tracks={tracks ?? null} />
            </Suspense>
          ) : (
            <Pitch
              event={view.event}
              frame={view.frame}
              path={view.path}
              homeTeam={match.home_team}
              lineup={lineup}
              highlighted={new Set(pb.highlighted)}
              followed={me.followedPlayer}
            scene={scene}
              onPick={(id) => {
                dispatch(profileActions.follow(id));
                dispatch(actions.setPanel("player"));
              }}
            />
          )}
          <ScoreBug
            events={events}
            upto={view.index}
            home={match.home_team}
            away={match.away_team}
            scripted={match.mode === "scenario"}
            t={pb.t}
            goalAt={goalAt}
          />
          {/* Fewer overlays for a fan: stat cards are an analyst's. */}
          {view.card && me.persona === "analyst" && (
            <div className="stat-card analyst" data-testid="stat-card">
              {view.card.text[me.lang] ?? view.card.text.en}
            </div>
          )}
          <MomentCard
            item={current}
            lang={me.lang}
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
          player={
            me.followedPlayer && lineup.has(me.followedPlayer) ? (
              <PlayerCard
                playerId={me.followedPlayer}
                t={pb.t}
                homeTeam={match.home_team}
                recaps={data.player_recaps ?? []}
              />
            ) : null
          }
        />
      </div>
      {me.pinnedMetric && <MetricRow name={me.pinnedMetric} t={view.row?.t ?? 0} pinned />}
      <Controls end={end} />
      <ViewerBar
        languages={data.meta.languages}
        teams={[match.home_team, match.away_team]}
        lineup={match.lineups ?? []}
      />
      <Timeline events={events} end={end} t={pb.t} markers={markers} onJump={onJump} />
      {moment && !shownMoment && (
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
        {shownMoment && (
          <EvidenceDrawer
            moment={shownMoment}
            overlays={data.overlays}
            narrations={data.narrations}
            persona={me.persona}
            evidence={evidenceFor(shownMoment.moment_id)!}
            lineup={lineup}
          />
        )}
        {pb.indicator && <IndicatorModal item={pb.indicator} row={view.row} />}
      </Suspense>
    </main>
  );
}
