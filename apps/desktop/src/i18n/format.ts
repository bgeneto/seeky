// Locale-explicit formatting with cached Intl instances (SPEC-0014 §4.2, R7).

const numberCache = new Map<string, Intl.NumberFormat>();
const dateCache = new Map<string, Intl.DateTimeFormat>();
const listCache = new Map<string, Intl.ListFormat>();
const pluralCache = new Map<string, Intl.PluralRules>();

function cached<T>(cache: Map<string, T>, key: string, make: () => T): T {
  let value = cache.get(key);
  if (value === undefined) {
    value = make();
    cache.set(key, value);
  }
  return value;
}

export function formatNumber(
  locale: string,
  value: number,
  options: Intl.NumberFormatOptions = {},
): string {
  const key = `${locale}|${JSON.stringify(options)}`;
  return cached(
    numberCache,
    key,
    () => new Intl.NumberFormat(locale, options),
  ).format(value);
}

export function formatDate(
  locale: string,
  epochSeconds: number,
  withTime: boolean,
  timeZone?: string,
): string {
  const key = `${locale}|${withTime}|${timeZone ?? ""}`;
  const format = cached(
    dateCache,
    key,
    () =>
      new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        ...(withTime ? { timeStyle: "short" } : {}),
        ...(timeZone ? { timeZone } : {}),
      }),
  );
  return format.format(new Date(epochSeconds * 1000));
}

export function formatList(locale: string, items: readonly string[]): string {
  return cached(
    listCache,
    locale,
    () => new Intl.ListFormat(locale, { type: "unit", style: "short" }),
  ).format(items);
}

export function pluralCategory(locale: string, count: number): string {
  return cached(pluralCache, locale, () => new Intl.PluralRules(locale)).select(
    count,
  );
}

export const BYTE_UNITS = ["byte", "kilobyte", "megabyte", "gigabyte"] as const;
export type ByteUnit = (typeof BYTE_UNITS)[number];

/** Splits a byte count into a localized number and a binary unit, or null. */
export function byteParts(
  locale: string,
  bytes: number,
): { value: string; unit: ByteUnit } | null {
  if (!Number.isFinite(bytes) || bytes < 0) return null;
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const fraction = unit > 0 && value < 10 ? 1 : 0;
  return {
    value: formatNumber(locale, value, {
      minimumFractionDigits: 0,
      maximumFractionDigits: fraction,
    }),
    unit: BYTE_UNITS[unit],
  };
}
