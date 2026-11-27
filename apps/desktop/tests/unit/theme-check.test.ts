// SPEC-0014 R10, R14, R15: contrast math, the declared pair matrix, and the
// component-CSS palette rule enforced by `npm run theme:check`.
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, test } from "node:test";

import {
  NONTEXT_PAIRS,
  TEXT_PAIRS,
  checkContrast,
  checkCss,
  checkTokens,
  contrastRatio,
  flatten,
  parseColor,
  runCheck,
} from "../../scripts/check-theme.mjs";
import { dark, light } from "../../src/theme/tokens.ts";

const desktop = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const themes = { light, dark };

const temps: string[] = [];
afterEach(() => {
  for (const dir of temps.splice(0))
    rmSync(dir, { recursive: true, force: true });
});

function cssFixture(css: string): string {
  const root = mkdtempSync(join(tmpdir(), "seeky-theme-"));
  temps.push(root);
  const file = join(root, "view.css");
  writeFileSync(file, css);
  return file;
}

describe("contrast math (SPEC-0014 R14)", () => {
  test("contrast_black_white_is_21", () => {
    assert.equal(contrastRatio(parseColor("#000"), parseColor("#fff")), 21);
    assert.equal(
      contrastRatio(parseColor("#ffffff"), parseColor("rgb(0, 0, 0)")),
      21,
    );
    assert.equal(contrastRatio(parseColor("#777"), parseColor("#777")), 1);
    // Known value: #767676 on white is the classic 4.54:1.
    const grey = contrastRatio(parseColor("#767676"), parseColor("#fff"));
    assert.ok(grey > 4.5 && grey < 4.6, String(grey));
  });

  test("no_rounding_up_at_the_threshold", () => {
    const fixture = {
      t: { bg: "#ffffff", text: "#777777" }, // 4.48:1 rounds to 4.5 but fails
    };
    const errors = checkContrast(fixture, [
      { fg: "text", on: ["bg"], kind: "text", where: "fixture" },
    ]);
    assert.equal(errors.length, 1);
    assert.match(errors[0], /4\.4\d/);
  });

  test("alpha_tokens_are_composited_before_contrast", () => {
    // 50% white over black is mid grey (#808080), not white.
    const mid = flatten({ base: "#000000", veil: "rgba(255,255,255,0.5)" }, [
      "base",
      "veil",
    ]);
    assert.deepEqual(
      [mid.r, mid.g, mid.b].map((v) => Math.round(v)),
      [128, 128, 128],
    );
    assert.equal(mid.a, 1);

    // White text passes on the veil's raw color only if alpha is ignored.
    const theme = {
      t: { base: "#000000", veil: "rgba(255,255,255,0.5)", text: "#ffffff" },
    };
    const errors = checkContrast(theme, [
      { fg: "text", on: ["base", "veil"], kind: "text", where: "fixture" },
    ]);
    assert.equal(errors.length, 1);

    // A translucent foreground is composited over its backdrop too.
    const ghost = {
      t: { base: "#ffffff", text: "rgba(0,0,0,0.2)" },
    };
    assert.equal(
      checkContrast(ghost, [
        { fg: "text", on: ["base"], kind: "nontext", where: "fixture" },
      ]).length,
      1,
    );

    // A pair must start from an opaque surface.
    assert.throws(() => flatten({ veil: "rgba(0,0,0,0.5)" }, ["veil"]));
  });

  test("text_token_pairs_meet_aa_in_both_themes", () => {
    assert.ok(TEXT_PAIRS.length > 0);
    for (const pair of TEXT_PAIRS) {
      assert.ok(pair.kind === "text" || pair.kind === "large");
    }
    // Every text role and state named in R14 is covered by the matrix.
    const fgs = new Set(TEXT_PAIRS.map((pair: { fg: string }) => pair.fg));
    for (const role of [
      "text",
      "muted",
      "subtle",
      "placeholder",
      "onAccent",
      "onMark",
      "accentText",
      "accentSecondary",
      "danger",
      "warning",
      "success",
      "info",
    ]) {
      assert.ok(fgs.has(role), `no text pair for ${role}`);
    }
    const surfaces = new Set(
      TEXT_PAIRS.flatMap((pair: { on: string[] }) => pair.on),
    );
    for (const state of ["hover", "selected", "mark", "dangerBg", "input"]) {
      assert.ok(surfaces.has(state), `no text pair on ${state}`);
    }
    assert.deepEqual(checkContrast(themes, TEXT_PAIRS), []);
  });
});

