# SPEC-0014 — Desktop experience (v1: localization and themes)

| Field | Value |
|---|---|
| Status | Draft |
| Version | 0.1 (desktop experience v1) |
| Owner | Maintainer |
| Phase / work packages | Phase 7 — WP-7.1, WP-7.2 |
| Crates touched | `seeky-desktop` only (`apps/desktop` React UI and Tauri shell); no engine crate |
| Governing docs | [vision](../product/vision.md) §2 P3–P5 and §5.2; [ADR-0012](../adr/0012-two-themes-minimal-ui-en-pt.md); [ADR-0006](../adr/0006-narrow-webview-capabilities.md); [ADR-0022](../adr/0022-permissive-license-gate.md); [ADR-0024](../adr/0024-source-code-indexing-opt-in.md) (WP-7.6 only); [SPEC-0002](SPEC-0002-engine-api.md) §4.3–§4.4 |
| Benchmark gates | None. No retrieval, indexing, inference, provisioning, or asset-size behavior changes |

## 1. Problem and goal

The current desktop UI is English-only and dark-only. Translatable copy,
notices, accessible names, the native folder-dialog title, and the window title
are embedded in `App.tsx`, `index.html`, or `tauri.conf.json`; counts and dates
use the webview's implicit locale. The native window is fixed to `Dark` with a
dark background, so even an OS-level light preference cannot be honored.

Desktop experience v1 makes the existing Search, Local Files, Settings, and
Preview surfaces available in English and Portuguese, with OS-locale detection,
a local user override, and English fallback. It also adds exactly one light and
one dark token set, follows the OS theme by default, persists an optional user
override, synchronizes the native Tauri window, and checks WCAG 2.2 AA contrast
targets. The user can change either preference without restarting or reloading.
The engine remains headless and unchanged: v1 adds no search, indexing, model,
or filesystem behavior and performs no network request.

## 2. Scope

- **In — WP-7.1:** statically bundled `en` and `pt` catalogs; migration of all
  existing user-facing UI copy, including native dialog/window text and the new
  preference controls; BCP 47 OS-locale resolution; regional-variant mapping;
  immediate and persistent locale override; per-message English fallback;
  interpolation and CLDR plural selection through `Intl`; explicit number,
  byte, date, and time formatting; localized operation errors and status
  fallbacks; a CI catalog-parity check; hardware-free unit tests and the manual
  locale/theme matrix in §6.
- **In — WP-7.2:** exactly two semantic-color token sets (`light` and `dark`);
  OS-theme detection and change tracking; immediate and persistent
  `system`/`light`/`dark` override; matching webview, native window theme,
  native background, and initial paint; text/non-text/focus contrast checks;
  hardware-free unit tests and manual inspection in both themes and locales.
- **Out — later SPEC-0014 versions:** the following work packages are not
  requirements of v1 and must not be implemented against this version:

  | Work package | Deferred scope | Spec version |
  |---|---|---|
  | WP-7.3 | Progressive results, stable reordering, keyboard-first result navigation, and instant cancellation | v2 |
  | WP-7.4 | Folders coverage, health, pause/resume, and exclusions redesign, including the semantic-indexing status with Pause and the temporary Full speed control (§7.3, ADR-0025) | v2 |
  | WP-7.5 | Retrieval-backed folder/type/date/size filters | v2 |
  | WP-7.6 | Full Settings and advanced diagnostics, including the ADR-0024 “Index source code” control, path redaction, the `Auto`/`CPU`/per-provider override, and the opt-in GPU quality tier entry (§7.3, ADR-0025) | v2 |
  | WP-7.7 | Preview highlights and opening at a locator | v2 |
  | WP-7.8 | Full accessibility pass, React component tests with mocked IPC, and WebDriver E2E | v2 |
  | WP-7.9 | Strict Content Security Policy | v2 |

- **Also out:** additional locales or regional translation catalogs, a theme
  editor, custom palettes, more than two themes, UI layout redesign, typed
  changes to SPEC-0002 engine errors or payloads, new engine IPC business logic,
  and generative translation at runtime. V1 only adds the minimal Language and
  Theme controls needed by WP-7.1/WP-7.2; it does not deliver the WP-7.6
  Settings redesign.

## 3. Requirements (EARS)

