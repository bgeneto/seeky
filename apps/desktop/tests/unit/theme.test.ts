// SPEC-0014 R10-R13: theme tokens, preference, OS tracking, and native sync.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { dark, light } from "../../src/theme/tokens.ts";
import {
  THEME_STORAGE_KEY,
  applyThemeToRoot,
  createThemeController,
  initializeWindow,
  parseThemePreference,
  resolveTheme,
  type EffectiveTheme,
  type ThemeAdapter,
} from "../../src/theme/theme.ts";
import { createPreferenceStore } from "../../src/preferences.ts";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
  };
}

type Call =
  ["setTheme", EffectiveTheme | null] | ["setBackground", string] | ["show"];

/** A fake Tauri/webview adapter that records native calls in order. */
function fakeAdapter(
  options: {
    media?: EffectiveTheme | null;
    native?: EffectiveTheme | null;
    reject?: boolean;
  } = {},
) {
  const calls: Call[] = [];
  const listeners = new Set<(theme: EffectiveTheme | null) => void>();
  let subscriptions = 0;
  const state = {
    media: options.media === undefined ? "light" : options.media,
    native: options.native ?? null,
  };
  const fail = () =>
    options.reject ? Promise.reject(new Error("native")) : Promise.resolve();
  const adapter: ThemeAdapter = {
    mediaTheme: () => state.media,
    nativeTheme: () =>
      options.reject
        ? Promise.reject(new Error("native"))
        : Promise.resolve(state.native),
    setNativeTheme(theme) {
      calls.push(["setTheme", theme]);
      return fail();
    },
    setNativeBackground(color) {
      calls.push(["setBackground", color]);
      return fail();
    },
    show() {
      calls.push(["show"]);
      return fail();
    },
    onOsThemeChange(listener) {
      subscriptions += 1;
      listeners.add(listener);
      return () => {
        subscriptions -= 1;
        listeners.delete(listener);
      };
    },
  };
  return {
    adapter,
    calls,
    state,
    subscriptions: () => subscriptions,
    /** An OS theme change: the media query now reports it, then events fire. */
    emit(theme: EffectiveTheme | null) {
      state.media = theme;
      for (const listener of [...listeners]) listener(theme);
    },
  };
}

function controllerWith(
  fake: ReturnType<typeof fakeAdapter>,
  storage = memoryStorage(),
) {
  const applied: EffectiveTheme[] = [];
  const controller = createThemeController({
    store: createPreferenceStore(() => storage),
    adapter: fake.adapter,
    apply: (theme) => applied.push(theme),
  });
  return { controller, applied, storage };
}

describe("semantic tokens (SPEC-0014 R10)", () => {
  test("token_sets_have_same_semantic_keys", () => {
    const lightKeys = Object.keys(light).sort();
    assert.deepEqual(Object.keys(dark).sort(), lightKeys);
    for (const role of [
      "bg",
      "panel",
      "panelRaised",
      "sidebar",
      "preview",
      "input",
      "hover",
      "selected",
      "statusbar",
      "border",
      "borderStrong",
      "focusRing",
      "text",
      "muted",
      "subtle",
      "placeholder",
      "onAccent",
      "onMark",
      "accent",
      "accentHover",
      "accentText",
      "accentSecondary",
      "danger",
      "dangerBg",
      "warning",
      "warningBg",
      "success",
      "successBg",
      "info",
      "infoBg",
      "mark",
      "disabled",
      "onDisabled",
      "shadow",
    ]) {
      assert.ok(lightKeys.includes(role), `missing role ${role}`);
    }
    for (const value of [...Object.values(light), ...Object.values(dark)]) {
      assert.equal(typeof value, "string");
      assert.ok(value.length > 0);
    }
  });

  test("root_receives_variables_data_theme_and_color_scheme", () => {
    const properties = new Map<string, string>();
    const attributes = new Map<string, string>();
    applyThemeToRoot(
      {
        style: { setProperty: (name, value) => properties.set(name, value) },
        setAttribute: (name, value) => attributes.set(name, value),
      },
      "dark",
    );
    assert.equal(attributes.get("data-theme"), "dark");
    assert.equal(properties.get("color-scheme"), "dark");
    assert.equal(properties.get("--color-bg"), dark.bg);
    assert.equal(properties.get("--color-panelRaised"), dark.panelRaised);
    assert.equal(
      [...properties.keys()].filter((name) => name.startsWith("--color-"))
        .length,
      Object.keys(dark).length,
    );
  });
});