describe("non-text contrast (SPEC-0014 R15)", () => {
  test("nontext_token_pairs_meet_aa_in_both_themes", () => {
    assert.ok(NONTEXT_PAIRS.length > 0);
    const fgs = new Set(NONTEXT_PAIRS.map((pair: { fg: string }) => pair.fg));
    for (const role of ["focusRing", "borderStrong", "accent"]) {
      assert.ok(fgs.has(role), `no non-text pair for ${role}`);
    }
    // The focus ring is checked against every surface it can sit on.
    const focusSurfaces = NONTEXT_PAIRS.filter(
      (pair: { fg: string }) => pair.fg === "focusRing",
    ).map((pair: { on: string[] }) => pair.on.at(-1));
    for (const surface of [
      "bg",
      "sidebar",
      "panel",
      "preview",
      "input",
      "hover",
      "selected",
      "statusbar",
    ]) {
      assert.ok(focusSurfaces.includes(surface), `focus on ${surface}`);
    }
    assert.deepEqual(checkContrast(themes, NONTEXT_PAIRS), []);
  });

  test("nontext_pairs_fail_below_three", () => {
    const errors = checkContrast({ t: { bg: "#ffffff", ring: "#a0a0a0" } }, [
      { fg: "ring", on: ["bg"], kind: "nontext", where: "fixture" },
    ]);
    assert.equal(errors.length, 1);
  });
});

describe("token sets and component CSS (SPEC-0014 R10)", () => {
  test("token_check_rejects_mismatched_or_invalid_sets", () => {
    assert.deepEqual(checkTokens(themes), []);
    assert.equal(
      checkTokens({ light: { bg: "#fff", text: "#000" }, dark: { bg: "#000" } })
        .length,
      1,
    );
    assert.ok(
      checkTokens({ light: { bg: "nope" }, dark: { bg: "#000" } }).length > 0,
    );
    assert.ok(
      checkTokens({ light: { bg: "#fff" }, dark: { bg: "#000" }, sepia: {} })
        .length > 0,
      "exactly two themes",
    );
  });

  test("css_check_rejects_palette_literals_and_unknown_tokens", () => {
    const keys = Object.keys(light);
    const errors = checkCss(
      [
        ".a { color: #fff; }",
        ".b { background: rgba(0, 0, 0, 0.5); }",
        ".c { border-color: white; }",
        ".d { color: var(--color-nope); }",
        ".e { color: var(--color-text); white-space: nowrap; }",
        ".f { background: transparent; color: currentColor; }",
      ].join("\n"),
      keys,
      [],
    );
    assert.equal(errors.length, 4, errors.join("\n"));
  });

  test("css_check_rejects_unlisted_foreground_background_rule", () => {
    const keys = Object.keys(light);
    const css =
      ".x { color: var(--color-subtle); background: var(--color-accent); }";
    assert.equal(checkCss(css, keys, TEXT_PAIRS).length, 1);
    const listed =
      ".y { color: var(--color-onAccent); background: var(--color-accent); }";
    assert.deepEqual(checkCss(listed, keys, TEXT_PAIRS), []);
  });

  test("real_theme_passes_the_check", async () => {
    const result = await runCheck({
      cssFiles: [join(desktop, "src", "App.css")],
      sourceDir: join(desktop, "src"),
    });
    assert.deepEqual(result.errors, []);
  });

  test("run_check_reports_literals_in_a_css_file", async () => {
    const file = cssFixture(".z { color: #123456; }");
    const result = await runCheck({ cssFiles: [file], sourceDir: null });
    assert.equal(result.errors.length, 1);
  });
});
