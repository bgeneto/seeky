// React binding for the catalog module (SPEC-0014 §4.1, §4.5, §5.1).
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import en from "./locales/en.json";
import pt from "./locales/pt.json";
import { createI18n, type Catalog, type I18n } from "./messages";
import {
  createLocaleState,
  formattingLocale,
  navigatorLanguages,
  type LocalePreference,
} from "./locale";
import { browserStorage, createPreferenceStore } from "../preferences";

const CATALOGS = { en: en as Catalog, pt: pt as Catalog };

function diagnostic(what: string) {
  // Developer-only; carries a key or parameter name, never user data (§4.1).
  if (import.meta.env.DEV) console.warn(`[i18n] missing ${what}`);
}

interface I18nContextValue {
  i18n: I18n;
  preference: LocalePreference;
  setPreference(preference: LocalePreference): void;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [state] = useState(() =>
    createLocaleState(
      createPreferenceStore(browserStorage),
      navigatorLanguages,
    ),
  );
  const [preference, setPreferenceState] = useState(state.preference);
  const [locale, setLocale] = useState(state.locale);

  const i18n = useMemo(
    () => createI18n({ locale, catalogs: CATALOGS, onMissing: diagnostic }),
    [locale],
  );

  // A `languagechange` recomputes only a `system` preference (§5.1 step 4).
  useEffect(() => {
    const onLanguageChange = () => setLocale(state.refreshOs());
    window.addEventListener("languagechange", onLanguageChange);
    return () => window.removeEventListener("languagechange", onLanguageChange);
  }, [state]);

  // Before paint: <html lang>, the document title, and the native title.
  useLayoutEffect(() => {
    const title = i18n.t("window.title");
    document.documentElement.lang = formattingLocale(i18n.locale);
    document.title = title;
    try {
      getCurrentWindow()
        .setTitle(title)
        .catch(() => diagnostic("native window title"));
    } catch {
      // Not running inside Tauri (for example `vite` in a browser).
    }
  }, [i18n]);

  const value = useMemo<I18nContextValue>(
    () => ({
      i18n,
      preference,
      setPreference(next) {
        setLocale(state.setPreference(next));
        setPreferenceState(state.preference());
      },
    }),
    [i18n, preference, state],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}
