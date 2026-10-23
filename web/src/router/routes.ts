// Every path on the screen, in one place. Build links with these functions,
// never by hand.
export const routes = {
  home: "/",
  run: "/runs/:run",
  producer: "/runs/:run/producer",
} as const;

export const paths = {
  home: () => "/",
  run: (run: string) => `/runs/${encodeURIComponent(run)}`,
  producer: (run: string) => `/runs/${encodeURIComponent(run)}/producer`,
};

export const DEFAULT_RUN = "demo";
