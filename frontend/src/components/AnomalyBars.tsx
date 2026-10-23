// A horizontal bar list: name, bar and the value as text. The bar is decoration only
// (aria-hidden); the number is always in the text, so nothing depends on colour or length.

/** One bar: `fraction` in 0..1 sets its length, `text` is the value shown and read out. */
export interface BarRow {
  name: string;
  fraction: number;
  text: string;
}

/** The list of bars with an accessible name. */
export function BarList({ rows, label }: { rows: readonly BarRow[]; label: string }) {
  return (
    <ul className="bar-list" aria-label={label}>
      {rows.map((row) => (
        <li key={row.name} className="bar-row">
          <span className="bar-name">{row.name}</span>
          <span className="bar-track" aria-hidden="true">
            <span className="bar-fill" style={{ width: `${Math.min(100, Math.max(0, row.fraction * 100))}%` }} />
          </span>
          <span className="bar-value">{row.text}</span>
        </li>
      ))}
    </ul>
  );
}
