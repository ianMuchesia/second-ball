// Generated from core/contracts by `make contracts`. Do not edit.

export interface Contracts {
  Insight?: Insight;
  Match?: Match;
  MatchEvent?: MatchEvent;
  MatchState?: MatchState;
  Moment?: Moment;
  Overlay?: Overlay;
}
export interface Insight {
  claim: string;
  confidence: number;
  /**
   * @minItems 1
   */
  evidence_event_ids: [string, ...string[]];
  mechanism: string;
  schema_version: 1;
}
export interface Match {
  away_team: string;
  competition: string;
  home_team: string;
  kickoff: string;
  match_id: string;
  schema_version: 1;
  seed: number;
  venue: string;
  weather: "dry" | "rain" | "wind" | "heat";
}
/**
 * SPADL convention: coordinates are from the acting team's view, so it attacks
 * towards x=105 and its own goal is at x=0.
 */
export interface MatchEvent {
  ball_speed_kmh: number | null;
  body_part: "foot" | "foot_left" | "foot_right" | "head" | "other";
  end_x: number;
  end_y: number;
  event_id: string;
  /**
   * @minItems 1
   * @maxItems 22
   */
  freeze_frame: [PlayerPosition, ...PlayerPosition[]];
  match_id: string;
  minute: number;
  outcome: "success" | "fail" | "offside" | "owngoal" | "yellow_card" | "red_card";
  period: number;
  player_id: string;
  possession_id: string;
  qualifiers: {
    [k: string]: string | number | boolean;
  };
  schema_version: 1;
  second: number;
  start_x: number;
  start_y: number;
  team_id: string;
  type:
    | "pass"
    | "cross"
    | "throw_in"
    | "freekick_crossed"
    | "freekick_short"
    | "corner_crossed"
    | "corner_short"
    | "take_on"
    | "foul"
    | "tackle"
    | "interception"
    | "shot"
    | "shot_penalty"
    | "shot_freekick"
    | "keeper_save"
    | "keeper_claim"
    | "keeper_punch"
    | "keeper_pick_up"
    | "clearance"
    | "bad_touch"
    | "non_action"
    | "dribble"
    | "goalkick";
  under_pressure: boolean;
}
/**
 * Facing angle in degrees: 0 points along +x, 90 along +y (anticlockwise).
 */
export interface PlayerPosition {
  facing_deg: number;
  player_id: string;
  team_id: string;
  x: number;
  y: number;
}
export interface MatchState {
  clock: Clock;
  metrics: {
    [k: string]: {
      [k: string]: MetricValue;
    };
  };
  schema_version: 1;
  score: Score;
}
export interface Clock {
  minute: number;
  period: number;
  second: number;
}
export interface MetricValue {
  /**
   * @minItems 1
   */
  evidence_event_ids: [string, ...string[]];
  value: number;
}
export interface Score {
  away: number;
  home: number;
}
export interface Moment {
  /**
   * @minItems 1
   */
  evidence_event_ids: [string, ...string[]];
  importance: number;
  kind: string;
  metrics_after: {
    [k: string]: MetricValue;
  };
  metrics_before: {
    [k: string]: MetricValue;
  };
  moment_id: string;
  schema_version: 1;
}
export interface Overlay {
  duration_ms: number;
  /**
   * @minItems 1
   */
  evidence_event_ids: [string, ...string[]];
  kind: string;
  match_id: string;
  overlay_id: string;
  priority: number;
  risk_tier: "low" | "medium" | "high";
  schema_version: 1;
  slot: string;
  status: "pending" | "approved" | "aired" | "expired";
  t_in: OverlayTime;
  text: {
    [k: string]: string;
  };
  values: {
    [k: string]: number;
  };
}
export interface OverlayTime {
  match: Clock;
  wall: string;
}