| ID | Requirement | Verification | Status |
|---|---|---|---|
| SPEC-0014-R1 | The desktop shall load all translations from statically bundled, flat JSON catalogs named `en` and `pt`, using the key, message, plural-form, and placeholder contracts in §4.1 and without fetching catalogs at runtime. | unit `catalogs_have_identical_flat_keys_and_shapes`; inspection of bundled assets and network-free startup | Open |
| SPEC-0014-R2 | When rendering a v1 surface, native dialog, accessible name, notification, or window title, the desktop shall obtain every translatable string through the catalog and shall retain only the exemptions in §4.6; the migration shall cover every item in §4.7. | unit `literal_translation_references_exist`; source inspection against §4.7; manual `localized_surfaces_have_no_hardcoded_copy` | Open |
| SPEC-0014-R3 | When no valid locale override is stored, the desktop shall select the first supported language in the OS preference list, map regional variants to `en` or `pt` as in §5.1, and use English when no supported language can be resolved. | unit `os_locale_prefers_first_supported_language`, `os_locale_maps_regional_variants_to_base_catalogs`, `os_locale_falls_back_to_english`, `invalid_stored_locale_uses_os_locale` | Open |
| SPEC-0014-R4 | When the user selects System default, English, or Português, the desktop shall apply that locale preference immediately, update `<html lang>`, persist only the corresponding enum value locally, and survive unavailable storage without failing; System default shall resume OS resolution. | unit `locale_override_persists_and_applies_without_reload`, `storage_failure_uses_in_memory_preferences`; manual restart and `languagechange` checks | Open |
| SPEC-0014-R5 | If a Portuguese message, corresponding plural form, or translation is unavailable, then the desktop shall use the English message with the same parameters; if a key is absent from English, then it shall use `common.error.generic` rather than expose the key, and CI shall reject the invalid catalog before release. | unit `missing_pt_message_uses_english`, `missing_english_message_uses_generic_error_not_key`, `parity_checker_rejects_missing_english_key` | Open |
| SPEC-0014-R6 | When a message has a numeric `count`, the desktop shall select its plural form with `Intl.PluralRules` for the active formatting locale and interpolate all values as plain text, without plural suffix keys, string concatenation for grammar, or HTML evaluation. | unit `plural_categories_come_from_intl`, `plural_placeholders_match_across_catalogs`, `interpolation_does_not_evaluate_markup` | Open |
| SPEC-0014-R7 | When rendering a count, score, elapsed time, byte size, date, or time, the desktop shall use explicit `en` or `pt-BR` `Intl` formatting as in §4.2 and shall not call parameterless `toLocaleString`/`toLocaleDateString` or hardcode decimal/group separators. | unit `numbers_use_active_locale`, `dates_use_active_locale_and_explicit_timezone`, `bytes_use_binary_units_and_locale_number`; inspection | Open |
| SPEC-0014-R8 | If an IPC operation rejects or an engine-supplied status, phase, progress message, health message, extraction detail, or error has no localization code, then the desktop shall show the corresponding localized operation/status fallback and shall not display the raw string as translated UI. | unit `ipc_failures_map_to_operation_messages`, `unknown_progress_phase_uses_localized_generic`; inspection of every `catch` and dynamic field in §4.6 | Open |
| SPEC-0014-R9 | When the `en` and `pt` catalogs differ in keys, message kinds, plural categories, or corresponding placeholders, or contain an empty message, the desktop CI shall fail `npm run i18n:check`; a missing key in either catalog shall always be a nonzero result. | unit `parity_checker_rejects_missing_extra_and_mismatched_keys`, `parity_checker_rejects_missing_english_key`, `parity_checker_rejects_empty_messages`; CI inspection | Open |
| SPEC-0014-R10 | The desktop shall define exactly two complete semantic token sets, `light` and `dark`, with identical keys and the roles in §4.4, and component CSS shall consume semantic variables rather than palette literals. | unit `token_sets_have_same_semantic_keys`; `npm run theme:check`; CSS inspection | Open |
| SPEC-0014-R11 | While the theme preference is `system`, the desktop shall use the resolved OS light/dark theme and shall update the effective theme when the OS theme changes; while an explicit override is active, it shall not change the effective theme in response to OS events. | unit `system_theme_changes_only_in_system_mode`, `os_theme_resolution_has_deterministic_fallback`; manual OS-switch check | Open |
| SPEC-0014-R12 | When the user selects System default, Light, or Dark, the desktop shall apply the theme immediately without reload, persist only `system`, `light`, or `dark` locally, treat an invalid stored value as `system`, and survive unavailable storage without failing. | unit `theme_override_persists_and_applies_without_reload`, `invalid_theme_falls_back_system`, `storage_failure_uses_in_memory_preferences`; manual restart check | Open |
| SPEC-0014-R13 | When the effective theme or locale changes, the Tauri shell shall synchronize the native theme, window and webview background, and localized window title as in §4.5; startup shall not show the fixed dark configuration or an incorrect-theme flash, and an initialization failure shall not leave the window hidden. | unit `native_theme_receives_null_for_system_and_explicit_override`, `native_background_matches_effective_background_token`, `initialization_failure_still_shows_window`; manual native startup/titlebar check | Open |
| SPEC-0014-R14 | For every text/background pair used by either theme, the desktop shall meet WCAG 2.2 AA contrast: at least 4.5:1 for normal text and at least 3:1 for large text, including muted, placeholder, selected, marked, notice, error, hover, and focus text states. | unit `contrast_black_white_is_21`, `text_token_pairs_meet_aa_in_both_themes`, `alpha_tokens_are_composited_before_contrast`; manual computed-style spot check | Open |
| SPEC-0014-R15 | For visual information required to identify controls, control states, meaningful icons, and focus indicators, the desktop shall meet at least 3:1 contrast against adjacent colors and shall keep a visible focus indicator in both themes. | unit `nontext_token_pairs_meet_aa_in_both_themes`; manual `focus_and_control_states_meet_contrast_targets` | Open |
| SPEC-0014-R16 | The WP-7.1/WP-7.2 implementation shall not change engine APIs, ranked output, indexing behavior, model behavior, file access, or telemetry/network behavior, and shall add no production dependency unless §7 is revised before acceptance. | diff and `cargo tree`/npm dependency inspection; existing golden and hardware-free suites; no benchmark report required | Open |

Status: `Open` → `Implemented` (code and its test merged; name WP-7.1 or WP-7.2)
→ `Verified` (any applicable acceptance gate passed). This draft defines no
benchmark-verified requirement.

## 4. Interfaces

### 4.1 Catalog files, keys, and messages

WP-7.1 adds these frontend-owned files (names are part of the contract):

```text
apps/desktop/src/i18n/locales/en.json
apps/desktop/src/i18n/locales/pt.json
apps/desktop/src/i18n/locale.ts
apps/desktop/src/i18n/messages.ts
apps/desktop/src/i18n/format.ts
apps/desktop/scripts/check-i18n.mjs
```

Both catalogs are strict JSON, imported into the local bundle. JSON has no
comments, functions, remote URLs, HTML message markup, or nested namespaces.
A key is a flat, dot-separated semantic identifier matching
`^[a-z][a-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+$`. The first segment is one of
`common`, `window`, `nav`, `search`, `folders`, `settings`, `preview`,
`indexing`, `status`, or `errors`; later segments use lower camel case. Keys describe
purpose, not an English phrase, CSS class, or array position.

Examples: `search.input.placeholder`, `folders.root.action.remove`,
`settings.theme.option.system`, `common.action.dismiss`. Shared actions and
states use `common` rather than duplicates. Static backend labels and details
also have keys even when their translated value is the same technical name.

A value is either a nonempty string or a plural object with exactly the CLDR
categories needed by v1, `one` and `other`, each nonempty:

```json
{
  "common.action.dismiss": "Dismiss",
  "search.results.count": {
    "one": "{count} result · {elapsedMs} ms",
    "other": "{count} results · {elapsedMs} ms"
  }
}
```

