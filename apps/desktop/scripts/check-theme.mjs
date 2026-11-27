// Theme check for the desktop UI (SPEC-0014 §4.4, §5.4, R10, R14, R15).
// Verifies exactly two token sets with identical keys, WCAG 2.2 AA contrast
// for every declared foreground/background pair (composited, no rounding),
// and that component CSS and sources use semantic variables, not palette
// literals. Prints only token names, file names, and ratios.
import { readFile, readdir } from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { dark, light } from "../src/theme/tokens.ts";

export const THEME_NAMES = ["light", "dark"];
export const MIN_RATIO = { text: 4.5, large: 3, nontext: 3 };
/** Tokens that may be translucent; everything else must be opaque. */
export const TRANSLUCENT = new Set([
  "dangerBg",
  "warningBg",
  "successBg",
  "infoBg",
  "mark",
  "shadow",
]);

// ---------------------------------------------------------------- colors

export function parseColor(input) {
  const value = String(input).trim().toLowerCase();
  let match = /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/.exec(value);
  if (match) {
    let hex = match[1];
    if (hex.length <= 4) hex = [...hex].map((c) => c + c).join("");
    const n = (i) => parseInt(hex.slice(i, i + 2), 16);
    return { r: n(0), g: n(2), b: n(4), a: hex.length === 8 ? n(6) / 255 : 1 };
  }
  match = /^rgba?\(\s*([^)]*)\)$/.exec(value);
  if (match) {
    const parts = match[1].split(/\s*[,/]\s*|\s+/).filter(Boolean);
    if (parts.length === 3 || parts.length === 4) {
      const [r, g, b] = parts.slice(0, 3).map(Number);
      const a =
        parts.length === 4
          ? parts[3].endsWith("%")
            ? Number(parts[3].slice(0, -1)) / 100
            : Number(parts[3])
          : 1;
      const channels = [r, g, b];
      if (
        channels.every((c) => Number.isFinite(c) && c >= 0 && c <= 255) &&
        Number.isFinite(a) &&
        a >= 0 &&
        a <= 1
      ) {
        return { r, g, b, a };
      }
    }
  }
  throw new Error(`unsupported color ${JSON.stringify(input)}`);
}

/** Source-over compositing of `top` onto an opaque `bottom`. */
export function composite(top, bottom) {
  const a = top.a;
  return {
    r: top.r * a + bottom.r * (1 - a),
    g: top.g * a + bottom.g * (1 - a),
    b: top.b * a + bottom.b * (1 - a),
    a: 1,
  };
}

/** Composites token layers bottom-to-top; the first layer must be opaque. */
export function flatten(theme, layers) {
  let result = null;
  for (const name of layers) {
    if (!(name in theme)) throw new Error(`unknown token ${name}`);
    const color = parseColor(theme[name]);
    if (result === null) {
      if (color.a !== 1) throw new Error(`${name} is not an opaque surface`);
      result = color;
    } else {
      result = composite(color, result);
    }
  }
  if (result === null) throw new Error("empty layer list");
  return result;
}

