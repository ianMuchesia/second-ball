import type { LineupPlayer } from "../api";
import { teamName } from "../api";
import { useAppDispatch, useAppSelector } from "../store";
import { type Persona, profileActions } from "../store/profile";
import { useMetricsQuery } from "../store/serverApi";

const LANGS: Record<string, string> = { en: "English", sw: "Kiswahili", fr: "Français", es: "Español", ar: "العربية" };

/** Who is watching: fan or analyst, language, favourite club (ranks its
 * moments first; the wording stays neutral), a player to follow, and a stat
 * to keep pinned. Saved for this viewer (store/profile.ts). */
export function ViewerBar({
  languages,
  teams,
  lineup,
}: {
  languages: string[];
  teams: [string, string];
  lineup: LineupPlayer[];
}) {
  const dispatch = useAppDispatch();
  const p = useAppSelector((s) => s.profile);
  const { data: metrics = [] } = useMetricsQuery();
  const label = (d: Record<string, string>) => (p.persona === "casual" ? (d.casual ?? d.analyst) : d.analyst);
  return (
    <div className="viewer-bar" data-testid="viewer-bar">
      <label>
        Viewer
        <select
          value={p.persona}
          onChange={(e) => dispatch(profileActions.setPersona(e.target.value as Persona))}
          data-testid="persona"
        >
          <option value="casual">Fan</option>
          <option value="analyst">Analyst</option>
        </select>
      </label>
      <label>
        Language
        <select value={p.lang} onChange={(e) => dispatch(profileActions.setLang(e.target.value))} data-testid="lang">
          {languages.map((l) => (
            <option key={l} value={l}>
              {LANGS[l] ?? l}
            </option>
          ))}
        </select>
      </label>
      <label title="Its moments come first within each level of importance. The wording stays neutral.">
        Favourite club
        <select
          value={p.favouriteClub ?? ""}
          onChange={(e) => dispatch(profileActions.setFavouriteClub(e.target.value || null))}
          data-testid="favourite"
        >
          <option value="">None</option>
          {teams.map((t) => (
            <option key={t} value={t}>
              {teamName(t)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Follow
        <select
          value={p.followedPlayer ?? ""}
          onChange={(e) => dispatch(profileActions.follow(e.target.value || null))}
          data-testid="follow"
        >
          <option value="">Nobody</option>
          {teams.map((t) => (
            <optgroup key={t} label={teamName(t)}>
              {lineup
                .filter((x) => x.team_id === t)
                .sort((a, b) => a.shirt_number - b.shirt_number)
                .map((x) => (
                  <option key={x.player_id} value={x.player_id}>
                    {x.shirt_number} {x.name} ({x.position})
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
      </label>
      <label>
        Pin a stat
        <select
          value={p.pinnedMetric ?? ""}
          onChange={(e) => dispatch(profileActions.pin(e.target.value || null))}
          data-testid="pin"
        >
          <option value="">None</option>
          {metrics.map((m) => (
            <option key={m.name} value={m.name}>
              {label(m.display_name)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