```json
{
  "common.action.dismiss": "Dispensar",
  "search.results.count": {
    "one": "{count} resultado · {elapsedMs} ms",
    "other": "{count} resultados · {elapsedMs} ms"
  }
}
```

Plural selection uses one base key, never `key_one`/`key_other`. A plural call
requires an integer, finite, nonnegative `count`. Count zero is not a special
category: the result comes from CLDR (notably, `pt-BR` classifies zero as
`one`). Additional categories may be introduced only by a later spec version
that adds a language needing them.

Placeholders use `{lowerCamelCase}` and values are strings or numbers. React
renders the completed message as text; `dangerouslySetInnerHTML` is forbidden.
The same message in both catalogs has the same kind and plural categories, and
each corresponding form has the same placeholder set. Parity is per category:
English `one` and Portuguese `one` must match, but `one` and `other` within one
catalog may use different placeholders when grammar requires it.

The following types define the frontend boundary; `MessageKey` is derived from
the English catalog so nonliteral references remain type-checked:

```ts
import enCatalog from "./locales/en.json";

type CatalogLocale = "en" | "pt";
type LocalePreference = "system" | CatalogLocale;
type MessageValues = Record<string, string | number>;
type MessageKey = keyof typeof enCatalog;

interface I18n {
  readonly locale: CatalogLocale;
  t(key: MessageKey, values?: MessageValues): string;
  number(value: number, options?: Intl.NumberFormatOptions): string;
  dateTime(epochSeconds: number, timeZone?: string): string;
  date(epochSeconds: number, timeZone?: string): string;
  bytes(bytes: number): string;
}
```

`common.error.generic` is mandatory. During development, a missing key or
parameter also raises a developer diagnostic containing only the key/parameter
name. In production, §3 R5's generic fallback applies; a catalog without
`common.error.generic` is invalid and cannot pass CI. Diagnostics never include
document text, paths, queries, or user data.

### 4.2 Locale and formatting contracts

The persisted webview keys and values are:

| Key | Allowed values | Default / invalid value |
|---|---|---|
| `seeky.ui.locale.v1` | `system`, `en`, `pt` | `system` |
| `seeky.ui.theme.v1` | `system`, `light`, `dark` | `system` |

Only these enums are stored, in webview `localStorage`; no locale/theme IPC
payload, engine database migration, account, telemetry, or remote preference is
introduced. Storage reads/writes are wrapped so denied or unavailable storage
falls back to in-memory preferences for the session.

The catalog locale and the formatting locale are deliberately separate:

| Catalog | `<html lang>` | `Intl` locale | Used for |
|---|---|---|---|
| `en` | `en` | `en` | Every English regional variant |
| `pt` | `pt-BR` | `pt-BR` | The shared Portuguese catalog; v1 uses Brazilian Portuguese number/date conventions |

`Intl.NumberFormat`, `Intl.DateTimeFormat`, `Intl.PluralRules`, and
`Intl.ListFormat` instances are cached by locale and options rather than
recreated for every result row. Their inputs/defaults are:

- General counts use grouping; page numbers and identifiers disable grouping.
  Scores use two fraction digits; elapsed milliseconds use a nonnegative integer
  followed by the locale-independent `ms` symbol inside a catalog message.
- `bytes` uses the existing binary thresholds (1024; B, KB, MB, GB), zero or one
  fraction digit below 10 above the byte unit and zero otherwise. Unit symbols
  come from `common.unit.byte`, `common.unit.kilobyte`,
  `common.unit.megabyte`, and `common.unit.gigabyte`; the number is localized.
  Nonfinite or negative values render `common.status.notAvailable`.
- `dateTime` uses `dateStyle: "medium", timeStyle: "short"`; `date` uses
  `dateStyle: "medium"`. Both consume Unix seconds and default to the user's
  local timezone. A nullable engine timestamp renders `common.time.never` only
  for `null`/`undefined`; epoch zero remains a valid timestamp. Tests inject a
  fixed timezone rather than depending on the runner timezone.
- Multipart indexing summaries are formatted as separately pluralized messages
  and joined with `Intl.ListFormat` using `type: "unit", style: "short"`, not
  English word order or hardcoded conjunctions.

### 4.3 Preference and theme modules

WP-7.2 adds:

```text
apps/desktop/src/theme/tokens.ts
apps/desktop/src/theme/theme.ts
apps/desktop/scripts/check-theme.mjs
```

```ts
import { light } from "./tokens";

type EffectiveTheme = "light" | "dark";
type ThemePreference = "system" | EffectiveTheme;

type SemanticToken = keyof typeof light;
type ThemeTokens = Record<SemanticToken, string>;

function resolveLocale(
  preference: LocalePreference,
  osLanguages: readonly string[],
): CatalogLocale;

function resolveTheme(
  preference: ThemePreference,
  osTheme: EffectiveTheme | null,
): EffectiveTheme;
```

`resolveTheme` returns an explicit preference unchanged; for `system` it returns
`osTheme`, with `light` as the deterministic fallback when neither the webview
nor Tauri can provide an OS theme. The Tauri adapter supplies OS information,
native setters, and subscriptions behind a small interface so pure preference
logic and native-call sequencing can be unit-tested with fakes. This is not the
WP-7.8 React component/IPC test suite.

### 4.4 Semantic theme tokens

`tokens.ts` exports `light` and `dark` objects with identical keys. It is the
single palette source for CSS variables, the contrast checker, and native
background colors. Palette literals (`#...`, `rgb(...)`, `rgba(...)`, and named
colors) are allowed there, not in component CSS. `theme.ts` applies the selected
object as `--color-<token>` custom properties, sets `data-theme` and
`color-scheme` on the root element, and uses the same `bg` value natively.

| Token group | Required tokens and roles |
|---|---|
| Surfaces | `bg` (root/native background), `panel`, `panelRaised`, `sidebar`, `preview`, `input`, `hover`, `selected`, `statusbar` |
| Borders/focus | `border`, `borderStrong`, `focusRing` |
| Text | `text`, `muted`, `subtle`, `placeholder`, `onAccent`, `onMark` |
| Accent/action | `accent`, `accentHover`, `accentText`, `accentSecondary` |
| Semantic states | `danger`, `dangerBg`, `warning`, `warningBg`, `success`, `successBg`, `info`, `infoBg` |
| Highlight/disabled | `mark`, `disabled`, `onDisabled` |
| Effects | `shadow` (exempt from contrast ratios, but still theme-specific) |

