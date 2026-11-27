import React from "react";
import ReactDOM from "react-dom/client";
import { flushSync } from "react-dom";
import App from "./App";
import { I18nProvider } from "./i18n/I18nProvider";
import { browserStorage, createPreferenceStore } from "./preferences";
import { ThemeProvider } from "./theme/ThemeProvider";
import { createTauriThemeAdapter } from "./theme/tauriAdapter";
import {
  applyThemeToRoot,
  createThemeController,
  initializeWindow,
} from "./theme/theme";

function diagnostic(what: string) {
  // Developer-only; names the failed step, never user data (§4.5 step 3).
  if (import.meta.env.DEV) console.warn(`[theme] ${what} failed`);
}

// SPEC-0014 §4.5: the window starts hidden; resolve and apply the theme,
// render (which also sets <html lang> and the localized title), then show.
const adapter = createTauriThemeAdapter();
const controller = createThemeController({
  store: createPreferenceStore(browserStorage),
  adapter,
  apply: (theme) => applyThemeToRoot(document.documentElement, theme),
  onDiagnostic: diagnostic,
});
const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement,
);

void initializeWindow({
  controller,
  adapter,
  onDiagnostic: diagnostic,
  render: () =>
    flushSync(() =>
      root.render(
        <React.StrictMode>
          <ThemeProvider controller={controller}>
            <I18nProvider>
              <App />
            </I18nProvider>
          </ThemeProvider>
        </React.StrictMode>,
      ),
    ),
});