describe("OS theme tracking (SPEC-0014 R11)", () => {
  test("os_theme_resolution_has_deterministic_fallback", async () => {
    assert.equal(resolveTheme("system", "dark"), "dark");
    assert.equal(resolveTheme("system", "light"), "light");
    assert.equal(resolveTheme("system", null), "light");
    assert.equal(resolveTheme("dark", "light"), "dark");
    assert.equal(resolveTheme("light", "dark"), "light");

    // No media result: the adapter asks the native window, then falls back.
    const nativeDark = fakeAdapter({ media: null, native: "dark" });
    const a = controllerWith(nativeDark).controller;
    await a.initialize();
    assert.equal(a.effective(), "dark");

    const neither = fakeAdapter({ media: null, native: null });
    const b = controllerWith(neither).controller;
    await b.initialize();
    assert.equal(b.effective(), "light");

    const failing = fakeAdapter({ media: null, reject: true });
    const c = controllerWith(failing).controller;
    await c.initialize();
    assert.equal(c.effective(), "light");
  });

  test("system_theme_changes_only_in_system_mode", async () => {
    const fake = fakeAdapter({ media: "light" });
    const { controller, applied } = controllerWith(fake);
    await controller.initialize();
    const stop = controller.start();

    fake.emit("dark");
    assert.equal(controller.effective(), "dark");
    assert.equal(applied.at(-1), "dark");
    fake.emit("dark"); // duplicate media + Tauri notifications are harmless
    assert.equal(controller.effective(), "dark");

    controller.setPreference("light");
    fake.emit("dark");
    assert.equal(controller.effective(), "light");
    fake.emit("light");
    fake.emit("dark");
    assert.equal(controller.effective(), "light");

    // Returning to system resolves the current OS value immediately.
    fake.state.media = "dark";
    controller.setPreference("system");
    assert.equal(controller.effective(), "dark");
    await controller.settled();
    assert.equal(controller.effective(), "dark");

    // The OS switches while an override is active; the webview may only
    // report the override, so the native window is asked after setTheme(null).
    controller.setPreference("dark");
    fake.state.native = "light";
    controller.setPreference("system");
    assert.equal(controller.effective(), "dark"); // last OS value seen
    await controller.settled();
    assert.equal(controller.effective(), "light");
    stop();
  });

  test("preference_change_notifies_even_when_effective_theme_is_unchanged", async () => {
    const fake = fakeAdapter({ media: "dark" });
    const { controller } = controllerWith(fake);
    await controller.initialize();
    let notified = 0;
    controller.subscribe(() => (notified += 1));
    controller.setPreference("dark"); // effective stays dark
    assert.equal(notified, 1);
    assert.equal(controller.preference(), "dark");
  });

  test("os_subscription_is_idempotent_and_removed_on_teardown", () => {
    const fake = fakeAdapter();
    const { controller } = controllerWith(fake);
    const stopA = controller.start();
    const stopB = controller.start(); // React StrictMode double setup
    assert.equal(fake.subscriptions(), 1);
    stopA();
    assert.equal(fake.subscriptions(), 1);
    stopB();
    assert.equal(fake.subscriptions(), 0);
    stopB();
    assert.equal(fake.subscriptions(), 0);
  });
});