Every semantic foreground/background combination used by CSS is enumerated in
`check-theme.mjs`; an unlisted combination is not permitted. Alpha colors are
composited over their actual token backdrop before calculating contrast.
Gradients are checked at their lowest-contrast stop. Disabled text is exempt
from WCAG 1.4.3, but its state must remain distinguishable and is manually
inspected. No third high-contrast or custom theme is added by v1.

### 4.5 Tauri window integration and narrow capabilities

The current static values `"theme": "Dark"` and
`"backgroundColor": "#0f1216"` are removed. The main window configuration has
`"title": "Seeky"` (a brand-only startup title), omits `theme` so the native
window follows the OS, omits a fixed `backgroundColor`, and uses
`"visible": false` until initialization completes.

Startup ordering is:

1. Read both preferences safely and resolve locale/effective theme.
2. While the window is hidden, apply `<html lang>`, root tokens/data attributes,
   the localized title, the native theme, and the native window/webview
   background. `index.html` also uses only `Seeky` as its static title, avoiding
   a second hardcoded English tagline.
3. Render React and show the window. If native synchronization rejects, retain
   the resolved web theme, record only a redacted developer diagnostic, and
   still show the window; initialization must never deadlock startup.
4. Subscribe to OS theme changes and, where the webview emits it,
   `languagechange`; subscriptions are idempotent under React StrictMode and
   are removed on teardown.

The Tauri JavaScript calls are `getCurrentWindow().setTitle(...)`,
`getCurrentWindow().setTheme(null | "light" | "dark")`,
`getCurrentWebviewWindow().setBackgroundColor(tokens[effective].bg)`, and
`getCurrentWindow().show()`. For `system`, native `setTheme(null)` restores OS
tracking; an override passes its explicit value. Initial web resolution uses the
`prefers-color-scheme` media query; if it has no usable result, the adapter
queries `getCurrentWindow().theme()`, then applies the `light` fallback. OS
events use both that media query and Tauri `onThemeChanged`, with duplicate
notifications harmless and the media query remaining the primary web source.

ADR-0006's core-only boundary remains. Only these narrow setters are added to
the existing main-window capability; no filesystem, opener, shell, store, or
new plugin permission is granted:

```text
core:window:allow-set-title
core:window:allow-set-theme
core:window:allow-set-background-color
core:webview:allow-set-webview-background-color
core:window:allow-show
```

### 4.6 Exempt and dynamic strings

The no-hardcoded-copy rule does not translate or alter the following data:

- `Seeky` and its brand mark; document titles, paths, filenames, extensions,
  queries, extracted snippets/content, and user-selected folder names;
- stable technical identifiers received from IPC (CPU, CUDA, NPU, ONNX Runtime,
  OpenVINO, BM25, model/device names and dimensions), file-format acronyms, SI
  symbols, punctuation-only separators, SVG path data, and internal enum values;
- text rendered by the OS inside native controls/dialogs.

Static technical labels still use catalog keys. Dynamic technical identifiers
may be displayed as identifiers, never interpolated into logs or treated as
translation keys. V1 does not introduce a hardcoded replacement for the current
`384-d`/`gety-embed-v0` fallback copy: absent engine details use
`common.status.notLoaded` or `common.status.notAvailable`; the indexing
explanation is model-neutral.

Engine payloads remain SPEC-0002-compatible. Raw `String(err)`,
`IndexHealth.last_message`, `last_error`, `details[]`, and
`IndexProgress.message` are diagnostic data, not translated UI. V1 shows a
localized message for the attempted operation, known localized state/phase, or
numeric issue count instead. Unknown `phase`/`matched` values use a localized
generic state or are not rendered as a tag; they are never echoed as English
copy. Full diagnostic presentation is deferred to WP-7.6.

### 4.7 Current user-facing string inventory

The tables below are the WP-7.1 migration checklist for `apps/desktop/src` and
the associated HTML/Tauri titles. English text in quotation marks is the
current source text or template, not a requirement to preserve awkward copy;
the key and parameter contract is normative. A plural key uses the message
object in §4.1.

#### Application, navigation, search, and preview

| Key | Current English text / dynamic template |
|---|---|
| `window.title` | “Seeky — local semantic search” (`index.html` and `tauri.conf.json`) |
| `common.brand.tagline` | “local semantic search” |
| `nav.search` | “Search” |
| `nav.folders` | “Local Files” |
| `nav.settings` | “Settings” |
| `common.inference.label` | “Inference” |
| `common.status.notLoaded` | “not loaded” |
| `common.status.notFound` | “not found” |
| `common.status.notAvailable` | Current em-dash fallback |
| `common.time.never` | “never” |
| `common.state.working` | “working…” |
| `common.state.applyingChanges` | “applying changes…” |
| `common.action.dismiss` | “Dismiss” (both banners) |
| `common.count.files` | “{count} file/files” (sidebar) |
| `common.count.chunks` | “{count} chunk/chunks” (sidebar/status bar) |
| `common.unit.byte` / `common.unit.kilobyte` / `common.unit.megabyte` / `common.unit.gigabyte` | “B”, “KB”, “MB”, “GB”, including “0 B” |
| `search.input.placeholder` | “Search keyword, phrase, or meaning…” |
| `search.input.action.clear` | Accessible name “Clear search” |
| `search.action.addFolder` | “Add folder” |
| `search.hero.kicker` | “PRIVATE · LOCAL · FAST” |
| `search.hero.title` | “Meet Seeky, your personal semantic file search.” (currently split by `<br>`) |
| `search.hero.body` | “Index your folders once. Then ask in plain language and get the passages that matter — with citations, on your machine.” |
| `search.hero.action.addFolder` | “Add a folder” |
| `search.hero.action.chooseBackend` | “Choose CPU / CUDA / NPU” |
| `search.hero.stats.filesIndexed` | “files indexed” |
| `search.hero.stats.semanticChunks` | “semantic chunks” |
| `search.hero.stats.activeBackend` | “active backend” |
| `search.status.searching` | “Searching…” |
| `search.results.count` | “{count} result/results · {elapsedMs} ms” |
| `search.status.noResultsYet` | “No results yet” |
| `search.mode.hybrid` | “hybrid BM25 + embeddings” |
| `search.mode.lexical` | “BM25 only” |
| `search.empty.title` | “No matches” |
| `search.empty.body` | “Try a broader phrase, or add and index another folder.” |
| `search.tag.semantic` | “semantic” |
| `search.tag.filename` | “filename” |
| `search.tag.bm25` | “BM25” |
| `search.result.page` | “p.{page}” |
| `preview.kicker` | “PREVIEW” |
| `preview.action.close` | Accessible name “Close preview” |
| `preview.action.openFile` | “Open file” |

