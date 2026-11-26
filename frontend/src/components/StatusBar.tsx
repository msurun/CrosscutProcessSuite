// frontend/src/components/StatusBar.tsx
// Global status bar (#174), shown on every page: gateway mode, kill switch state, proposals waiting for
// approval (opens the approval queue), runtime state and active alarms. Read-only: the kill switch is
// only displayed here; its actions stay on the gateway page.
import type { Translate } from "../findings";
import { buildItems, type StatusBarData, type StatusItem } from "../statusBarModel";
import { StatusChip } from "./StatusChip";

export interface StatusBarProps {
  data: StatusBarData;
  /** Opens the approval queue (the pending list of the gateway page). */
  onOpenQueue: () => void;
  t: Translate;
}

/** The value text of an item: a placeholder while loading, "unavailable" after a failure. */
function valueText(item: StatusItem, t: Translate): string {
  if (item.availability === "loading") return t("statusBar.loading");
  if (item.availability === "unavailable" || item.valueKey === null) return t("statusBar.unavailable");
  return t(item.valueKey, item.params);
}

/** One label + chip; the queue item is a button once its count is known. */
function BarItem({ item, onOpenQueue, t }: { item: StatusItem; onOpenQueue: () => void; t: Translate }) {
  const text = valueText(item, t);
  const label = t(`statusBar.${item.id}`);
  const chip = <StatusChip level={item.level} label={text} />;
  const opens = item.id === "queue" && item.availability === "ready";
  return (
    <li className="status-bar-item" data-testid={`status-bar-${item.id}`}>
      <span className="status-bar-label">{label}</span>
      {opens ? (
        <button type="button" className="status-bar-link" onClick={onOpenQueue} aria-label={`${label}: ${text}. ${t("statusBar.queue.open")}`}>
          {chip}
        </button>
      ) : chip}
    </li>
  );
}

/** The bar itself; `data` comes from useStatusBarData. */
export function StatusBar({ data, onOpenQueue, t }: StatusBarProps) {
  return (
    <section className="status-bar" aria-label={t("statusBar.title")} data-testid="status-bar">
      <ul className="status-bar-list">
        {buildItems(data).map((item) => <BarItem key={item.id} item={item} onOpenQueue={onOpenQueue} t={t} />)}
      </ul>
    </section>
  );
}
