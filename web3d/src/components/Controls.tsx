import type { CameraMode } from "../three/Stage";

export const SPEEDS = [1, 2, 4, 10];
export const CAMERAS: { id: CameraMode; label: string; key: string }[] = [
  { id: "broadcast", label: "Broadcast", key: "1" },
  { id: "tactical", label: "Tactical", key: "2" },
  { id: "behind", label: "Behind", key: "3" },
  { id: "free", label: "Free", key: "4" },
];

/** Play/pause, speed, jump and camera: the Second Ball control row. */
export function Controls(p: {
  playing: boolean;
  speed: number;
  camera: CameraMode;
  onPlay: () => void;
  onSpeed: (s: number) => void;
  onJump: (d: number) => void;
  onCamera: (c: CameraMode) => void;
}) {
  return (
    <div className="controls">
      <button className="play" onClick={p.onPlay} title="Space">
        {p.playing ? "Pause" : "Play"}
      </button>
      <div className="group" role="group" aria-label="Speed">
        {SPEEDS.map((s) => (
          <button key={s} className={s === p.speed ? "on" : ""} onClick={() => p.onSpeed(s)}>
            {s}x
          </button>
        ))}
      </div>
      <button onClick={() => p.onJump(-30)} title="Left arrow">
        −30 s
      </button>
      <button onClick={() => p.onJump(30)} title="Right arrow">
        +30 s
      </button>
      <span className="spacer" />
      <span className="label">Camera</span>
      <div className="group" role="group" aria-label="Camera">
        {CAMERAS.map((c) => (
          <button key={c.id} className={c.id === p.camera ? "on" : ""} onClick={() => p.onCamera(c.id)} title={`Key ${c.key}`}>
            {c.label}
          </button>
        ))}
      </div>
    </div>
  );
}
