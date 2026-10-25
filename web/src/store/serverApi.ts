// Every call to the broadcast API, through RTK Query: cached per argument,
// loading/error state included, and the producer view refetched after an
// approve, reject or test injection (tag "Producer").
import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";
import { parseTracks, type Tracks } from "../tracks";
import type {
  AuditRow,
  Injection,
  Meta,
  MetricAt,
  MetricInfo,
  MetricListItem,
  PlayerCard,
  ProducerView,
  Run,
  ScreenEvent,
} from "../api";

export interface Rule {
  kind: string;
  importance: number;
  thresholds: Record<string, unknown>;
  source: string;
}

export const serverApi = createApi({
  reducerPath: "server",
  baseQuery: fetchBaseQuery({ baseUrl: "/api" }),
  tagTypes: ["Producer"],
  endpoints: (b) => ({
    runs: b.query<Meta[], void>({ query: () => "runs" }),
    run: b.query<Run, string>({ query: (run) => `runs/${run}` }),
    events: b.query<ScreenEvent[], string>({ query: (run) => `runs/${run}/events` }),
    // The engine's 10 Hz movement (binary; null for runs without it).
    tracks: b.query<Tracks | null, string>({
      async queryFn(run) {
        const head = await fetch(`/api/runs/${run}/tracks`);
        if (!head.ok) return { data: null };
        const body = await fetch(`/api/runs/${run}/tracks.bin`);
        if (!body.ok) return { data: null };
        return { data: parseTracks(await head.json(), await body.arrayBuffer()) };
      },
    }),
    evidence: b.query<ScreenEvent[], { run: string; ids: string[] }>({
      query: ({ run, ids }) => ({ url: `runs/${run}/evidence`, params: { ids: ids.join(",") } }),
    }),
    metric: b.query<MetricInfo, string>({ query: (name) => `registry/${name}` }),
    metrics: b.query<MetricListItem[], void>({ query: () => "registry" }),
    // A registry metric over the match so far at match second t.
    metricAt: b.query<MetricAt, { run: string; name: string; t: number }>({
      query: ({ run, name, t }) => ({ url: `runs/${run}/metrics/${name}`, params: { t } }),
    }),
    playerCard: b.query<PlayerCard, { run: string; player: string }>({
      query: ({ run, player }) => `runs/${run}/players/${encodeURIComponent(player)}`,
    }),
    rule: b.query<Rule, string>({ query: (kind) => `moment-rules/${kind}` }),
    producer: b.query<ProducerView, { run: string; favourite?: string | null }>({
      query: ({ run, favourite }) => ({
        url: `runs/${run}/producer`,
        params: favourite ? { favourite } : {},
      }),
      providesTags: ["Producer"],
    }),
    act: b.mutation<
      AuditRow,
      { run: string; overlayId: string; action: "approve" | "reject"; who: string; reason: string }
    >({
      query: ({ run, overlayId, ...body }) => ({
        url: `runs/${run}/producer/${encodeURIComponent(overlayId)}`,
        method: "POST",
        body,
      }),
      invalidatesTags: ["Producer"],
    }),
    inject: b.mutation<Injection, { run: string; who: string }>({
      query: ({ run, who }) => ({ url: `runs/${run}/inject-test-error`, method: "POST", body: { who } }),
      invalidatesTags: ["Producer"],
    }),
  }),
});

export const {
  useRunsQuery,
  useRunQuery,
  useEventsQuery,
  useTracksQuery,
  useEvidenceQuery,
  useMetricQuery,
  useMetricsQuery,
  useMetricAtQuery,
  usePlayerCardQuery,
  useRuleQuery,
  useProducerQuery,
  useActMutation,
  useInjectMutation,
} = serverApi;
