// SPEC-0014 R3, R4: locale resolution, override, and safe persistence.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  LOCALE_STORAGE_KEY,
  createLocaleState,
  formattingLocale,
  parseLocalePreference,
  resolveLocale,
} from "../../src/i18n/locale.ts";
import { createPreferenceStore } from "../../src/preferences.ts";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
  };
}

describe("OS locale resolution (SPEC-0014 R3)", () => {
  test("os_locale_prefers_first_supported_language", () => {
    assert.equal(resolveLocale("system", ["pt-BR", "en-US"]), "pt");
    assert.equal(resolveLocale("system", ["en-US", "pt-BR"]), "en");
    assert.equal(resolveLocale("system", ["fr-FR", "pt-BR"]), "pt");
  });

  test("os_locale_maps_regional_variants_to_base_catalogs", () => {
    assert.equal(resolveLocale("system", ["pt-PT"]), "pt");
    assert.equal(resolveLocale("system", ["en-GB"]), "en");
    assert.equal(resolveLocale("system", ["PT-br"]), "pt");
    assert.equal(formattingLocale("pt"), "pt-BR");
    assert.equal(formattingLocale("en"), "en");
  });

  test("os_locale_falls_back_to_english", () => {
    assert.equal(resolveLocale("system", ["fr-FR", "de-DE"]), "en");
    assert.equal(resolveLocale("system", []), "en");
    assert.equal(resolveLocale("system", ["", "not a locale!!"]), "en");
  });

  test("invalid_stored_locale_uses_os_locale", () => {
    assert.equal(parseLocalePreference("fr"), "system");
    assert.equal(parseLocalePreference(null), "system");
    assert.equal(parseLocalePreference("pt"), "pt");
    const storage = memoryStorage();
    storage.data.set(LOCALE_STORAGE_KEY, "klingon");
    const state = createLocaleState(
      createPreferenceStore(() => storage),
      () => ["pt-BR"],
    );
    assert.equal(state.preference(), "system");
    assert.equal(state.locale(), "pt");
  });

  test("explicit_preference_ignores_os_languages", () => {
    assert.equal(resolveLocale("en", ["pt-BR"]), "en");
    assert.equal(resolveLocale("pt", ["en-US"]), "pt");
  });
});

describe("locale override (SPEC-0014 R4)", () => {
  test("locale_override_persists_and_applies_without_reload", () => {
    const storage = memoryStorage();
    let os = ["en-US"];
    const state = createLocaleState(
      createPreferenceStore(() => storage),
      () => os,
    );
    assert.equal(state.locale(), "en");
    assert.equal(state.setPreference("pt"), "pt");
    assert.equal(state.locale(), "pt");
    assert.equal(storage.data.get(LOCALE_STORAGE_KEY), "pt");

    os = ["pt-BR"];
    const restarted = createLocaleState(
      createPreferenceStore(() => storage),
      () => ["en-US"],
    );
    assert.equal(restarted.locale(), "pt");

    assert.equal(state.setPreference("system"), "pt");
    assert.equal(storage.data.get(LOCALE_STORAGE_KEY), "system");
    os = ["en-GB"];
    assert.equal(state.refreshOs(), "en");
  });

  test("os_change_does_not_override_explicit_choice", () => {
    let os = ["en-US"];
    const state = createLocaleState(
      createPreferenceStore(() => memoryStorage()),
      () => os,
    );
    state.setPreference("en");
    os = ["pt-BR"];
    assert.equal(state.refreshOs(), "en");
  });

  test("storage_failure_uses_in_memory_preferences", () => {
    const broken = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    };
    const store = createPreferenceStore(() => broken);
    const state = createLocaleState(store, () => ["en-US"]);
    assert.equal(state.locale(), "en");
    assert.equal(state.setPreference("pt"), "pt");
    assert.equal(store.read(LOCALE_STORAGE_KEY), "pt");

    const absent = createPreferenceStore(() => {
      throw new Error("no storage");
    });
    absent.write(LOCALE_STORAGE_KEY, "en");
    assert.equal(absent.read(LOCALE_STORAGE_KEY), "en");
  });
});
