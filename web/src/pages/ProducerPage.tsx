import { useEffect } from "react";
import ProducerTab from "../components/Producer";
import { useRun } from "../hooks/useRun";
import { useAppDispatch } from "../store";
import { controlActions } from "../store/control";
import { useRunQuery } from "../store/serverApi";
import BroadcastPage from "./BroadcastPage";

/** The control room: the broadcast as viewers see it beside the producer's
 * desk, on one clock. Lines arrive on the desk as the match plays; with
 * "approve before air" (on at a first visit) they reach the broadcast only
 * when approved. On a narrow screen the desk alone. */
export default function ProducerPage() {
  const { data } = useRunQuery(useRun());
  const dispatch = useAppDispatch();
  useEffect(() => {
    dispatch(controlActions.openRoom());
  }, [dispatch]);
  if (!data) return null;
  return (
    <div className="control-room">
      <div className="room-broadcast">
        <BroadcastPage inRoom />
      </div>
      <ProducerTab narrations={data.narrations} />
    </div>
  );
}
