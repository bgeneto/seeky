// Locale preference and OS resolution (SPEC-0014 §4.2, §5.1, R3, R4).
import type { PreferenceStore } from "../preferences.ts";

export type CatalogLocale = "en" | "pt";
export type LocalePreference = "system" | CatalogLocale;
export type FormattingLocale = "en" | "pt-BR";

export const LOCALE_STORAGE_KEY = "seeky.ui.locale.v1";
export const LOCALE_PREFERENCES: readonly LocalePreference[] = [
  "system",
  "en",
  "pt",
];

export function parseLocalePreference(value: unknown): LocalePreference {
  return value === "en" || value === "pt" || value === "system"
    ? value
    : "system";
}

function baseLanguage(candidate: string): string | null {
  try {
    const [canonical] = Intl.getCanonicalLocales(candidate);
    return canonical ? canonical.split("-")[0].toLowerCase() : null;
  } catch {
    return null;
  }
}

export function resolveLocale(
  preference: LocalePreference,
  osLanguages: readonly string[],
): CatalogLocale {
  if (preference !== "system") return preference;
  for (const candidate of osLanguages) {
    const base = baseLanguage(candidate);
    if (base === "pt" || base === "en") return base;
  }
  return "en";
}

/** v1 formats every Portuguese variant with pt-BR conventions (§4.2). */
export function formattingLocale(locale: CatalogLocale): FormattingLocale {
  return locale === "pt" ? "pt-BR" : "en";
}

export function navigatorLanguages(): string[] {
  if (typeof navigator === "undefined") return [];
  const list = Array.isArray(navigator.languages) ? navigator.languages : [];
  if (list.length) return [...list];
  return navigator.language ? [navigator.language] : [];
}

export interface LocaleState {
  preference(): LocalePreference;
  locale(): CatalogLocale;
  setPreference(preference: LocalePreference): CatalogLocale;
  /** Recomputes a `system` preference after an OS `languagechange`. */
  refreshOs(): CatalogLocale;
}

export function createLocaleState(
  store: PreferenceStore,
  osLanguages: () => readonly string[],
): LocaleState {
  let preference = parseLocalePreference(store.read(LOCALE_STORAGE_KEY));
  let locale = resolveLocale(preference, osLanguages());

  return {
    preference: () => preference,
    locale: () => locale,
    setPreference(next) {
      preference = parseLocalePreference(next);
      store.write(LOCALE_STORAGE_KEY, preference);
      locale = resolveLocale(preference, osLanguages());
      return locale;
    },
    refreshOs() {
      locale = resolveLocale(preference, osLanguages());
      return locale;
    },
  };
}
