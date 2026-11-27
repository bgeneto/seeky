// Catalog parity check for the desktop UI (SPEC-0014 §5.3, R1, R2, R5, R9).
// Prints only catalog keys, file names, and mismatch reasons; never user data.
import { readFile, readdir } from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const KEY_PATTERN = /^[a-z][a-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+$/;
export const NAMESPACES = new Set([
  "common",
  "window",
  "nav",
  "search",
  "folders",
  "settings",
  "preview",
  "indexing",
  "status",
  "errors",
]);
export const PLURAL_CATEGORIES = ["one", "other"];
const PLACEHOLDER = /\{([a-z][A-Za-z0-9]*)\}/g;
const LITERAL_CALL = /(?<![\w.$])t\(\s*(["'])([^"'\n]+)\1/g;

export function placeholders(text) {
  return [...new Set([...text.matchAll(PLACEHOLDER)].map((m) => m[1]))].sort();
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function kindOf(value) {
  if (typeof value === "string") return "string";
  if (isPlainObject(value)) return "plural";
  return "invalid";
}

function validateCatalog(name, catalog, errors) {
  if (!isPlainObject(catalog)) {
    errors.push(`${name}: catalog must be a flat JSON object`);
    return;
  }
  for (const [key, value] of Object.entries(catalog)) {
    if (!KEY_PATTERN.test(key)) {
      errors.push(`${name}: ${key}: key does not match the key grammar`);
    } else if (!NAMESPACES.has(key.split(".")[0])) {
      errors.push(`${name}: ${key}: unknown namespace`);
    }
    const kind = kindOf(value);
    if (kind === "invalid") {
      errors.push(`${name}: ${key}: value must be a string or plural object`);
    } else if (kind === "string") {
      if (value.trim() === "") errors.push(`${name}: ${key}: empty message`);
    } else {
      const categories = Object.keys(value).sort();
      if (categories.join() !== [...PLURAL_CATEGORIES].sort().join()) {
        errors.push(
          `${name}: ${key}: plural categories must be exactly ${PLURAL_CATEGORIES.join(", ")}`,
        );
      }
      for (const [category, form] of Object.entries(value)) {
        if (typeof form !== "string" || form.trim() === "") {
          errors.push(`${name}: ${key}.${category}: empty plural form`);
        }
      }
    }
  }
  if (!Object.hasOwn(catalog, "common.error.generic")) {
    errors.push(`${name}: common.error.generic: mandatory key is missing`);
  }
}

function forms(value) {
  if (typeof value === "string") return { "": value };
  return isPlainObject(value) ? value : {};
}

/** Compares two parsed catalogs and returns human-readable errors. */
export function checkCatalogs(en, pt) {
  const errors = [];
  validateCatalog("en", en, errors);
  validateCatalog("pt", pt, errors);
  if (!isPlainObject(en) || !isPlainObject(pt)) return errors;
  for (const key of Object.keys(en)) {
    if (!Object.hasOwn(pt, key)) errors.push(`pt: ${key}: missing key`);
  }
  for (const key of Object.keys(pt)) {
    if (!Object.hasOwn(en, key)) errors.push(`en: ${key}: missing key`);
  }
  for (const key of Object.keys(en)) {
    if (!Object.hasOwn(pt, key)) continue;
    const a = en[key];
    const b = pt[key];
    if (kindOf(a) !== kindOf(b)) {
      errors.push(
        `${key}: message kind differs (${kindOf(a)} vs ${kindOf(b)})`,
      );
      continue;
    }
    const enForms = forms(a);
    const ptForms = forms(b);
    const categories = new Set([
      ...Object.keys(enForms),
      ...Object.keys(ptForms),
    ]);
    for (const category of categories) {
      const label = category ? `${key}.${category}` : key;
      if (typeof enForms[category] !== "string") {
        errors.push(`en: ${label}: missing plural category`);
        continue;
      }
      if (typeof ptForms[category] !== "string") {
        errors.push(`pt: ${label}: missing plural category`);
        continue;
      }
      const left = placeholders(enForms[category]).join(",");
      const right = placeholders(ptForms[category]).join(",");
      if (left !== right) {
        errors.push(`${label}: placeholders differ ({${left}} vs {${right}})`);
      }
    }
  }
  return errors;
}

/** Returns the literal keys passed to t("…") in a source text. */
export function literalKeys(source) {
  return [...source.matchAll(LITERAL_CALL)].map((m) => m[2]);
}

async function sourceFiles(dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await sourceFiles(path)));
    else if (/\.(?:ts|tsx)$/.test(entry.name)) out.push(path);
  }
  return out;
}

async function readCatalog(localesDir, name, errors) {
  try {
    return JSON.parse(await readFile(join(localesDir, `${name}.json`), "utf8"));
  } catch {
    errors.push(`${name}.json: missing or invalid JSON`);
    return null;
  }
}

/** Runs every §5.3 check against catalogs and sources on disk. */
export async function runCheck({ localesDir, srcDir }) {
  const errors = [];
  const en = await readCatalog(localesDir, "en", errors);
  const pt = await readCatalog(localesDir, "pt", errors);
  if (en === null || pt === null) return errors;
  errors.push(...checkCatalogs(en, pt));
  if (isPlainObject(en)) {
    for (const file of await sourceFiles(srcDir)) {
      const text = await readFile(file, "utf8");
      for (const key of literalKeys(text)) {
        if (!Object.hasOwn(en, key)) {
          const where = relative(srcDir, file).replaceAll("\\", "/");
          errors.push(`${where}: ${key}: referenced key is not in en.json`);
        }
      }
    }
  }
  return errors;
}

const invokedDirectly =
  process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) {
  const desktop = join(dirname(fileURLToPath(import.meta.url)), "..");
  const errors = await runCheck({
    localesDir: join(desktop, "src", "i18n", "locales"),
    srcDir: join(desktop, "src"),
  });
  if (errors.length) {
    for (const error of errors) console.error(error);
    console.error(`i18n check failed: ${errors.length} problem(s)`);
    process.exit(1);
  }
  console.log("i18n check passed");
}
