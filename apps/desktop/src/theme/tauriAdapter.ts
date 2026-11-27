// The Tauri/webview side of the theme adapter (SPEC-0014 §4.3, §4.5). Only
// the narrow core window/webview setters of §4.5 are used. Every call is
// made inside an async function so a missing Tauri runtime (plain `vite`
// in a browser) becomes a rejected promise, which theme.ts records and
// survives.
import { getCurrentWindow, type Theme } from "@tauri-apps/api/window";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import type { EffectiveTheme, ThemeAdapter } from "./theme";

function query(scheme: EffectiveTheme): MediaQueryList | null {
  try {
    return typeof window.matchMedia === "function"
      ? window.matchMedia(`(prefers-color-scheme: ${scheme})`)
      : null;
  } catch {
    return null;
  }
}

function mediaTheme(): EffectiveTheme | null {
  if (query("dark")?.matches) return "dark";
  if (query("light")?.matches) return "light";
  return null;
}

function asEffective(theme: Theme | null): EffectiveTheme | null {
  return theme === "dark" || theme === "light" ? theme : null;
}

export function createTauriThemeAdapter(): ThemeAdapter {
  return {
    mediaTheme,
    nativeTheme: async () => asEffective(await getCurrentWindow().theme()),
    setNativeTheme: async (theme) => getCurrentWindow().setTheme(theme),
    // Sets both the window and the webview background (two §4.5 permissions).
    setNativeBackground: async (color) =>
      getCurrentWebviewWindow().setBackgroundColor(color),
    show: async () => getCurrentWindow().show(),

    onOsThemeChange(listener) {
      // The media query is the primary web source; the native event covers
      // webviews that do not report it. Duplicates are harmless.
      const dark = query("dark");
      const onMedia = () => listener(mediaTheme());
      dark?.addEventListener("change", onMedia);

      let disposed = false;
      let unlisten: (() => void) | null = null;
      (async () => {
        const stop = await getCurrentWindow().onThemeChanged(({ payload }) =>
          listener(asEffective(payload)),
        );
        if (disposed) stop();
        else unlisten = stop;
      })().catch(() => {
        // Not running inside Tauri: the media query alone tracks the OS.
      });

      return () => {
        disposed = true;
        dark?.removeEventListener("change", onMedia);
        unlisten?.();
        unlisten = null;
      };
    },
  };
}
