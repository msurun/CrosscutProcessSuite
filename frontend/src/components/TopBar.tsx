// src/components/TopBar.tsx
/**
 * Header bar for the Crosscut web console.
 * Displays application branding, the read-only mode badge, an optional
 * shortcut to the plant site catalogue, and language/theme preference pickers.
 */

import type { ReactNode } from "react";
import type { ThemePreference } from "../useTheme";

/** The theme options in the order they are offered to the user. */
const THEME_OPTIONS: readonly ThemePreference[] = ["system", "light", "dark"];

/** Identifiers that tie each <label> to its <select>. */
const LANGUAGE_SELECT_ID = "top-bar-language";
const THEME_SELECT_ID = "top-bar-theme";

export interface TopBarProps {
  /** Application name shown on the left. */
  title: string;
  /** Text of the badge warning the user that the session cannot be edited. */
  readOnlyLabel: string;
  /** Language codes the user can pick from, e.g. ["pl", "en"]. */
  languages: readonly string[];
  /** Currently selected language code. */
  language: string;
  /** Called with the chosen language code. */
  onLanguage: (code: string) => void;
  /** Accessible label placed next to the language select. */
  languageLabel: string;
  /** Currently selected theme preference. */
  theme: ThemePreference;
  /** Called with the chosen theme preference. */
  onTheme: (preference: ThemePreference) => void;
  /** Accessible label placed next to the theme select. */
  themeLabel: string;
  /** Human readable (translated) name for each theme preference. */
  themeNames: Record<ThemePreference, string>;
  /** Optional callback to navigate directly to the site catalogue. */
  onCatalogue?: () => void;
  /** Accessible label for the site catalogue link or button. */
  catalogueLabel?: string;
  /** Optional account area (the signed-in user badge) shown at the end of the bar. */
  account?: ReactNode;
}

/**
 * Header bar with application title, read-only badge, catalogue shortcut, and pickers.
 *
 * @returns The rendered header element.
 */
export function TopBar({
  title,
  readOnlyLabel,
  languages,
  language,
  onLanguage,
  languageLabel,
  theme,
  onTheme,
  themeLabel,
  themeNames,
  onCatalogue,
  catalogueLabel,
  account,
}: TopBarProps) {
  function handleLanguageChange(event: React.ChangeEvent<HTMLSelectElement>) {
    onLanguage(event.target.value);
  }

  function handleThemeChange(event: React.ChangeEvent<HTMLSelectElement>) {
    onTheme(event.target.value as ThemePreference);
  }

  return (
    <header className="top-bar">
      <strong>{title}</strong>

      {onCatalogue && catalogueLabel && (
        <button
          type="button"
          className="link-button"
          onClick={onCatalogue}
        >
          {catalogueLabel}
        </button>
      )}

      <span className="read-only-badge">{readOnlyLabel}</span>

      <label htmlFor={LANGUAGE_SELECT_ID}>{languageLabel}</label>
      <select id={LANGUAGE_SELECT_ID} value={language} onChange={handleLanguageChange}>
        {languages.map((code) => (
          <option key={code} value={code}>
            {code.toUpperCase()}
          </option>
        ))}
      </select>

      <label htmlFor={THEME_SELECT_ID}>{themeLabel}</label>
      <select id={THEME_SELECT_ID} value={theme} onChange={handleThemeChange}>
        {THEME_OPTIONS.map((preference) => (
          <option key={preference} value={preference}>
            {themeNames[preference]}
          </option>
        ))}
      </select>
      {account}
    </header>
  );
}
