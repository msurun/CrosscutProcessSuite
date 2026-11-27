// The global status bar (#174) polls these endpoints on every page; in an e2e backend without a
// gateway, runtime or site catalogue they answer 4xx/5xx by design and the bar shows "unavailable".
// Specs that assert "no failed API requests" ignore exactly these probes and nothing else.
const STATUS_BAR_PROBES = ["/api/gateway/status", "/api/runtime/status", "/api/live/loops", "/api/equipment/anomalies"];

/** True when a response URL is one of the status bar's polling endpoints. */
export function isStatusBarProbe(url: string): boolean {
  const path = new URL(url).pathname;
  return STATUS_BAR_PROBES.some((probe) => path === probe);
}

/** True for the browser's console line about a failed status-bar probe ("Failed to load resource"). */
export function isStatusBarConsoleNoise(text: string, locationUrl: string): boolean {
  return text.startsWith("Failed to load resource") && locationUrl !== "" && isStatusBarProbe(locationUrl);
}
