/** Types of a fuzzy rule base (see `schemas/fuzzy.schema.json`) and the membership functions to draw it. */

export type TermShape = "tri" | "trap" | "gauss";

export interface FuzzyTerm {
  name: string;
  shape: TermShape;
  params: number[];
}

export interface FuzzyVariable {
  id: string;
  label?: string;
  unit?: string;
  tag?: string;
  low: number;
  high: number;
  terms: FuzzyTerm[];
}

export interface FuzzyClause {
  variable: string;
  is: string;
}

export interface FuzzyRule {
  id: string;
  if: FuzzyClause[];
  operator?: "and" | "or";
  then: FuzzyClause;
  weight?: number;
  enabled?: boolean;
}

export interface FuzzyDocument {
  schema_version: string;
  name: string;
  description?: string;
  inputs: FuzzyVariable[];
  outputs: FuzzyVariable[];
  rules: FuzzyRule[];
}

/** Number of parameters each shape needs. */
export const SHAPE_PARAMETER_COUNTS: Record<TermShape, number> = { tri: 3, trap: 4, gauss: 2 };

/** Membership degree (0..1) of `x` in `term`; shoulders (a == b or c == d) are supported. */
export function membership(term: FuzzyTerm, x: number): number {
  if (term.shape === "gauss") {
    const [mean, sigma] = term.params;
    return Math.exp(-0.5 * ((x - mean) / sigma) ** 2);
  }
  const [footLeft, shoulderLeft, shoulderRight, footRight] = corners(term);
  return Math.min(rise(x, footLeft, shoulderLeft), fall(x, shoulderRight, footRight));
}

function corners(term: FuzzyTerm): [number, number, number, number] {
  if (term.shape === "tri") {
    const [footLeft, peak, footRight] = term.params;
    return [footLeft, peak, peak, footRight];
  }
  const [footLeft, shoulderLeft, shoulderRight, footRight] = term.params;
  return [footLeft, shoulderLeft, shoulderRight, footRight];
}

function rise(x: number, start: number, end: number): number {
  if (end === start) return x >= end ? 1 : 0;
  return Math.min(1, Math.max(0, (x - start) / (end - start)));
}

function fall(x: number, start: number, end: number): number {
  if (end === start) return x <= end ? 1 : 0;
  return Math.min(1, Math.max(0, (end - x) / (end - start)));
}

/** `points` evenly spaced samples of a term over [low, high], for drawing. */
export function sampleTerm(term: FuzzyTerm, low: number, high: number, points = 121): { x: number[]; y: number[] } {
  const x = Array.from({ length: points }, (_, index) => low + ((high - low) * index) / (points - 1));
  return { x, y: x.map((value) => membership(term, value)) };
}

/** CSS variable name of the colour of the `index`-th term (cycles through the 7 series colours). */
export function termColor(index: number): string {
  return `--series-${(index % 7) + 1}`;
}

/** A rule id that is not used yet: r1, r2, ... */
export function newRuleId(rules: readonly FuzzyRule[]): string {
  const used = new Set(rules.map((rule) => rule.id));
  let number = rules.length + 1;
  while (used.has(`r${number}`)) number += 1;
  return `r${number}`;
}

/** A library id made from a free-text name: lower case letters, digits, `_` and `-`, at most 64 characters. */
export function slugify(name: string): string {
  const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return slug.slice(0, 64) || "my_system";
}
