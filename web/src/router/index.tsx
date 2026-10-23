// The router: each page is its own chunk, loaded when first visited.
import { createBrowserRouter } from "react-router-dom";
import RouteError from "../pages/RouteError";
import { routes } from "./routes";

export const router = createBrowserRouter([
  {
    path: routes.home,
    errorElement: <RouteError />,
    lazy: async () => ({ Component: (await import("../pages/RunsPage")).default }),
  },
  {
    path: routes.run,
    errorElement: <RouteError />,
    lazy: async () => ({ Component: (await import("../pages/RunLayout")).default }),
    children: [
      {
        index: true,
        lazy: async () => ({ Component: (await import("../pages/BroadcastPage")).default }),
      },
      {
        path: routes.producer,
        lazy: async () => ({ Component: (await import("../pages/ProducerPage")).default }),
      },
    ],
  },
  {
    path: "*",
    lazy: async () => ({ Component: (await import("../pages/NotFound")).default }),
  },
]);
