import { useState } from "react";
import type { MetricInfo, MetricValueAt } from "../api";
import { pct, range, teamName } from "../api";
import { useRun } from "../hooks/useRun";
import { useAppSelector } from "../store";
import { useMetricAtQuery, useMetricQuery } from "../store/serverApi";
import { teamCode } from "../theme";
import { EventsModal } from "./EventsModal";

/** A registry metric over the match so far: the persona's name for it, each
 * team's value (an analyst also gets units, Wilson 95% ranges and the event
 * count), its plain definition, and the events behind it. */
export function MetricRow({
  name,
  t,
  pinned = false,
}: {
  name: string;
  t: number; // match seconds, already rounded to a minute by the caller
  pinned?: boolean;
}) {
  const run = useRun();
  const persona = useAppSelector((s) => s.profile.persona);
  const { data: info } = useMetricQuery(name);
  const { data } = useMetricAtQuery({ run, name, t });
  const [open, setOpen] = useState(false);
  if (!info) return null;
  const analyst = persona === "analyst";
  const label = analyst ? info.display_name.analyst : (info.display_name.casual ?? info.display_name.analyst);
  const values = Object.entries(data?.values ?? {});
  const ids = values.flatMap(([, v]) => v?.evidence_event_ids ?? []).slice(-8);
  const total = values.reduce((n, [, v]) => n + (v?.events ?? 0), 0);
  return (
    <div className={pinned ? "metric-row pinned" : "metric-row"} data-testid={pinned ? "pinned-metric" : `metric-${name}`}>
      <span className="metric-name">
        {pinned && <span className="pin">Pinned</span>}
        {label}
      </span>
      <span className="metric-values">
        {values.length === 0 || values.every(([, v]) => !v) ? (
          <span className="stat-none">not enough play yet</span>
        ) : (
          values.map(([owner, v]) => (
            <span key={owner} className="metric-value">
              {owner !== "match" && <b>{teamCode(teamName(owner))}</b>} {v ? shown(v, info, analyst) : "–"}
            </span>
          ))
        )}
      </span>
      <span className="metric-meaning">{info.definition.split(/(?<=[.:;])\s/)[0]}</span>
      <button className="metric-more" onClick={() => setOpen(true)} data-testid="metric-evidence">
        Evidence ›
      </button>
      {open && (
        <EventsModal
          title={label}
          definition={info.definition}
          note={`Unit: ${info.unit}. Computed by ${info.formula} over the match so far.`}
          ids={ids}
          total={total}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

function shown(v: MetricValueAt, info: MetricInfo, analyst: boolean): string {
  const share = info.unit.startsWith("share");
  if (!analyst) return share ? pct(v.value) : Number.isInteger(v.value) ? String(v.value) : v.value.toFixed(1);
  if (share) {
    const n = v.numerator !== null && v.denominator ? ` · ${Math.round(v.numerator)}/${Math.round(v.denominator)}` : "";
    return `${pct(v.value)}${v.interval ? ` (95%: ${range(v.interval)})` : ""}${n}`;
  }
  const unit = info.unit === "count" ? "" : ` ${info.unit}`;
  return `${Number.isInteger(v.value) ? v.value : v.value.toFixed(2)}${unit}`;
}
