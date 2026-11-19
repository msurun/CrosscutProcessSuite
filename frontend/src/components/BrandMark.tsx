// src/components/BrandMark.tsx
/**
 * Crosscut brand mark: a damped step response settling onto a dashed setpoint.
 * Pure SVG, coloured by theme tokens so it works in light and dark mode.
 */

/** Underdamped step response y = 12 + 9·e^(-2t)·cos(2π·2.4t), on a 24-unit grid. */
const RESPONSE_PATH =
  "M2 21 L2.33 20.43 L2.67 19.38 L3 17.94 L3.33 16.22 L3.67 14.35 L4 12.46 " +
  "L4.33 10.66 L4.67 9.06 L5 7.75 L5.33 6.78 L5.67 6.20 L6 6.01 L6.33 6.21 " +
  "L6.67 6.75 L7 7.58 L7.33 8.63 L7.67 9.83 L8 11.07 L8.33 12.30 L8.67 13.43 " +
  "L9 14.39 L9.33 15.15 L9.67 15.66 L10 15.92 L10.33 15.91 L10.67 15.66 " +
  "L11 15.21 L11.33 14.58 L11.67 13.83 L12 13.02 L12.33 12.20 L12.67 11.42 " +
  "L13 10.72 L13.33 10.15 L13.67 9.73 L14 9.48 L14.33 9.40 L14.67 9.48 " +
  "L15 9.72 L15.33 10.08 L15.67 10.54 L16 11.06 L16.33 11.60 L16.67 12.13 " +
  "L17 12.62 L17.33 13.04 L17.67 13.37 L18 13.59 L18.33 13.70 L18.67 13.70 " +
  "L19 13.59 L19.33 13.39 L19.67 13.12 L20 12.80 L20.33 12.44 L20.67 12.09 " +
  "L21 11.75 L21.33 11.45 L21.67 11.20 L22 11.01";

export interface BrandMarkProps {
  /** Rendered width and height in pixels. */
  size?: number;
}

/**
 * Decorative logo; the product name next to it carries the accessible text.
 *
 * @returns The SVG element.
 */
export function BrandMark({ size = 24 }: BrandMarkProps) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <line x1="2" y1="12" x2="22" y2="12" stroke="var(--text-muted)" strokeWidth="1.25" strokeDasharray="2.5 2" />
      <path d={RESPONSE_PATH} stroke="var(--accent)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
