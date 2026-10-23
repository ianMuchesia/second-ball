import type { IndicatorRow, IndicatorValue } from "../api";
import { teamName } from "../api";
import { useAppDispatch, useAppSelector } from "../store";
import { actions, type IndicatorPick } from "../store/playback";
import type { FeedItem } from "../store/selectors";
import { useMetricQuery } from "../store/serverApi";
import { teamCode } from "../theme";
import { kindLabel } from "./MomentCard";

/** The right column: verified key moments so far, and the three stats. */
export function MatchCentre(props: {
  feed: FeedItem[];
  t: number;
  row: IndicatorRow | undefined;
  home: string;
  away: string;
  momentumScale: number;
  onOpen: (item: FeedItem) => void;
}) {
  const dispatch = useAppDispatch();
  const panel = useAppSelector((s) => s.playback.panel);
  return (
    <aside className="centre">
      <nav className="centre-tabs" role="tablist">
        <button role="tab" aria-selected={panel === "moments"} className={panel === "moments" ? "on" : ""} onClick={() => dispatch(actions.setPanel("moments"))}>
          Key moments
        </button>
        <button role="tab" aria-selected={panel === "stats"} className={panel === "stats" ? "on" : ""} onClick={() => dispatch(actions.setPanel("stats"))} data-testid="tab-stats">
          Match stats
        </button>
      </nav>
      {panel === "moments" ? <Moments {...props} /> : <Stats {...props} />}
    </aside>
  );
}

function Moments({ feed, t, onOpen }: { feed: FeedItem[]; t: number; onOpen: (i: FeedItem) => void }) {
  const sofar = feed.filter((i) => i.overlay.t <= t).reverse();
  if (!sofar.length) return <p className="empty">No key moment yet. Lines appear here once the Verifier passes them.</p>;
  return (
    <ol className="feed" data-testid="feed">
      {sofar.map((i) => (
        <li key={i.overlay.overlay_id}>
          <button onClick={() => onOpen(i)}>
            <span className="minute">{i.overlay.t_in.match.minute}'</span>
            <span className="body">
              <span className="kind">
                {kindLabel(i.overlay.kind)}
                <span className={i.narration?.fallback ? "status template" : "status verified"}>
                  {i.narration?.fallback ? "Template" : "✓ Verified"}
                </span>
              </span>
              <span className="text">{i.overlay.text.en}</span>
              <span className="facts">
                {i.linkedEvents} events · {i.players.length} players · {i.metrics} metrics
                {i.narration && ` · ${i.narration.latency_s.toFixed(1)} s`}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function Stats({
  row,
  home,
  away,
  momentumScale,
}: {
  row: IndicatorRow | undefined;
  home: string;
  away: string;
  momentumScale: number;
}) {
  const persona = useAppSelector((s) => s.playback.persona);
  const dispatch = useAppDispatch();
  const get = (k: string) => (row?.[k] as IndicatorValue | null | undefined)?.value;
  const open = (pick: IndicatorPick) => dispatch(actions.openIndicator(pick));
  const minute = row?.minute ?? 0;
  const ch = get(`control_index.${home}`);
  const ca = get(`control_index.${away}`);
  const op = get("openness_index");
  const mo = get("momentum");
  const H = teamCode(teamName(home));
  const A = teamCode(teamName(away));
  return (
    <div className="stats" data-testid="stats">
      <Stat metric="control_index" onOpen={() => open({ metric: "control_index", key: `control_index.${home}`, label: "Control" })} early={minute < 10 ? `Warming up: ${minute} of 10 minutes of play so far` : null}>
        <Split left={ch} right={ca} leftLabel={H} rightLabel={A} />
      </Stat>
      <Stat metric="openness_index" onOpen={() => open({ metric: "openness_index", key: "openness_index", label: "Openness" })} early={minute < 10 ? `Warming up: ${minute} of 10 minutes of play so far` : null}>
        <Gauge value={op} />
      </Stat>
      <Stat metric="momentum" onOpen={() => open({ metric: "momentum", key: "momentum", label: "Momentum" })} early={null}>
        <Centre value={mo} scale={momentumScale} left={H} right={A} showValue={persona === "analyst"} />
      </Stat>
    </div>
  );
}

/** One stat: its name and plain meaning from the registry, the bar, and a tap
 * for the full definition and the events behind it. */
function Stat({
  metric,
  early,
  onOpen,
  children,
}: {
  metric: string;
  early: string | null;
  onOpen: () => void;
  children: React.ReactNode;
}) {
  const { data } = useMetricQuery(metric);
  const meaning = data?.definition.split(/(?<=[.:;])\s/)[0];
  return (
    <button className={early ? "stat warming" : "stat"} onClick={onOpen} data-testid={`stat-${metric}`}>
      <span className="stat-name">{data?.display_name.casual ?? data?.display_name.analyst ?? metric}</span>
      {early && <span className="stat-early">{early}</span>}
      {children}
      <span className="stat-meaning">{meaning}</span>
      <span className="stat-more">Definition and evidence ›</span>
    </button>
  );
}

const pct = (v: number) => `${Math.round(v * 100)}%`;

function Split({ left, right, leftLabel, rightLabel }: { left?: number; right?: number; leftLabel: string; rightLabel: string }) {
  if (left === undefined || right === undefined) return <span className="stat-none">not enough play yet</span>;
  const total = left + right || 1;
  return (
    <span className="split">
      <span className="num home">
        {leftLabel} {pct(left)}
      </span>
      <span className="bar">
        <span className="home" style={{ width: `${(100 * left) / total}%` }} />
        <span className="away" style={{ width: `${(100 * right) / total}%` }} />
      </span>
      <span className="num away">
        {pct(right)} {rightLabel}
      </span>
    </span>
  );
}

function Gauge({ value }: { value?: number }) {
  if (value === undefined) return <span className="stat-none">not enough play yet</span>;
  return (
    <span className="gauge">
      <span className="bar">
        <span style={{ width: pct(Math.max(0, Math.min(1, value))) }} />
      </span>
      <span className="num">{pct(value)}</span>
    </span>
  );
}

function Centre({
  value,
  scale,
  left,
  right,
  showValue,
}: {
  value?: number;
  scale: number;
  left: string;
  right: string;
  showValue: boolean;
}) {
  if (value === undefined) return <span className="stat-none">not enough play yet</span>;
  // Relative to the biggest swing in this match (computed from the run).
  const share = Math.max(-1, Math.min(1, value / (scale || 1)));
  const a = Math.abs(share);
  const how = a < 0.1 ? "" : a < 0.35 ? "slightly " : a < 0.7 ? "" : "strongly ";
  const who = a < 0.1 ? "Even" : `${share > 0 ? left : right} ${how}on top`;
  return (
    <span className="centre-bar">
      <span className="num">{left}</span>
      <span className="bar">
        <span className="mid" />
        <span
          className={share >= 0 ? "fill home" : "fill away"}
          style={share >= 0 ? { left: "50%", width: `${50 * share}%` } : { right: "50%", width: `${-50 * share}%` }}
        />
      </span>
      <span className="num">{right}</span>
      <span className="who">
        {who}
        {showValue && ` (${value.toFixed(3)})`}
      </span>
    </span>
  );
}