The literal brand strings `s` and `seeky.` and dynamic result titles, paths,
extensions, snippets, scores-as-data, and backend identifiers are covered by
§4.6 rather than duplicated as translations. Scores and page numbers still use
§4.2 formatting.

#### Folder actions, notices, indexing summaries, and health

| Key | Current English text / dynamic template |
|---|---|
| `folders.dialog.addTitle` | Native dialog title “Add a folder to Seeky” |
| `folders.notice.addedWatching` | “Folder added. Watching for changes — index it to make it searchable.” |
| `folders.notice.addedWatchFailed` | “Folder added, but watching failed. Check Index health, then index it manually.” |
| `folders.notice.removed` | “Removed {folder} and its indexed documents.” |
| `folders.notice.watchResumed` | “Watching {folder} for changes.” |
| `folders.notice.watchPaused` | “Paused watching {folder}.” |
| `folders.notice.indexCancelled` | Current “Index cancelled after {files} files / {chunks} chunks.”; v1 uses a separately formatted `{summary}` |
| `folders.notice.cancelRequested` | “Cancellation requested. The current file will finish first.” |
| `indexing.progress.scanning` | “Scanning…” |
| `indexing.summary.updated` | “{count} updated” (plural message) |
| `indexing.summary.unchanged` | “{count} unchanged” (plural message) |
| `indexing.summary.chunks` | “{count} chunk/chunks” |
| `indexing.summary.skipped` | “{count} skipped” (plural message) |
| `indexing.summary.removed` | “{count} removed” (plural message) |
| `folders.eyebrow` | “INDEX” |
| `folders.title` | “Local Files” |
| `folders.description` | “Folders Seeky can watch and search. Nothing leaves this machine.” |
| `folders.action.add` | “Add folder” |
| `folders.empty.title` | “No folders yet” |
| `folders.empty.body` | “Add a folder to start building your local index.” |
| `folders.root.meta.documents` | “{count} document/documents” |
| `folders.root.status.indexed` | “indexed” |
| `folders.root.status.readyToIndex` | “ready to index” |
| `folders.root.action.pauseWatching` | Tooltip “Pause filesystem watching” |
| `folders.root.action.resumeWatching` | Tooltip “Resume filesystem watching” |
| `common.state.watching` | “Watching” |
| `common.state.paused` | “Paused” |
| `common.state.indexing` | “Indexing” |
| `folders.root.action.indexing` | “Indexing…” |
| `folders.root.action.reindex` | “Reindex” |
| `folders.root.action.index` | “Index” |
| `folders.root.action.remove` | Accessible name “Remove folder” |
| `folders.health.title` | “Index health” |
| `folders.health.noActivity` | “No indexing activity yet.” |
| `folders.health.action.cancel` | “Cancel” |
| `folders.health.state.idle` | “Idle” |
| `folders.health.watcher.label` | “Watcher” |
| `folders.health.watcher.watching` | “Watching {count} folder/folders” |
| `folders.health.pending` | “Pending changes” |
| `folders.health.lastIndexed` | “Last indexed” |
| `folders.health.skippedErrors` | “Skipped / errors” |
| `folders.health.processing` | “Processing” (the path remains dynamic data) |
| `folders.health.recentIssues` | “Recent extraction issues ({count})” |
| `folders.health.hint` | “Live changes are applied automatically. Use Reindex to pick up edits made while Seeky was closed.” |
| `folders.supported.title` | “Supported today” |
| `folders.supported.pdf` | “text + pages” |
| `folders.supported.docx` | “paragraphs” |
| `folders.supported.xlsx` | “sheet cells” |
| `folders.supported.pptx` | “slide text” |
| `folders.supported.text` | “plain text” |
| `folders.supported.html` | “readable text” |
| `folders.supported.code` | “source files” |
| `folders.how.title` | “How indexing works” |
| `folders.how.body` | “Seeky extracts text, chunks it, embeds every chunk with `gety-embed-v0`, and stores both BM25 and vector indexes in one SQLite file.”; v1 makes it model-neutral |
| `status.filesSearchable` | “{count} file/files searchable” |
| `status.indexingFolder` | “Indexing {folder}” |
| `status.watching` | “Watching” |

The format labels `PDF`, `DOCX`, `XLSX`, `PPTX`, `TXT / MD`, `HTML`, and `CODE`
are static technical labels and receive parallel `folders.supported.*.label`
keys even though their values need not change between locales. `Processing`,
`Watching`, and indexing status separators do not expose raw progress messages.

#### Settings, backends, and new preferences

