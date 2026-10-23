import ProducerTab from "../components/Producer";
import { useRun } from "../hooks/useRun";
import { useRunQuery } from "../store/serverApi";

export default function ProducerPage() {
  const { data } = useRunQuery(useRun());
  return data ? <ProducerTab narrations={data.narrations} /> : null;
}
