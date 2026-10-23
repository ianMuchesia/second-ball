import { useParams } from "react-router-dom";
import { DEFAULT_RUN } from "../router/routes";

/** The run in the URL (/runs/:run). */
export function useRun(): string {
  return useParams().run ?? DEFAULT_RUN;
}