function channel(value) {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance({ r, g, b }) {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a, b) {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort(
    (x, y) => y - x,
  );
  return (hi + 0.05) / (lo + 0.05);
}

// ------------------------------------------------------------ pair matrix
//
// Every semantic foreground/background combination the CSS uses (§4.4).
// `on` lists surfaces bottom-to-top; translucent layers are composited.
// Rules: text 4.5:1 (R14, no large-text relief is claimed), non-text 3:1
// (R15). Disabled text and `shadow` are exempt (§4.4) and inspected
// manually.

function pairs(kind, where, fgs, surfaces) {
  const out = [];
  for (const on of surfaces) {
    const layers = Array.isArray(on) ? on : [on];
    for (const fg of fgs) out.push({ fg, on: layers, kind, where });
  }
  return out;
}

const CARD_TEXT = ["text", "muted", "subtle", "accentText", "accentSecondary"];
const STATE_SURFACES = ["panel", "hover", "selected"];
const TAGS = [
  ["warning", "warningBg"],
  ["success", "successBg"],
  ["info", "infoBg"],
];

export const TEXT_PAIRS = [
  ...pairs(
    "text",
    "sidebar: brand, nav, tagline, footer",
    ["text", "muted", "subtle", "accentText"],
    ["sidebar"],
  ),
  ...pairs("text", "nav item hover/active", ["text"], ["hover", "selected"]),
  ...pairs(
    "text",
    "sidebar backend card",
    ["text", "muted", "subtle"],
    ["panel"],
  ),
  ...pairs(
    "text",
    "page background: hero, headings, results head, cells",
    [...CARD_TEXT, "danger"],
    ["bg"],
  ),
  ...pairs(
    "text",
    "search input and placeholder",
    ["text", "placeholder"],
    ["input"],
  ),
  ...pairs(
    "text",
    "buttons and controls on hover",
    ["text", "muted"],
    ["hover"],
  ),
  ...pairs(
    "text",
    "primary button and brand mark",
    ["onAccent"],
    ["accent", "accentHover"],
  ),
  ...pairs("text", "error banner", ["danger"], [["bg", "dangerBg"]]),
  ...pairs("text", "notice banner", ["success"], [["bg", "successBg"]]),
  ...pairs(
    "text",
    "cards, results, health, settings",
    [...CARD_TEXT, "danger"],
    ["panel"],
  ),
  ...pairs("text", "hovered/selected results and backend options", CARD_TEXT, [
    "hover",
    "selected",
  ]),
  ...pairs("text", "select control", ["text"], ["panelRaised"]),
  ...pairs("text", "result/root icon tiles", ["accentText"], ["panelRaised"]),
  ...pairs(
    "text",
    "marked query terms",
    ["onMark"],
    [
      ["panel", "mark"],
      ["hover", "mark"],
      ["selected", "mark"],
      ["preview", "mark"],
    ],
  ),
  ...TAGS.flatMap(([fg, tint]) =>
    pairs(
      "text",
      "match tags, watch toggle, health state",
      [fg],
      STATE_SURFACES.map((surface) => [surface, tint]),
    ),
  ),
  ...pairs(
    "text",
    "preview pane",
    ["text", "muted", "subtle", "accentSecondary"],
    ["preview"],
  ),
  ...pairs("text", "status bar", ["text", "muted", "subtle"], ["statusbar"]),
];

const FOCUS_SURFACES = [
  "bg",
  "sidebar",
  "panel",
  "panelRaised",
  "preview",
  "input",
  "hover",
  "selected",
  "statusbar",
];

export const NONTEXT_PAIRS = [
  ...pairs(
    "nontext",
    "keyboard focus indicator",
    ["focusRing"],
    FOCUS_SURFACES,
  ),
  ...pairs(
    "nontext",
    "input and select boundaries",
    ["borderStrong"],
    ["bg", "panel", "panelRaised", "input"],
  ),
  ...pairs(
    "nontext",
    "selected-state indicators, resizer, spinner, primary button shape",
    ["accent"],
    ["bg", "sidebar", "panel", "preview", "selected"],
  ),
  ...pairs(
    "nontext",
    "progress fill against its track",
    ["accent"],
    ["border"],
  ),
  ...pairs(
    "nontext",
    "meaningful icons",
    ["muted"],
    ["input", "hover", "panel", "preview", "bg"],
  ),
  ...pairs(
    "nontext",
    "icon tiles and callout icon",
    ["accentText"],
    ["panelRaised"],
  ),
  ...pairs("nontext", "callout icon", ["accentSecondary"], ["panel"]),
];

/**
 * Declared but exempt from ratios: disabled text (WCAG 1.4.3 exception,
 * §4.4). It must stay distinguishable and is inspected manually.
 */
export const EXEMPT_PAIRS = pairs(
  "exempt",
  "disabled controls",
  ["onDisabled"],
  ["disabled"],
);

// ------------------------------------------------------------- checks

export function checkTokens(themes) {
  const errors = [];
  const names = Object.keys(themes).sort();
  if (names.join() !== [...THEME_NAMES].sort().join()) {
    errors.push(`themes must be exactly ${THEME_NAMES.join(", ")}`);
  }
  const reference = themes[names[0]] ?? {};
  for (const name of names) {
    const theme = themes[name];
    for (const key of Object.keys(reference)) {
      if (!(key in theme)) errors.push(`${name}: missing token ${key}`);
    }
    for (const [key, value] of Object.entries(theme)) {
      if (!(key in reference)) errors.push(`${name}: extra token ${key}`);
      try {
        const color = parseColor(value);
        if (color.a !== 1 && !TRANSLUCENT.has(key)) {
          errors.push(`${name}: ${key} must be opaque`);
        }
      } catch {
        errors.push(`${name}: ${key} is not a supported color`);
      }
    }
  }
  return errors;
}

export function checkContrast(themes, pairList) {
  const errors = [];
  for (const [name, theme] of Object.entries(themes)) {
    for (const pair of pairList) {
      let ratio;
      try {
        const backdrop = flatten(theme, pair.on);
        const fg = composite(parseColor(theme[pair.fg]), backdrop);
        ratio = contrastRatio(fg, backdrop);
      } catch (error) {
        errors.push(`${name}: ${pair.fg} on ${pair.on.join("+")}: ${error}`);
        continue;
      }
      const min = MIN_RATIO[pair.kind];
      if (!(ratio >= min)) {
        errors.push(
          `${name}: ${pair.fg} on ${pair.on.join("+")} is ` +
            `${ratio.toFixed(3)}:1, needs ${min}:1 (${pair.where})`,
        );
      }
    }
  }
  return errors;
}

// CSS named colors (CSS Color 4). `transparent` and `currentColor` are
// keywords, not palette entries, and stay allowed.
const NAMED_COLORS = new Set(
  (
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black " +
    "blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse " +
    "chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan " +
    "darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta " +
    "darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen " +
    "darkslateblue darkslategray darkslategrey darkturquoise darkviolet " +
    "deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite " +
    "forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green " +
    "greenyellow grey honeydew hotpink indianred indigo ivory khaki " +
    "lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral " +
    "lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink " +
    "lightsalmon lightseagreen lightskyblue lightslategray lightslategrey " +
    "lightsteelblue lightyellow lime limegreen linen magenta maroon " +
    "mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen " +
    "mediumslateblue mediumspringgreen mediumturquoise mediumvioletred " +
    "midnightblue mintcream mistyrose moccasin navajowhite navy oldlace " +
    "olive olivedrab orange orangered orchid palegoldenrod palegreen " +
    "paleturquoise palevioletred papayawhip peru pink plum powderblue " +
    "purple rebeccapurple red rosybrown royalblue saddlebrown salmon " +
    "sandybrown seagreen seashell sienna silver skyblue slateblue slategray " +
    "slategrey snow springgreen steelblue tan teal thistle tomato turquoise " +
    "violet wheat white whitesmoke yellow yellowgreen"
  ).split(" "),
);
const COLOR_FUNCTION = /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(/i;
const HEX = /#[0-9a-fA-F]{3,8}\b/;
const TOKEN_REF = /var\(\s*--color-([A-Za-z0-9]+)\s*[,)]/g;

function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** Yields `{ selector, declarations: [[property, value]] }` per rule. */
function* rules(css) {
  const pattern = /([^{}]+)\{([^{}]*)\}/g;
  for (const match of stripComments(css).matchAll(pattern)) {
    const declarations = match[2]
      .split(";")
      .map((d) => d.trim())
      .filter(Boolean)
      .map((d) => {
        const i = d.indexOf(":");
        return [d.slice(0, i).trim().toLowerCase(), d.slice(i + 1).trim()];
      });
    yield { selector: match[1].trim(), declarations };
  }
}

function singleToken(value) {
  const match = /^var\(\s*--color-([A-Za-z0-9]+)\s*\)$/.exec(value.trim());
  return match ? match[1] : null;
}

/**
 * Component CSS rules: no palette literals, only known `--color-*` tokens,
 * and a rule that sets both a token color and a token background must use a
 * declared text pair.
 */
export function checkCss(css, tokenKeys, pairList, file = "css") {
  const errors = [];
  const known = new Set(tokenKeys);
  const declared = new Set(
    pairList.map((pair) => `${pair.fg}|${pair.on.at(-1)}`),
  );
  for (const rule of rules(css)) {
    let fg = null;
    let bg = null;
    for (const [property, value] of rule.declarations) {
      const where = `${file}: ${rule.selector} { ${property} }`;
      if (HEX.test(value) || COLOR_FUNCTION.test(value)) {
        errors.push(`${where}: palette literal; use a --color-* token`);
      } else {
        const words = value.toLowerCase().match(/[a-z]+/g) ?? [];
        if (words.some((word) => NAMED_COLORS.has(word))) {
          errors.push(`${where}: named color; use a --color-* token`);
        }
      }
      for (const [, token] of value.matchAll(TOKEN_REF)) {
        if (!known.has(token)) errors.push(`${where}: unknown token ${token}`);
      }
      if (property === "color") fg = singleToken(value);
      if (property === "background" || property === "background-color") {
        bg = singleToken(value);
      }
    }
    if (fg && bg && !declared.has(`${fg}|${bg}`)) {
      errors.push(
        `${file}: ${rule.selector}: ${fg} on ${bg} is not a declared pair`,
      );
    }
  }
  return errors;
}

/** TypeScript sources: palette literals only in theme/tokens.ts. */
export async function checkSources(sourceDir) {
  const errors = [];
  const tokensFile = join(sourceDir, "theme", "tokens.ts");
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) await walk(path);
      else if (/\.tsx?$/.test(entry.name) && path !== tokensFile) {
        const text = await readFile(path, "utf8");
        text.split("\n").forEach((line, index) => {
          if (HEX.test(line) || COLOR_FUNCTION.test(line)) {
            errors.push(
              `${relative(sourceDir, path)}:${index + 1}: palette literal`,
            );
          }
        });
      }
    }
  }
  await walk(sourceDir);
  return errors;
}

