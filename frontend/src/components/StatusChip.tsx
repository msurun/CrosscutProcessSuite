// src/components/StatusChip.tsx

/**
 * Severity shown by a {@link StatusChip}.
 *
 * - "ok": everything is fine.
 * - "warning": something needs attention soon.
 * - "problem": something is broken and needs action.
 * - "unused": the item is not in use, so no judgement is made about its health.
 */
export type StatusLevel = "ok" | "warning" | "problem" | "unused" | "not_assessed";

/**
 * The decorative icon shown next to the label, per level.
 *
 * Each level gets a distinct shape (not only a distinct colour) so the meaning
 * survives for colour-blind users and in greyscale print. Decorative only:
 * screen readers get the translated label text instead.
 */
const LEVEL_ICON: Record<StatusLevel, string> = {
  ok: "\u25CF", // filled circle
  warning: "\u25B2", // filled triangle
  problem: "\u25A0", // filled square
  unused: "\u25CB", // hollow circle
  not_assessed: "\u25CC", // dotted circle: not checked yet
};

type StatusChipProps = {
  level: StatusLevel;
  /** Already-translated text describing the status; displayed as-is. */
  label: string;
};

/**
 * Small inline badge showing a status as an icon plus its label.
 *
 * Renders a `<span role="status">`; the icon is `aria-hidden`, so assistive
 * technology announces only the label. Styling comes from the
 * `status-chip--<level>` class.
 */
export function StatusChip({ level, label }: StatusChipProps) {
  return (
    <span className={`status-chip status-chip--${level}`} role="status">
      <span aria-hidden="true">{LEVEL_ICON[level]}</span>
      {label}
    </span>
  );
}
