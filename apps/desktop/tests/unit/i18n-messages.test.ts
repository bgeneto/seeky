// SPEC-0014 R5-R8: messages, plurals, fallback, formatting, and errors.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import en from "../../src/i18n/locales/en.json" with { type: "json" };
import pt from "../../src/i18n/locales/pt.json" with { type: "json" };
import { createI18n, type Catalog } from "../../src/i18n/messages.ts";
import {
  OPERATION_ERROR_KEYS,
  operationErrorKey,
  progressPhaseKey,
} from "../../src/i18n/operations.ts";

const catalogs = { en: en as Catalog, pt: pt as Catalog };

function i18n(locale: "en" | "pt", overrides?: Partial<typeof catalogs>) {
  const missing: string[] = [];
  const value = createI18n({
    locale,
    catalogs: { ...catalogs, ...overrides },
    onMissing: (what) => missing.push(what),
  });
  return { i18n: value, missing };
}

describe("fallback (SPEC-0014 R5)", () => {
  test("missing_pt_message_uses_english", () => {
    const ptWithout: Catalog = { ...catalogs.pt };
    delete ptWithout["search.results.count"];
    delete ptWithout["nav.search"];
    const { i18n: t } = i18n("pt", { pt: ptWithout });
    assert.equal(t.t("nav.search"), en["nav.search"]);
    // English plural rules select the form for the reused count.
    assert.equal(
      t.t("search.results.count", { count: 0, elapsedMs: 5 }),
      "0 results · 5 ms",
    );
    assert.equal(
      t.t("search.results.count", { count: 1, elapsedMs: 5 }),
      "1 result · 5 ms",
    );
  });

  test("missing_english_message_uses_generic_error_not_key", () => {
    const { i18n: t, missing } = i18n("pt");
    const key = "nav.doesNotExist" as Parameters<typeof t.t>[0];
    const text = t.t(key);
    assert.equal(text, pt["common.error.generic"]);
    assert.ok(!text.includes("nav.doesNotExist"));
    assert.deepEqual(missing, ["nav.doesNotExist"]);
  });

  test("missing_parameter_is_a_diagnostic_not_a_raw_placeholder", () => {
    const { i18n: t, missing } = i18n("en");
    const text = t.t("folders.notice.removed");
    assert.ok(!text.includes("{folder}"));
    assert.deepEqual(missing, ["folders.notice.removed:folder"]);
  });
});

describe("plurals and interpolation (SPEC-0014 R6)", () => {
  test("plural_categories_come_from_intl", () => {
    const enT = i18n("en").i18n;
    const ptT = i18n("pt").i18n;
    const counts = [0, 1, 2].map((count) => ({ count, elapsedMs: 7 }));
    assert.deepEqual(
      counts.map((v) => enT.t("search.results.count", v)),
      ["0 results · 7 ms", "1 result · 7 ms", "2 results · 7 ms"],
    );
    // CLDR classifies pt-BR zero as "one".
    assert.deepEqual(
      counts.map((v) => ptT.t("search.results.count", v)),
      ["0 resultado · 7 ms", "1 resultado · 7 ms", "2 resultados · 7 ms"],
    );
  });

  test("plural_requires_a_nonnegative_integer_count", () => {
    const { i18n: t, missing } = i18n("en");
    t.t("search.results.count", { count: -1, elapsedMs: 1 });
    t.t("search.results.count", { count: 1.5, elapsedMs: 1 });
    assert.equal(missing.length, 2);
  });

  test("interpolation_does_not_evaluate_markup", () => {
    const { i18n: t } = i18n("en");
    const text = t.t("folders.notice.removed", {
      folder: '<img src=x onerror="alert(1)">',
    });
    assert.ok(text.includes('<img src=x onerror="alert(1)">'));
    assert.ok(!/\{[a-zA-Z]+\}/.test(text));
  });
});

describe("formatting (SPEC-0014 R7)", () => {
  test("numbers_use_active_locale", () => {
    assert.equal(i18n("en").i18n.number(1234567.89), "1,234,567.89");
    assert.equal(i18n("pt").i18n.number(1234567.89), "1.234.567,89");
    assert.equal(
      i18n("pt").i18n.t("common.count.files", { count: 1234 }),
      "1.234 arquivos",
    );
  });

  test("dates_use_active_locale_and_explicit_timezone", () => {
    const epoch = 1700000000; // 2023-11-14 22:13:20 UTC
    const enText = i18n("en").i18n.dateTime(epoch, "UTC");
    const ptText = i18n("pt").i18n.dateTime(epoch, "UTC");
    assert.match(enText, /Nov 14, 2023/);
    assert.match(enText, /10:13/);
    assert.match(ptText, /14 de nov\.? de 2023/);
    assert.match(ptText, /22:13/);
    assert.match(i18n("pt").i18n.date(epoch, "UTC"), /14 de nov\.? de 2023/);
    assert.doesNotMatch(i18n("pt").i18n.date(epoch, "UTC"), /22:13/);
    assert.equal(
      i18n("en").i18n.dateTime(0, "UTC").includes("1970"),
      true,
      "epoch zero is a valid timestamp",
    );
  });

  test("bytes_use_binary_units_and_locale_number", () => {
    const enT = i18n("en").i18n;
    const ptT = i18n("pt").i18n;
    assert.equal(enT.bytes(0), "0 B");
    assert.equal(enT.bytes(1024), "1 KB");
    assert.equal(enT.bytes(1536), "1.5 KB");
    assert.equal(ptT.bytes(1536), "1,5 KB");
    assert.equal(enT.bytes(15 * 1024 * 1024), "15 MB");
    assert.equal(enT.bytes(-1), en["common.status.notAvailable"]);
    assert.equal(enT.bytes(Number.NaN), en["common.status.notAvailable"]);
  });

  test("list_uses_the_locale_unit_style", () => {
    // §4.2: Intl.ListFormat decides the separators, not English word order.
    const unit = (locale: string) =>
      new Intl.ListFormat(locale, { type: "unit", style: "short" });
    assert.equal(i18n("en").i18n.list(["a", "b", "c"]), "a, b, c");
    assert.equal(
      i18n("pt").i18n.list(["a", "b"]),
      unit("pt-BR").format(["a", "b"]),
    );
  });
});

describe("operation errors and dynamic diagnostics (SPEC-0014 R8)", () => {
  test("ipc_failures_map_to_operation_messages", () => {
    const expected = {
      refresh: "errors.status.refresh",
      search: "errors.search.failed",
      addFolder: "errors.folders.add",
      removeFolder: "errors.folders.remove",
      watch: "errors.folders.watch",
      startIndex: "errors.indexing.start",
      cancelIndex: "errors.indexing.cancel",
      probeBackend: "errors.settings.probeBackend",
      loadPreview: "errors.preview.load",
      openFile: "errors.preview.open",
    };
    assert.deepEqual(OPERATION_ERROR_KEYS, expected);
    for (const key of Object.values(expected)) {
      assert.ok(key in en, key);
      assert.ok(key in pt, key);
    }
    assert.equal(operationErrorKey("unknown"), "common.error.generic");
  });

  test("unknown_progress_phase_uses_localized_generic", () => {
    assert.equal(progressPhaseKey("scan"), "indexing.progress.scanning");
    assert.equal(progressPhaseKey("extract"), "indexing.progress.extracting");
    assert.equal(progressPhaseKey("done"), "common.state.applyingChanges");
    assert.equal(progressPhaseKey("Embedding chunk 3"), "common.state.working");
    assert.equal(progressPhaseKey(undefined), "common.state.working");
  });
});
