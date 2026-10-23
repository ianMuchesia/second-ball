import { evidenceCounts, latencyText } from "../api";
import type { FeedItem } from "../store/selectors";

const KIND: Record<string, string> = {
  goal: "Goal",
  red_card_impact: "Red card",
  big_chance: "Big chance",
  repeated_pattern: "Pattern",
  momentum_swing: "Momentum",
  control_shift: "Control",
  recap_half_time: "Half-time",
  recap_full_time: "Full-time",
};

export const kindLabel = (k: string) => KIND[k] ?? k.replace(/_/g, " ");

/** The lower third: the verified line on air, its status, the evidence behind
 * it and how long it really took. */
export function MomentCard({
  item,
  lang,
  onEvidence,
}: {
  item: FeedItem | undefined;
  lang: string;
  onEvidence: () => void;
}) {
  if (!item) return null;
  const { overlay, narration } = item;
  const text = overlay.text[lang] ?? overlay.text.en;
  const translated = lang !== "en" && overlay.text[lang] !== undefined;
  const recap = overlay.slot === "recap";
  const verified = narration ? !narration.fallback : true;
  return (
    <section className="moment-card" data-testid="lower-third" aria-live="polite">
      <header>
        <span className="strip">
          {recap ? "Recap" : "Key moment"} · {kindLabel(overlay.kind)} · {overlay.t_in.match.minute}'
        </span>
        <span className={verified ? "status verified" : "status template"} data-testid="status">
          {verified ? "✓ Verified" : "Template"}
        </span>
      </header>
      <p className="headline" lang={translated ? lang : "en"}>
        {text}
      </p>
      <footer>
        {evidenceCounts(item.linkedEvents, item.players.length, item.metrics).map((x) => (
          <span key={x}>{x}</span>
        ))}
        {narration && (
          <span
            className={latencyText(narration).ok ? "latency ok" : "latency late"}
            title="event available → line verified and translated"
            data-testid="latency"
          >
            {latencyText(narration).text}
          </span>
        )}
        <button className="evidence-btn" onClick={onEvidence} data-testid="why">
          Evidence ›
        </button>
      </footer>
    </section>
  );
}
