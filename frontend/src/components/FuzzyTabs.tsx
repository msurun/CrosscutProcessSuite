/**
 * Accessible tab strip of the Fuzzy Studio (WAI-ARIA tabs pattern, automatic activation).
 * Left/Right/Home/End move between tabs; only the active tab is in the tab order.
 */

import { useRef, type KeyboardEvent, type ReactNode } from "react";
import type { Translate } from "../findings";

/** The tabs of the studio, in display order. */
export const FUZZY_TABS = ["variables", "rules", "replay", "backtest"] as const;

export type FuzzyTab = (typeof FUZZY_TABS)[number];

/** Index of the tab a key moves to, or null when the key is not a navigation key. */
export function nextTabIndex(key: string, current: number, count: number): number | null {
  if (key === "ArrowRight") return (current + 1) % count;
  if (key === "ArrowLeft") return (current - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

/** DOM id of the tab button of `tab`. */
export function tabId(tab: FuzzyTab): string {
  return `fuzzy-tab-${tab}`;
}

/** DOM id of the panel of `tab`. */
export function panelId(tab: FuzzyTab): string {
  return `fuzzy-panel-${tab}`;
}

interface FuzzyTabListProps {
  active: FuzzyTab;
  onChange: (tab: FuzzyTab) => void;
  t: Translate;
}

/** The row of tab buttons. */
export function FuzzyTabList({ active, onChange, t }: FuzzyTabListProps) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  function handleKey(event: KeyboardEvent, index: number): void {
    const target = nextTabIndex(event.key, index, FUZZY_TABS.length);
    if (target === null) return;
    event.preventDefault();
    onChange(FUZZY_TABS[target]);
    buttons.current[target]?.focus();
  }

  return (
    <div role="tablist" aria-label={t("fuzzy.tabs")} className="fuzzy-tabs">
      {FUZZY_TABS.map((tab, index) => (
        <button
          key={tab}
          ref={(element) => {
            buttons.current[index] = element;
          }}
          type="button"
          role="tab"
          id={tabId(tab)}
          aria-selected={tab === active}
          aria-controls={panelId(tab)}
          tabIndex={tab === active ? 0 : -1}
          className={tab === active ? "fuzzy-tab fuzzy-tab-active" : "fuzzy-tab"}
          onClick={() => onChange(tab)}
          onKeyDown={(event) => handleKey(event, index)}
        >
          {t(`fuzzy.tab.${tab}`)}
        </button>
      ))}
    </div>
  );
}

/** The panel belonging to `tab`; the caller renders it only for the active tab. */
export function FuzzyTabPanel({ tab, children }: { tab: FuzzyTab; children: ReactNode }) {
  return (
    <div role="tabpanel" id={panelId(tab)} aria-labelledby={tabId(tab)} className="fuzzy-tabpanel">
      {children}
    </div>
  );
}