describe("theme override (SPEC-0014 R12)", () => {
  test("theme_override_persists_and_applies_without_reload", async () => {
    const storage = memoryStorage();
    const fake = fakeAdapter({ media: "light" });
    const { controller, applied } = controllerWith(fake, storage);
    await controller.initialize();
    assert.equal(controller.preference(), "system");
    assert.equal(controller.effective(), "light");

    const seen: EffectiveTheme[] = [];
    const unsubscribe = controller.subscribe(() =>
      seen.push(controller.effective()),
    );
    assert.equal(controller.setPreference("dark"), "dark");
    assert.equal(applied.at(-1), "dark");
    assert.deepEqual(seen, ["dark"]);
    assert.equal(storage.data.get(THEME_STORAGE_KEY), "dark");
    unsubscribe();

    // Restart: the stored override wins over the OS value.
    const restarted = controllerWith(fakeAdapter({ media: "light" }), storage);
    await restarted.controller.initialize();
    assert.equal(restarted.controller.preference(), "dark");
    assert.equal(restarted.controller.effective(), "dark");

    restarted.controller.setPreference("system");
    assert.equal(storage.data.get(THEME_STORAGE_KEY), "system");
    assert.equal(restarted.controller.effective(), "light");
    // Only the enum is stored.
    assert.deepEqual([...storage.data.keys()], [THEME_STORAGE_KEY]);
  });

  test("invalid_theme_falls_back_system", async () => {
    for (const bad of ["Dark", "sepia", "", "high-contrast", null]) {
      assert.equal(parseThemePreference(bad), "system");
    }
    assert.equal(parseThemePreference("light"), "light");
    const storage = memoryStorage();
    storage.data.set(THEME_STORAGE_KEY, "solarized");
    const { controller } = controllerWith(
      fakeAdapter({ media: "dark" }),
      storage,
    );
    await controller.initialize();
    assert.equal(controller.preference(), "system");
    assert.equal(controller.effective(), "dark");
  });

  test("storage_failure_uses_in_memory_preferences", async () => {
    const throwing = {
      getItem(): string | null {
        throw new Error("denied");
      },
      setItem() {
        throw new Error("denied");
      },
    };
    const applied: EffectiveTheme[] = [];
    const controller = createThemeController({
      store: createPreferenceStore(() => throwing),
      adapter: fakeAdapter({ media: "dark" }).adapter,
      apply: (theme) => applied.push(theme),
    });
    await controller.initialize();
    assert.equal(controller.effective(), "dark");
    assert.equal(controller.setPreference("light"), "light");
    assert.equal(controller.preference(), "light");
    assert.equal(applied.at(-1), "light");

    const unavailable = createThemeController({
      store: createPreferenceStore(() => {
        throw new Error("no storage");
      }),
      adapter: fakeAdapter({ media: "light" }).adapter,
      apply: () => {},
    });
    await unavailable.initialize();
    assert.equal(unavailable.preference(), "system");
  });
});

describe("native synchronization (SPEC-0014 R13)", () => {
  test("native_theme_receives_null_for_system_and_explicit_override", async () => {
    const fake = fakeAdapter({ media: "dark" });
    const { controller } = controllerWith(fake);
    await controller.initialize();
    assert.deepEqual(fake.calls[0], ["setTheme", null]);

    controller.setPreference("light");
    await controller.settled();
    controller.setPreference("dark");
    await controller.settled();
    controller.setPreference("system");
    await controller.settled();
    const themes = fake.calls
      .filter((call) => call[0] === "setTheme")
      .map((call) => call[1]);
    assert.deepEqual(themes, [null, "light", "dark", null]);
  });

  test("native_background_matches_effective_background_token", async () => {
    const fake = fakeAdapter({ media: "dark" });
    const { controller } = controllerWith(fake);
    await controller.initialize();
    const lastBackground = () =>
      fake.calls.filter((call) => call[0] === "setBackground").at(-1)?.[1];
    assert.equal(lastBackground(), dark.bg);

    controller.setPreference("light");
    await controller.settled();
    assert.equal(lastBackground(), light.bg);

    controller.setPreference("system");
    controller.start();
    fake.emit("light");
    await controller.settled();
    assert.equal(lastBackground(), light.bg);
    fake.emit("dark");
    await controller.settled();
    assert.equal(lastBackground(), dark.bg);
  });

  test("initialization_failure_still_shows_window", async () => {
    const rejecting = fakeAdapter({ media: "dark", reject: true });
    const { controller } = controllerWith(rejecting);
    let rendered = false;
    await initializeWindow({
      controller,
      adapter: rejecting.adapter,
      render: () => {
        rendered = true;
      },
    });
    assert.equal(rendered, true);
    assert.equal(controller.effective(), "dark"); // web theme retained
    assert.deepEqual(rejecting.calls.at(-1), ["show"]);

    // Even a render failure leaves the window visible, then rethrows.
    const ok = fakeAdapter({ media: "light" });
    const second = controllerWith(ok).controller;
    await assert.rejects(
      initializeWindow({
        controller: second,
        adapter: ok.adapter,
        render: () => {
          throw new Error("render");
        },
      }),
    );
    assert.deepEqual(ok.calls.at(-1), ["show"]);

    // Native setters run while the window is still hidden, before show.
    const order = ok.calls.map((call) => call[0]);
    assert.ok(order.indexOf("setBackground") < order.indexOf("show"));

    // A native call that never settles cannot keep the window hidden.
    const hung = fakeAdapter({ media: "dark" });
    hung.adapter.setNativeTheme = () => new Promise<void>(() => {});
    const third = controllerWith(hung).controller;
    const diagnostics: string[] = [];
    await initializeWindow({
      controller: third,
      adapter: hung.adapter,
      render: () => {},
      timeoutMs: 5,
      onDiagnostic: (what) => diagnostics.push(what),
    });
    assert.deepEqual(hung.calls.at(-1), ["show"]);
    assert.deepEqual(diagnostics, ["theme initialization timeout"]);
  });
});
