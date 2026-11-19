// src/components/BrandMark.tsx
/**
 * Crosscut brand mark: a damped step response settling onto a dashed setpoint.
 * Pure SVG, coloured by theme tokens so it works in light and dark mode.
 */

/** Step response y = 11 + 9·e^(-3.4t)·cos(2π·1.55t), sampled on a 24-unit grid. */
const RESPONSE_PATH =
  "M2.5 20 L3 18.9 L3.6 17.4 L4.1 15.7 L4.6 13.9 L5.1 12.2 L5.7 10.7 L6.2 9.5 " +
  "L6.7 8.6 L7.2 8.1 L7.8 7.8 L8.3 7.9 L8.8 8.1 L9.4 8.5 L9.9 9.1 L10.4 9.7 " +
  "L10.9 10.3 L11.5 10.8 L12 11.3 L12.5 11.6 L13.1 11.9 L13.6 12 L14.1 12.1 " +
  "L14.6 12 L15.2 11.9 L15.7 11.8 L16.2 11.6 L16.8 11.4 L17.3 11.2 L17.8 11 " +
  "L18.3 10.9 L18.9 10.8 L19.4 10.7 L19.9 10.6 L20.4 10.6 L21 10.7 L21.5 10.7";

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
      <line x1="2" y1="11" x2="22" y2="11" stroke="var(--text-muted)" strokeWidth="1.25" strokeDasharray="2.5 2" />
      <path d={RESPONSE_PATH} stroke="var(--accent)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
