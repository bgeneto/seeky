// Localized replacements for raw IPC errors and untyped engine strings
// (SPEC-0014 §4.6, §4.7, R8). Raw error text is diagnostic data, never UI.
import type { MessageKey } from "./messages.ts";

export const OPERATION_ERROR_KEYS = {
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
} as const satisfies Record<string, MessageKey>;

export type Operation = keyof typeof OPERATION_ERROR_KEYS;

export function operationErrorKey(operation: string): MessageKey {
  return Object.hasOwn(OPERATION_ERROR_KEYS, operation)
    ? OPERATION_ERROR_KEYS[operation as Operation]
    : "common.error.generic";
}

const PHASE_KEYS: Record<string, MessageKey> = {
  scan: "indexing.progress.scanning",
  extract: "indexing.progress.extracting",
  done: "common.state.applyingChanges",
};

/** Known progress phases get a localized label; anything else is generic. */
export function progressPhaseKey(phase: string | null | undefined): MessageKey {
  return phase && Object.hasOwn(PHASE_KEYS, phase)
    ? PHASE_KEYS[phase]
    : "common.state.working";
}
