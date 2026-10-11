// src/useTheme.ts
import { useCallback, useEffect, useState } from "react";

/** The user's stated colour-scheme choice: follow the OS, or force light/dark. */
export type ThemePreference = "system" | "light" | "dark";

/** The colour scheme actually rendered, after the "system" preference is resolved. */
export type ResolvedTheme = "light" | "dark";

/** localStorage key holding the persisted {@link ThemePreference}. Namespaced to avoid collisions. */
export const THEME_STORAGE_KEY = "crosscut.theme";

const DARK_MEDIA_QUERY = "(prefers-color-scheme: dark)";

/**
 * Turns a stored preference into the theme to render.
 *
 * Pure: "system" defers to the OS signal, the other two are used as-is.
 *
 * @param preference - What the user chose.
 * @param systemPrefersDark - Whether the OS currently reports a dark scheme.
 * @returns The theme to apply to the document.
 */
export function resolveTheme(preference: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (preference === "system") {
    return systemPrefersDark ? "dark" : "light";
  }
  return preference;
}

/** Type guard for values read back from storage, which are untrusted. */
function isThemePreference(value: string): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

/**
 * Reads the persisted preference from localStorage.
 *
 * Storage access can throw (private mode, blocked cookies), so any failure is
 * treated as "nothing stored". Unrecognised values are ignored for the same
 * reason: a corrupt entry must not break rendering.
 *
 * @returns The stored preference, or "system" when absent or invalid.
 */
export function loadPreference(): ThemePreference {
  try {
    const storedValue = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (storedValue !== null && isThemePreference(storedValue)) {
      return storedValue;
    }
  } catch {
    // Storage unavailable: fall through to the default.
  }
  return "system";
}

/**
 * Persists the preference to localStorage.
 *
 * Failures are swallowed on purpose: the theme still applies for this session
 * even when it cannot be remembered for the next one.
 *
 * @param preference - The preference to store.
 */
export function savePreference(preference: ThemePreference): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Storage unavailable: the preference simply will not persist.
  }
}

/**
 * Applies the theme to the document root, where the CSS reads it.
 *
 * The matching stylesheet rule is `:root[data-theme="dark"]`.
 *
 * @param theme - The resolved theme to render.
 */
export function applyTheme(theme: ResolvedTheme): void {
  document.documentElement.dataset.theme = theme;
}

/** Reports whether the OS asks for dark mode; older browsers without matchMedia count as light. */
function systemPrefersDark(): boolean {
  if (typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(DARK_MEDIA_QUERY).matches;
}

/**
 * Subscribes to OS scheme changes and re-applies the theme on each change.
 *
 * @param preference - The current preference; listeners are only attached for "system".
 */
function useSystemThemeListener(preference: ThemePreference): void {
  useEffect(() => {
    applyTheme(resolveTheme(preference, systemPrefersDark()));

    if (preference !== "system" || typeof window.matchMedia !== "function") {
      return;
    }

    const mediaQuery = window.matchMedia(DARK_MEDIA_QUERY);
    const handleChange = (event: MediaQueryListEvent): void => {
      applyTheme(event.matches ? "dark" : "light");
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => {
      mediaQuery.removeEventListener("change", handleChange);
    };
  }, [preference]);
}

/**
 * React hook exposing the colour-scheme preference and a setter for it.
 *
 * The preference is read once from localStorage, kept in React state, mirrored
 * onto `<html data-theme>` and written back to localStorage on every change.
 * While the preference is "system" the hook also follows OS scheme changes.
 *
 * @returns A `[preference, setPreference]` tuple.
 */
export function useTheme(): [ThemePreference, (preference: ThemePreference) => void] {
  const [preference, setPreferenceState] = useState<ThemePreference>(loadPreference);

  const setPreference = useCallback((nextPreference: ThemePreference): void => {
    savePreference(nextPreference);
    setPreferenceState(nextPreference);
  }, []);

  useSystemThemeListener(preference);

  return [preference, setPreference];
}
