// Every call to the broadcast API, through RTK Query: cached per argument,
// loading/error state included, and the producer view refetched after an
// approve, reject or test injection (tag "Producer").
import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";
import type {
  AuditRow,
  Injection,
  Meta,
  MetricInfo,
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
    evidence: b.query<ScreenEvent[], { run: string; ids: string[] }>({
      query: ({ run, ids }) => ({ url: `runs/${run}/evidence`, params: { ids: ids.join(",") } }),
    }),
    metric: b.query<MetricInfo, string>({ query: (name) => `registry/${name}` }),
    rule: b.query<Rule, string>({ query: (kind) => `moment-rules/${kind}` }),
    producer: b.query<ProducerView, string>({
      query: (run) => `runs/${run}/producer`,
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
  useEvidenceQuery,
  useMetricQuery,
  useRuleQuery,
  useProducerQuery,
  useActMutation,
  useInjectMutation,
} = serverApi;
