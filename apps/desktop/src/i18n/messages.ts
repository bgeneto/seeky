// Catalog lookup, plural selection, interpolation, and fallback
// (SPEC-0014 §4.1, §5.1, R1, R5, R6, R7).
import {
  byteParts,
  formatDate,
  formatList,
  formatNumber,
  pluralCategory,
} from "./format.ts";
import { formattingLocale, type CatalogLocale } from "./locale.ts";

type EnCatalog = typeof import("./locales/en.json");
export type MessageKey = keyof EnCatalog;
export type MessageValues = Record<string, string | number>;
export type Catalog = Record<string, string | Record<string, string>>;

export interface I18n {
  readonly locale: CatalogLocale;
  t(key: MessageKey, values?: MessageValues): string;
  number(value: number, options?: Intl.NumberFormatOptions): string;
  dateTime(epochSeconds: number, timeZone?: string): string;
  date(epochSeconds: number, timeZone?: string): string;
  bytes(bytes: number): string;
  list(items: readonly string[]): string;
}

export interface I18nOptions {
  locale: CatalogLocale;
  catalogs: Record<CatalogLocale, Catalog>;
  /** Developer diagnostic; receives only a key or `key:parameter`. */
  onMissing?: (what: string) => void;
}

const PLACEHOLDER = /\{([a-z][A-Za-z0-9]*)\}/g;
const GENERIC = "common.error.generic";

export function createI18n({
  locale,
  catalogs,
  onMissing = () => undefined,
}: I18nOptions): I18n {
  const intlLocale = formattingLocale(locale);
  const number = (value: number, options?: Intl.NumberFormatOptions) =>
    formatNumber(intlLocale, value, options);

  /** One form of `key` from `catalog`, or undefined when unavailable. */
  function form(
    catalog: Catalog,
    key: string,
    rulesLocale: string,
    values: MessageValues | undefined,
  ): string | undefined {
    const entry = catalog[key];
    if (typeof entry === "string") return entry;
    if (entry === undefined || entry === null) return undefined;
    const count = values?.count;
    if (typeof count !== "number" || !Number.isInteger(count) || count < 0) {
      onMissing(`${key}:count`);
      return undefined;
    }
    const chosen = entry[pluralCategory(rulesLocale, count)] ?? entry.other;
    return typeof chosen === "string" ? chosen : undefined;
  }

  function generic(): string {
    const own = catalogs[locale][GENERIC];
    const fallback = catalogs.en[GENERIC];
    if (typeof own === "string") return own;
    return typeof fallback === "string" ? fallback : "";
  }

  function interpolate(key: string, text: string, values?: MessageValues) {
    let missing = false;
    const out = text.replace(PLACEHOLDER, (_, name: string) => {
      const value = values?.[name];
      if (value === undefined) {
        missing = true;
        onMissing(`${key}:${name}`);
        return "";
      }
      return typeof value === "number" ? number(value) : value;
    });
    return missing ? generic() : out;
  }

  function t(key: MessageKey, values?: MessageValues): string {
    let text = form(catalogs[locale], key, intlLocale, values);
    if (text === undefined && locale !== "en") {
      text = form(catalogs.en, key, "en", values);
    }
    if (text === undefined) {
      if (!(key in catalogs.en)) onMissing(key);
      return generic();
    }
    return interpolate(key, text, values);
  }

  return {
    locale,
    t,
    number,
    dateTime: (epochSeconds, timeZone) =>
      formatDate(intlLocale, epochSeconds, true, timeZone),
    date: (epochSeconds, timeZone) =>
      formatDate(intlLocale, epochSeconds, false, timeZone),
    bytes(bytes) {
      const parts = byteParts(intlLocale, bytes);
      if (!parts) return t("common.status.notAvailable");
      const unitKey = `common.unit.${parts.unit}` as MessageKey;
      return `${parts.value} ${t(unitKey)}`;
    },
    list: (items) => formatList(intlLocale, items),
  };
}