| Key | Current English text / dynamic template |
|---|---|
| `settings.eyebrow` | “INFERENCE” |
| `settings.title` | “Hardware & models” |
| `settings.description` | “Switch backends without changing the index. All models are local.” |
| `settings.backend.auto.label` | “Auto” |
| `settings.backend.cpu.label` / `settings.backend.cuda.label` / `settings.backend.npu.label` | “CPU”, “CUDA”, “NPU” |
| `settings.backend.auto.detail` | “CPU” |
| `settings.backend.cpu.detail` | “ONNX Runtime · uint8” |
| `settings.backend.cuda.detail` | “RTX / ONNX Runtime · FP16” |
| `settings.backend.npu.detail` | “Intel AI Boost · OpenVINO” |
| `settings.backend.auto.description` | “Uses the CPU. NPU and GPU run only when chosen explicitly until they pass validation.” |
| `settings.backend.cpu.description` | “Universal fallback. Smallest model, lowest memory.” |
| `settings.backend.cuda.description` | “Fastest path on NVIDIA GPUs.” |
| `settings.backend.npu.description` | “Low-power inference on Intel Core Ultra NPUs.” |
| `settings.backend.noticeReady` | “{backend} ready · {device}” |
| `settings.backend.active` | “active” |
| `settings.backend.unavailable` | “unavailable” |
| `settings.engine.title` | “Active engine” |
| `settings.engine.backend` / `settings.engine.device` / `settings.engine.model` / `settings.engine.shape` | “Backend”, “Device”, “Model”, “Shape” |
| `settings.engine.empty` | “No engine loaded yet. Choose a backend or run a search/index.” |
| `settings.index.title` | “Index” |
| `settings.index.documents` / `settings.index.chunks` / `settings.index.embeddings` / `settings.index.roots` | “Documents”, “Chunks”, “Embeddings”, “Roots” |
| `settings.paths.title` | “Model paths” |
| `settings.paths.embeddingModel` | Current “Gety model”; v1 uses “Embedding model” |
| `settings.paths.openvinoIr` | “OpenVINO IR” |
| `settings.paths.pdfium` | “PDFium” |
| `settings.paths.database` | “Database” |
| `settings.backendNotes.title` | “Backend notes” |
| `settings.backendNotes.body` | “CUDA uses the FP16 Gety export and NVIDIA’s runtime. NPU uses the OpenVINO IR on Intel AI Boost. CPU uses the uint8 ONNX export. The first load compiles/loads the model and may take a few seconds.” |
| `settings.preferences.title` | New “Preferences” heading |
| `settings.locale.label` | New “Language” label |
| `settings.locale.option.system` | New “System default” option |
| `settings.locale.option.en` | New endonym “English” |
| `settings.locale.option.pt` | New endonym “Português” |
| `settings.theme.label` | New “Theme” label |
| `settings.theme.option.system` | New “System default” option |
| `settings.theme.option.light` | New “Light” option |
| `settings.theme.option.dark` | New “Dark” option |

The current hardcoded `384-d Gety embeddings` and status-bar `384-d` fallbacks
are intentionally not catalog entries; §4.6 defines their localized neutral
fallback. Engine-provided backend, device, model, shape, and path values remain
dynamic diagnostic identifiers, with full diagnostics/redaction deferred.

#### Operation errors and untyped dynamic diagnostics

The current `Document not found in the index.` becomes
`errors.document.notFound`. Each existing raw `String(err)` display is replaced
by its operation-specific key:

| Operation | Required key |
|---|---|
| Refresh/get status | `errors.status.refresh` |
| Search | `errors.search.failed` |
| Add folder/native dialog | `errors.folders.add` |
| Remove folder | `errors.folders.remove` |
| Pause/resume watching | `errors.folders.watch` |
| Start/reindex | `errors.indexing.start` |
| Cancel indexing | `errors.indexing.cancel` |
| Probe/choose backend | `errors.settings.probeBackend` |
| Load document preview | `errors.preview.load` |
| Open file | `errors.preview.open` |
| Unmapped translation/operation failure | `common.error.generic` |

`health.last_message`, `health.last_error`, `health.details[]`, and
`progress.message` have no fixed English inventory because they are arbitrary
backend strings. Their current render sites are covered by R8: use
`folders.health.noActivity`, `folders.health.state.*`,
`folders.health.recentIssues`, `indexing.progress.scanning`, another known
localized phase key, or `common.state.working`/`common.error.generic` as
appropriate. Raw extraction-detail list items are not shown as default v1 UI.

## 5. Behavior details

### 5.1 Locale resolution and changes

1. Parse the stored preference as an enum; any other value is `system`.
2. For an explicit `en`/`pt`, use it and ignore OS languages until the preference
   returns to `system`.
3. For `system`, iterate `navigator.languages` in order, falling back to
   `navigator.language` when the list is empty or unavailable. Canonicalize each
   candidate with `Intl.getCanonicalLocales` inside error handling, compare its
   lowercase base subtag, and select the first `pt` or `en`. Examples:

   | OS languages | Catalog / formatting locale |
   |---|---|
   | `["pt-BR", "en-US"]` | `pt` / `pt-BR` |
   | `["pt-PT"]` | `pt` / `pt-BR` (shared v1 Portuguese catalog) |
   | `["en-GB"]` | `en` / `en` |
   | `["fr-FR", "pt-BR"]` | `pt` / `pt-BR` |
   | `["fr-FR", "de-DE"]` | `en` / `en` |
   | empty, malformed, or unavailable | `en` / `en` |

4. A `languagechange` event recomputes only a `system` preference. There is no
   polling and no assumption that every webview emits the event; the next
   startup always recomputes it.
5. The Settings control displays `System default`, `English`, and `Português`.
   Changing it updates all rendered messages, accessible names, native titles,
   formats, and `<html lang>` before the next paint; no reload or engine call
   occurs.

Fallback is per message, not a wholesale switch after one missing translation.
English parameters are reused, including `count`, so fallback still selects the
English plural correctly. Parity failure is a developer/build error and must
not silently ship as a partially English Portuguese UI.

### 5.2 Theme state and native synchronization

`system` is the default. The effective web and native themes always derive from
the same preference and OS value. An OS event while in `system` recomputes and
applies tokens/background; an explicit override leaves the effective value
unchanged. Returning to `system` calls native `setTheme(null)` and immediately
resolves the current OS value rather than waiting for another event.

A theme change updates all semantic variables, native controls via
`color-scheme`, the Tauri native theme/background, and the root `data-theme`.
There is no timed animation requirement and no polling. Listener registration
and native calls are safe to repeat during development StrictMode setup.

### 5.3 Catalog parity CI

`npm run i18n:check` runs `node scripts/check-i18n.mjs` with Node 24 and no new
runtime dependency. It parses the real `en.json` and `pt.json`, rejects invalid
JSON/empty leaves, and compares:

1. exact flat key sets in both directions (missing and extra keys both fail);
2. string versus plural-object kind at every key;
3. exact plural-category sets and nonempty forms;
4. sorted placeholder sets for each corresponding message/form;
5. every literal `t("…")` reference against the English key set (TypeScript's
   `MessageKey` checks typed nonliteral references);
6. mandatory `common.error.generic` and the §4.1 key grammar.

The checker exits nonzero and prints only catalog keys and mismatch reasons,
never document/user data. `apps/desktop/package.json` exposes the script and the
CI frontend job invokes it on every pull request. Tests create synthetic catalog
fixtures in per-test temporary directories; they do not weaken or edit the real
catalogs to demonstrate failure.

### 5.4 Contrast calculation and inspection

`npm run theme:check` verifies identical token sets and evaluates the declared
pair matrix with the WCAG sRGB relative-luminance formula. It uses opaque,
composited colors and fails below 4.5:1 or 3:1 as assigned in §3 R14/R15; no
rounding up is allowed (for example, 4.499 fails 4.5). Black/white is a
known-answer test at 21:1. “Large text” follows WCAG: at least 24 CSS px for
regular weight or approximately 18.66 CSS px for bold; smaller text uses the
4.5:1 target.

Automated token checks complement, not replace, manual computed-style and focus
checks. V1 targets WCAG 2.2 AA Success Criteria 1.4.3 (Contrast Minimum) and
1.4.11 (Non-text Contrast), plus visible focus. It does not claim complete WCAG
conformance; the full accessibility pass, including screen readers and E2E, is
WP-7.8.

## 6. Acceptance

### 6.1 Tests

Write these hardware-free tests before implementation and name/comment each
with its requirement ID. Pure locale, message, formatting, preference, native
adapter sequencing, token, and contrast logic is unit-testable immediately with
Node 24's built-in `node:test` runner and small fakes; no React renderer, model,
PDFium, GPU, NPU, or Tauri runtime is required. Pure TypeScript modules use
Node-compatible, erasable-only type syntax. Keep these tests outside the
frontend `tsconfig` application include when necessary, and add
`npm run test:unit` for `node --test` over them. React component tests with
mocked IPC are explicitly deferred to WP-7.8; until then, the manual matrix is
mandatory and is not represented as an automated component test.

| Test | Requirement IDs |
|---|---|
| `catalogs_have_identical_flat_keys_and_shapes` | R1, R9 |
| `literal_translation_references_exist` | R2, R9 |
| `catalog_values_are_nonempty_and_valid` | R1, R9 |
| `os_locale_prefers_first_supported_language` | R3 |
| `os_locale_maps_regional_variants_to_base_catalogs` | R3 |
| `os_locale_falls_back_to_english` | R3 |
| `invalid_stored_locale_uses_os_locale` | R3, R4 |
| `locale_override_persists_and_applies_without_reload` | R4 |
| `missing_pt_message_uses_english` | R5 |
| `missing_english_message_uses_generic_error_not_key` | R5, R9 |
| `parity_checker_rejects_missing_english_key` | R5, R9 |
| `plural_categories_come_from_intl` (en and pt-BR counts 0, 1, 2) | R6 |
| `plural_placeholders_match_across_catalogs` | R6, R9 |
| `interpolation_does_not_evaluate_markup` | R6 |
| `numbers_use_active_locale` (fixed `1234567.89` en/pt-BR examples) | R7 |
| `dates_use_active_locale_and_explicit_timezone` (fixed epoch, UTC) | R7 |
| `bytes_use_binary_units_and_locale_number` (0, 1024, 1536, invalid input) | R7 |
| `ipc_failures_map_to_operation_messages` | R8 |
| `unknown_progress_phase_uses_localized_generic` | R8 |
| `parity_checker_rejects_missing_extra_and_mismatched_keys` | R9 |
| `parity_checker_rejects_empty_messages` | R9 |
| `token_sets_have_same_semantic_keys` | R10 |
| `system_theme_changes_only_in_system_mode` | R11, R12 |
| `os_theme_resolution_has_deterministic_fallback` | R11 |
| `theme_override_persists_and_applies_without_reload` | R12 |
| `invalid_theme_falls_back_system` | R12 |
| `storage_failure_uses_in_memory_preferences` | R4, R12 |
| `native_theme_receives_null_for_system_and_explicit_override` | R13 |
| `native_background_matches_effective_background_token` | R13 |
| `initialization_failure_still_shows_window` | R13 |
| `contrast_black_white_is_21` | R14 |
| `text_token_pairs_meet_aa_in_both_themes` | R14 |
| `alpha_tokens_are_composited_before_contrast` | R14, R15 |
| `nontext_token_pairs_meet_aa_in_both_themes` | R15 |

The following manual checks are required until WP-7.8 adds component/E2E
coverage; both themes and both locales are exercised in each applicable row:

| Manual check | Requirement IDs |
|---|---|
| `localized_surfaces_have_no_hardcoded_copy`: Search, results/empty state, Local Files, health, Settings, Preview, notices, accessible names, native folder dialog/title | R2, R4, R8 |
| OS locale en, pt-BR, unsupported-only, and mixed unsupported/supported lists; each override and restart persistence | R3, R4 |
| OS light/dark at startup and live OS switching under `system`; Light/Dark override and restart persistence | R11, R12 |
| Native titlebar, window/webview background, first paint, native call rejection, and React StrictMode development startup | R13 |
| `focus_and_control_states_meet_contrast_targets`: keyboard focus, buttons, input, selected/hover states, meaningful icons, errors/notices, marks, placeholders, disabled controls; spot-check computed colors | R14, R15 |
| Portuguese expansion/wrapping at minimum window size, with no clipped action or unreadable ellipsis-only meaning | R2, R4, R14 |

Implementation PRs for WP-7.1/WP-7.2 also run the AGENTS.md §5 checks and
`npm run i18n:check`, `npm run theme:check`, and `npm run test:unit` from
`apps/desktop`. No hardware-dependent test is required.

### 6.2 Benchmark gates

| Gate | Dataset/split | Tier | Threshold | Baseline report |
|---|---|---|---|---|
| None | UI-only contracts; no S*, I*, R*, D*, O*, V*, or Q* behavior changes | N/A | N/A | N/A |