export async function runCheck({ cssFiles, sourceDir, themes }) {
  const sets = themes ?? { light, dark };
  const errors = [...checkTokens(sets)];
  if (errors.length === 0) {
    errors.push(...checkContrast(sets, TEXT_PAIRS));
    errors.push(...checkContrast(sets, NONTEXT_PAIRS));
  }
  const keys = Object.keys(sets.light ?? {});
  for (const file of cssFiles) {
    const css = await readFile(file, "utf8");
    const declared = [...TEXT_PAIRS, ...EXEMPT_PAIRS];
    errors.push(
      ...checkCss(css, keys, declared, relative(process.cwd(), file)),
    );
  }
  if (sourceDir) errors.push(...(await checkSources(sourceDir)));
  return { errors };
}

async function main() {
  const desktop = join(dirname(fileURLToPath(import.meta.url)), "..");
  const src = join(desktop, "src");
  const cssFiles = (await readdir(src, { recursive: true }))
    .filter((name) => name.endsWith(".css"))
    .map((name) => join(src, name));
  const { errors } = await runCheck({ cssFiles, sourceDir: src });
  if (errors.length) {
    for (const error of errors) console.error(error);
    console.error(`theme:check failed with ${errors.length} error(s).`);
    process.exit(1);
  }
  console.log(
    `theme:check passed: 2 themes, ${TEXT_PAIRS.length} text and ` +
      `${NONTEXT_PAIRS.length} non-text pairs per theme, ` +
      `${cssFiles.length} CSS file(s).`,
  );
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  await main();
}
