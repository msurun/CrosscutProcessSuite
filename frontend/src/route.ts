// Hash-router core for the frontend: turns `location.hash` into a typed Route and back.
// Pure functions only (no React, no DOM) so it can be unit-tested in isolation.
// Every dynamic segment is percent-encoded in the hash so dataset names and loop
// names may contain "/", "#", "?", spaces, "%" and non-ASCII letters.

/** The top-level views the app can show. */
export type View = "trends" | "loops" | "fuzzy" | "advisory" | "anomalies" | "softsensor" | "steps" | "import";

/** The sub-tabs of the "loops" view. */
export type LoopSub = "detail" | "tuning" | "benefit" | "valve";

/** A fully resolved location. `loop`/`sub` only mean something for view "loops". */
export interface Route {
  dataset: string;
  view: View;
  loop: string | null;
  sub: LoopSub;
}

/** Where the app lands when the hash is empty or unparsable. */
export const DEFAULT_ROUTE: Route = {
  dataset: "",
  view: "trends",
  loop: null,
  sub: "detail",
};

const PATH_PREFIX = "/d/";
const HASH_PREFIX = `#${PATH_PREFIX}`;
const KNOWN_VIEWS: readonly View[] = ["trends", "loops", "fuzzy", "advisory", "anomalies", "softsensor", "steps", "import"];
const KNOWN_SUBS: readonly LoopSub[] = ["detail", "tuning", "benefit", "valve"];

/**
 * Decode one percent-encoded hash segment.
 *
 * Returns `null` when the encoding is malformed (decodeURIComponent throws URIError)
 * so the caller can fall back instead of crashing.
 */
function decodeSegment(segment: string): string | null {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

/** True when `value` is one of the known view names. */
function isView(value: string): value is View {
  return (KNOWN_VIEWS as readonly string[]).includes(value);
}

/** True when `value` is one of the known loop sub-tab names. */
function isLoopSub(value: string): value is LoopSub {
  return (KNOWN_SUBS as readonly string[]).includes(value);
}

/**
 * Turn the raw hash (with or without a leading "#") into a Route.
 *
 * Never throws: empty, malformed, unknown or truncated hashes fall back to
 * DEFAULT_ROUTE, to the valid prefix of the hash, or to the documented defaults
 * (missing sub -> "detail", loop on a non-"loops" view -> dropped).
 */
export function parseHash(hash: string): Route {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!raw.startsWith(PATH_PREFIX)) {
    return { ...DEFAULT_ROUTE };
  }

  const segments = raw.slice(PATH_PREFIX.length).split("/");
  if (segments.length > 4) {
    return { ...DEFAULT_ROUTE };
  }

  const parts = segments.map(decodeSegment);
  const [dataset, viewName, loopName, subName] = parts;
  if (dataset === null || dataset === undefined) {
    return { ...DEFAULT_ROUTE };
  }
  if (viewName === null || viewName === undefined || !isView(viewName)) {
    return { ...DEFAULT_ROUTE };
  }

  return buildRoute(dataset, viewName, loopName ?? null, subName ?? null);
}

/**
 * Assemble a Route from already-decoded parts, applying the defaults:
 * loop/sub are only kept for the "loops" view, and an unknown sub becomes "detail".
 */
function buildRoute(
  dataset: string,
  view: View,
  loop: string | null,
  sub: string | null,
): Route {
  if (view !== "loops") {
    return { dataset, view, loop: null, sub: "detail" };
  }
  const resolvedSub: LoopSub = sub !== null && isLoopSub(sub) ? sub : "detail";
  return { dataset, view, loop, sub: resolvedSub };
}

/**
 * Render a Route as a canonical hash string starting with "#/d/".
 *
 * `parseHash(formatHash(route))` returns `route` for every valid route.
 */
export function formatHash(route: Route): string {
  const encodedParts = [encodeURIComponent(route.dataset), route.view];
  if (route.view === "loops" && route.loop !== null) {
    encodedParts.push(encodeURIComponent(route.loop), route.sub);
  }
  return HASH_PREFIX + encodedParts.join("/");
}

/** Return a copy of `route` on another dataset, with loop and sub reset to defaults. */
export function withDataset(route: Route, dataset: string): Route {
  return { dataset, view: route.view, loop: null, sub: "detail" };
}

/** Return a copy of `route` on another view, dropping loop/sub unless the view is "loops". */
export function withView(route: Route, view: View): Route {
  if (view !== "loops") {
    return { dataset: route.dataset, view, loop: null, sub: "detail" };
  }
  return { dataset: route.dataset, view, loop: route.loop, sub: route.sub };
}

/** Return a copy of `route` with the given loop, forcing the "loops" view. */
export function withLoop(route: Route, loop: string | null, sub: LoopSub = "detail"): Route {
  return { dataset: route.dataset, view: "loops", loop, sub };
}
