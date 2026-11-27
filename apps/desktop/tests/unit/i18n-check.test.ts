// SPEC-0014 R1, R2, R5, R6, R9: catalog parity checker and real catalogs.
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, test } from "node:test";

import { checkCatalogs, runCheck } from "../../scripts/check-i18n.mjs";

const desktop = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const realLocales = join(desktop, "src", "i18n", "locales");
const realSrc = join(desktop, "src");

const temps: string[] = [];
afterEach(() => {
  for (const dir of temps.splice(0))
    rmSync(dir, { recursive: true, force: true });
});

function fixture(
  en: Record<string, unknown>,
  pt: Record<string, unknown>,
  source = "",
): { localesDir: string; srcDir: string } {
  const root = mkdtempSync(join(tmpdir(), "seeky-i18n-"));
  temps.push(root);
  const localesDir = join(root, "locales");
  const srcDir = join(root, "src");
  mkdirSync(localesDir);
  mkdirSync(srcDir);
  writeFileSync(join(localesDir, "en.json"), JSON.stringify(en));
  writeFileSync(join(localesDir, "pt.json"), JSON.stringify(pt));
  writeFileSync(join(srcDir, "view.tsx"), source);
  return { localesDir, srcDir };
}

const base = {
  "common.error.generic": "Something went wrong.",
  "search.results.count": { one: "{count} result", other: "{count} results" },
};
const basePt = {
  "common.error.generic": "Algo deu errado.",
  "search.results.count": {
    one: "{count} resultado",
    other: "{count} resultados",
  },
};

describe("catalog parity (SPEC-0014 R1, R9)", () => {
  test("catalogs_have_identical_flat_keys_and_shapes", async () => {
    // SPEC-0014-R1, R9: the shipped catalogs pass the same check CI runs.
    const errors = await runCheck({
      localesDir: realLocales,
      srcDir: realSrc,
    });
    assert.deepEqual(errors, []);
  });

  test("catalog_values_are_nonempty_and_valid", () => {
    // SPEC-0014-R1, R9: key grammar, namespaces, and message kinds.
    const errors = checkCatalogs(
      { ...base, "Bad.key": "x", "unknown.space": "x", "nav.list": ["a"] },
      { ...basePt, "Bad.key": "x", "unknown.space": "x", "nav.list": ["a"] },
    );
    assert.ok(errors.some((e) => e.includes("Bad.key")));
    assert.ok(errors.some((e) => e.includes("unknown.space")));
    assert.ok(errors.some((e) => e.includes("nav.list")));
  });

  test("parity_checker_rejects_missing_extra_and_mismatched_keys", () => {
    // SPEC-0014-R9: missing, extra, and kind mismatches all fail.
    const errors = checkCatalogs(
      { ...base, "nav.search": "Search", "nav.folders": "Files" },
      {
        ...basePt,
        "nav.search": { one: "a", other: "b" },
        "nav.settings": "Ajustes",
      },
    );
    assert.ok(errors.some((e) => e.includes("nav.folders")));
    assert.ok(errors.some((e) => e.includes("nav.settings")));
    assert.ok(errors.some((e) => e.includes("nav.search")));
  });

  test("parity_checker_rejects_missing_english_key", () => {
    // SPEC-0014-R5, R9: a key only in pt and a missing generic both fail.
    const errors = checkCatalogs(
      { "search.results.count": base["search.results.count"] },
      { ...basePt },
    );
    assert.ok(errors.some((e) => e.includes("common.error.generic")));
    assert.notEqual(errors.length, 0);
  });

  test("parity_checker_rejects_empty_messages", () => {
    // SPEC-0014-R9: empty strings and empty plural forms fail.
    const errors = checkCatalogs(
      { ...base, "nav.search": "" },
      {
        ...basePt,
        "nav.search": "Busca",
        "search.results.count": { one: " ", other: "{count}" },
      },
    );
    assert.ok(errors.some((e) => e.includes("nav.search")));
    assert.ok(errors.some((e) => e.includes("search.results.count")));
  });

  test("plural_placeholders_match_across_catalogs", () => {
    // SPEC-0014-R6, R9: per-category placeholder and category parity.
    const errors = checkCatalogs(
      {
        ...base,
        "status.watching": { one: "{count} folder", other: "{count} folders" },
      },
      {
        ...basePt,
        "status.watching": { one: "{total} pasta", other: "{count} pastas" },
      },
    );
    assert.ok(errors.some((e) => e.includes("status.watching")));
    const categories = checkCatalogs(
      { ...base },
      { ...basePt, "search.results.count": { other: "{count}" } },
    );
    assert.ok(categories.some((e) => e.includes("search.results.count")));
  });

  test("literal_translation_references_exist", async () => {
    // SPEC-0014-R2, R9: every literal t("…") must name an English key.
    const ok = fixture(base, basePt, 'const a = t("common.error.generic");');
    assert.deepEqual(await runCheck(ok), []);
    const bad = fixture(base, basePt, "const a = t('nav.missing');");
    const errors = await runCheck(bad);
    assert.ok(errors.some((e) => e.includes("nav.missing")));
  });

  test("invalid_json_is_reported_without_content", async () => {
    // SPEC-0014-R9: invalid JSON fails with the file name only.
    const dirs = fixture(base, basePt);
    writeFileSync(join(dirs.localesDir, "pt.json"), "{ not json");
    const errors = await runCheck(dirs);
    assert.ok(errors.some((e) => e.includes("pt.json")));
  });
});