The implementation PR records the production frontend gzip-size delta for the
chosen i18n approach and catalogs as diagnostic evidence, without claiming a
speed improvement or introducing a locked size budget.

### 6.3 Inspection

- Diff touches only `apps/desktop` and its CI invocation; no engine crate or
  public engine API changes.
- `tauri.conf.json` no longer fixes `Dark`/`#0f1216`; capabilities gain only
  §4.5's narrow core permissions.
- No catalog request, translation service, analytics, telemetry, document
  content, query, filename, or unredacted path enters network/log output.
- Exactly two token sets exist; no raw palette literals are used by components;
  all §4.7 inventory rows are migrated or explicitly covered by §4.6.
- Every raw IPC error/dynamic diagnostic render site is removed or mapped per
  R8, and SPEC-0002 command/payload shapes remain unchanged.
- No production dependency is added under the recommended design. The normal
  TypeScript build, Prettier check, hardware-free Rust tests, and existing
  golden test remain green.

## 7. Risks and open questions

### 7.1 i18n implementation recommendation

**Recommendation: use the small in-house module specified in §4, built on the
webview's `Intl` APIs, with no production i18n library.** V1 needs only two
complete catalogs, one interpolation syntax, two plural categories, locale
resolution, fallback, and formatting. These are small, pure, unit-testable
contracts. This option adds zero third-party runtime dependency bytes, has no
new third-party license/notice surface, and keeps all data local. Its own
module/catalog size must still be measured in the WP-7.1 PR; “small” is not a
measured performance claim.

The library alternative is acceptable under ADR-0022 but is not recommended for
this scope: `i18next` and `react-i18next` are MIT-licensed, mature, and provide
broader plural/context/plugin features. The upstream project reports **17.4 KB
gzip** for `i18next` 27.2.2 with `react-i18next` 18.0.3, measured 2026-11-21 and
excluding application catalogs ([i18next size/license evidence](https://www.i18next.com/)).
That is a third-party published figure, not a Seeky bundle measurement. A
library would reduce custom message logic but add dependencies, notices, API
surface, and unused features; `i18next-cli` could replace part of the parity
script but would be another development dependency. If the maintainer prefers
the library, §4.1/§4.2 and R6 must be revised before H2 acceptance rather than
mixing both message syntaxes.

### 7.2 Risks and decisions

| Risk / question | Mitigation / owner / deadline | Blocking? |
|---|---|---|
| Untyped engine strings cannot be translated reliably | R8 uses operation-specific generic localized UI and never echoes unknown text; richer typed diagnostics belong to WP-7.6. Maintainer confirms this does not change SPEC-0002 before H2. | No; behavior specified |
| Regional Portuguese needs more than one translation or formatting convention | V1 deliberately has one `pt` catalog and `pt-BR` formatting, as §4.2 states. A separate `pt-PT` catalog/formatting policy requires a later spec version and P5 review. Maintainer confirms at H2. | No; v1 scope explicit |
| Intl output differs by webview/ICU version | Pin explicit locales/options, inject timezone in tests, run fixed examples in Node 24, and manually verify WebView2; never depend on the machine's implicit locale. | No |
| Hidden-native-window initialization could fail or delay first paint | Always show in the fallback path, use no network/polling, and test native rejection; record startup/size impact in the implementation PR. | No |
| Translation expansion or a new token pair regresses accessibility | Mandatory two-locale/two-theme manual matrix and exhaustive declared contrast pair matrix; WP-7.8 adds component/E2E coverage. | No |

### 7.3 Forward decisions for v2 (not v1 requirements)

Recorded so v2 starts from them; v1 must not implement them (R16). They
follow [ADR-0025](../adr/0025-automatic-provider-opt-in-gpu-tier-full-speed.md)
(Accepted) and the governor modes in
[SPEC-0007](SPEC-0007-indexing-pipeline.md) §5.1.

- **Full speed (WP-7.4).** Next to the semantic-indexing status, the UI
  offers Pause and Full speed. Full speed is an action, not a stored
  setting: it shows as active until the engine reports a return to the
  default mode (backlog drained, user off, AC power lost, restart), and the
  status line then reverts. While active on battery, the control says so.
  The UI renders state only from the typed governor events (SPEC-0007-R8);
  it never infers mode from strings.
- **Labels describe indexing, not “AI”** (ADR-0012: no AI badges). Proposed
  catalog entries, final keys set in v2:

  | Proposed key | en | pt |
  |---|---|---|
  | `indexing.semantic.label` | “Semantic indexing” | “Indexação semântica” |
  | `indexing.semantic.idle` | “Continues when idle” | “Continua quando ocioso” |
  | `indexing.action.pause` / `indexing.action.resume` | “Pause” / “Resume” | “Pausar” / “Retomar” |
  | `indexing.action.fullSpeed` | “Full speed” | “Velocidade máxima” |
  | `indexing.fullSpeed.active` | “Full speed until done” | “Velocidade máxima até concluir” |
  | `indexing.fullSpeed.onBattery` | “Full speed on battery” | “Velocidade máxima na bateria” |
  | `indexing.fullSpeed.endedPowerLost` | “Back to normal speed: charger disconnected” | “Velocidade normal: carregador desconectado” |

- **Provider override and GPU tier (WP-7.6).** Settings list `Auto`, `CPU`,
  and each validated provider on the machine; `Auto` describes itself as
  “fastest validated option for this computer” rather than naming a fixed
  order. The opt-in GPU quality tier, when it exists, is offered at most
  once after detection, dismissibly, and installed only after the user sees
  its download size and any reindex cost. The current v1 strings
  `settings.backend.cuda.*` describe the frozen PoC CUDA path and are
  replaced in v2.

There are no unresolved technical questions in this draft. H2 acceptance is the
maintainer's gate for the recommendations and explicit v1 scope above; this
file must remain **Draft** until that gate.

## 8. Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-11-27 | Initial Draft for desktop experience v1 (WP-7.1 localization and WP-7.2 themes); WP-7.3–WP-7.9 deferred to later versions |
| 0.1 | 2026-11-27 | Added §7.3 forward decisions for v2 (Full speed, indexing labels, provider override, opt-in GPU tier) from ADR-0025; no v1 requirement changed |
