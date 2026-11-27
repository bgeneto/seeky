// React binding for the theme controller (SPEC-0014 §4.3, §5.2, R11, R12).
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { ThemeController, ThemePreference } from "./theme";

interface ThemeContextValue {
  preference: ThemePreference;
  setPreference(preference: ThemePreference): void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({
  controller,
  children,
}: {
  controller: ThemeController;
  children: ReactNode;
}) {
  const preference = useSyncExternalStore(
    controller.subscribe,
    controller.preference,
  );

  // OS theme tracking; idempotent under StrictMode and removed on teardown.
  useEffect(() => controller.start(), [controller]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      preference,
      setPreference: (next) => void controller.setPreference(next),
    }),
    [controller, preference],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}
