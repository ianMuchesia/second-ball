import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { Controls } from "./components/Controls";
import { Crest } from "./components/Crest";
import { MatchCentre } from "./components/MatchCentre";
import { ScoreBug } from "./components/ScoreBug";
import { Timeline } from "./components/Timeline";
import {
  clockAt,
  describe,
  type KeyMoment,
  keyMoments,
  loadMatch,
  statsAt,
  teamCode,
  teamName,
  type Timeline as TL,
} from "./match";
import { type CameraMode, Stage, type Tick } from "./three/Stage";

interface Listed {
  file: string;
  label: string;
  note: string;
}

const REPLAY_LEAD = 9; // match seconds of build-up before a replayed moment

export function App() {
  const [list, setList] = useState<Listed[]>([]);
  const [file, setFile] = useState<string | null>(null);
  const [tl, setTl] = useState<TL | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState<Tick>({ t: 0, index: 0, playing: false, holder: null, goalAt: null });
  const [speed, setSpeed] = useState(4);
  const [camera, setCamera] = useState<CameraMode>("broadcast");
  const canvas = useRef<HTMLCanvasElement>(null);
  const stage = useRef<Stage | null>(null);
  const [kits, setKits] = useState<Stage["kits"] | null>(null);

  useEffect(() => {
    fetch("/matches/index.json")
      .then((r) => r.json())
      .then((xs: Listed[]) => {
        setList(xs);
        const linked = new URLSearchParams(location.search).get("match");
        setFile(xs.find((x) => x.file === linked)?.file ?? xs[0]?.file ?? null);
      })
      .catch(() => setError("No match list at /matches/index.json"));
  }, []);

  useEffect(() => {
    if (!file) return;
    setTl(null);
    loadMatch(`/matches/${file}`)
      .then(setTl)
      .catch((e) => setError(String(e)));
  }, [file]);

  // One Stage per match; the canvas outlives it.
  useEffect(() => {
    if (!tl || !canvas.current) return;
    let s: Stage | null = null;
    let cancelled = false;
    // The boards are drawn in Barlow: wait for it, then for the rig.
    document.fonts
      .load('800 64px "Barlow Condensed"')
      .catch(() => undefined)
      .then(() => (cancelled || !canvas.current ? null : Stage.create(canvas.current, tl)))
      .then((made) => {
        if (!made) return;
        if (cancelled) return made.dispose();
        s = made;
        s.setSpeed(speed);
        s.setCamera(camera);
        s.onTick = setTick;
        stage.current = s;
        setKits(s.kits);
        if (new URLSearchParams(location.search).has("debug")) (window as unknown as { stage: Stage }).stage = s;
      })
      .catch((e) => setError(String(e)));
    return () => {
      cancelled = true;
      setKits(null);
      s?.dispose();
      stage.current = null;
    };
    // speed and camera are pushed to the live stage by their own handlers
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tl]);

  const moments = useMemo(() => (tl ? keyMoments(tl) : []), [tl]);
  const stats = useMemo(() => (tl ? statsAt(tl, tick.index) : null), [tl, tick.index]);
  const line = useMemo(() => (tl ? describe(tl, tick.index) : null), [tl, tick.index]);

  const play = () => stage.current?.play(!stage.current.playing);
  const jump = (d: number) => stage.current && stage.current.seek(stage.current.t + d);
  const changeSpeed = (s: number) => {
    setSpeed(s);
    stage.current?.setSpeed(s);
  };
  const changeCamera = (c: CameraMode) => {
    setCamera(c);
    stage.current?.setCamera(c);
  };
  // A replay goes back to the build-up and plays it at real speed, like Second Ball's "Why?".
  const replay = (m: KeyMoment) => {
    const s = stage.current;
    if (!s) return;
    s.seek(Math.max(0, m.t - REPLAY_LEAD));
    changeSpeed(1);
    s.play(true);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("select, input")) return;
      if (e.code === "Space") {
        e.preventDefault();
        play();
      } else if (e.code === "ArrowLeft") jump(-10);
      else if (e.code === "ArrowRight") jump(10);
      else if (e.key >= "1" && e.key <= "4") changeCamera((["broadcast", "tactical", "behind", "free"] as const)[+e.key - 1]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const goal = tl && tick.goalAt !== null ? tl.events[tick.goalAt] : null;
  const scorer = goal ? tl!.lineup.get(goal.player) : null;
  const holder = tick.holder && tl ? tl.lineup.get(tick.holder) : null;

  return (
    <div
      className="app"
      style={
        kits
          ? ({ "--kit-home": kits.home.shirt, "--kit-home-2": kits.home.trim, "--kit-away": kits.away.shirt, "--kit-away-2": kits.away.trim } as CSSProperties)
          : undefined
      }
    >
      <header className="masthead">
        <div className="brand">
          <span className="wordmark">
            Second Ball <em>3D</em>
          </span>
          <span className="sub">Match viewer · synthetic data</span>
        </div>
        {tl && (
          <div className="fixture">
            <span className="sides">
              <Crest team={tl.home} side="home" />
              {teamName(tl.home)}
              <span className="v">v</span>
              {teamName(tl.away)}
              <Crest team={tl.away} side="away" />
            </span>
            <small>
              {tl.meta.venue} · {tl.meta.competition} · {tl.meta.weather}
            </small>
          </div>
        )}
        <label className="picker">
          Match
          <select value={file ?? ""} onChange={(e) => setFile(e.target.value)}>
            {list.map((m) => (
              <option key={m.file} value={m.file}>
                {m.label} ({m.note})
              </option>
            ))}
          </select>
        </label>
      </header>

      <main className="stage">
        <div className="screen">
          <canvas ref={canvas} />
          {(!tl || !kits) && <div className="loading">{error ?? "Warming up the floodlights…"}</div>}
          {tl && (
            <>
              <ScoreBug tl={tl} index={tick.index} clock={clockAt(tl, tick.index, tick.t)} />
              {holder && (
                <div className="possession">
                  <span className={`kit ${holder.team_id === tl.home ? "home" : "away"}`} />
                  {teamCode(holder.team_id)} on the ball
                </div>
              )}
              <div className="attack-dir">{teamCode(tl.home)} attack →</div>
              {goal && scorer && (
                <div className="goal-flash" key={goal.id}>
                  <span className="word">Goal</span>
                  <span className="who">
                    {scorer.name} · {teamName(goal.team)}
                  </span>
                </div>
              )}
              {holder && !goal && (
                <div className={`player-card ${holder.team_id === tl.home ? "home" : "away"}`}>
                  <span className="pos">{holder.position}</span>
                  <span className="num">{holder.shirt_number}</span>
                  <span className="name">
                    {holder.name.split(" ")[0][0]}. {holder.name.split(" ").slice(-1)[0]}
                  </span>
                  {holder.style && <span className="style">{holder.style}</span>}
                </div>
              )}
              {line && !goal && (
                <div className={`lower-third${line.hot ? " hot" : ""}`}>
                  <span className="strip">{line.kind}</span>
                  <span className="headline">{line.text}</span>
                </div>
              )}
              {!tick.playing && tick.t === 0 && (
                <button className="kickoff" onClick={play}>
                  Kick off ›
                </button>
              )}
            </>
          )}
        </div>
        {tl && stats && <MatchCentre tl={tl} moments={moments} stats={stats} index={tick.index} onReplay={replay} />}
      </main>

      {tl && (
        <>
          <Controls
            playing={tick.playing}
            speed={speed}
            camera={camera}
            onPlay={play}
            onSpeed={changeSpeed}
            onJump={jump}
            onCamera={changeCamera}
          />
          <Timeline tl={tl} t={tick.t} moments={moments} onJump={(t, m) => (m ? replay(m) : stage.current?.seek(t))} />
          <p className="small foot">
            Space play/pause · ← → 10 s · 1–4 cameras · Free camera: drag to orbit, scroll to zoom. Every position comes
            from the engine's freeze frames; motion between them is interpolated.
          </p>
        </>
      )}
    </div>
  );
}
