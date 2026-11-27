// Local UI preferences (SPEC-0014 §4.2): only small enums, in webview
// localStorage, with an in-memory fallback when storage is unavailable.

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface PreferenceStore {
  read(key: string): string | null;
  write(key: string, value: string): void;
}

export function createPreferenceStore(
  getStorage: () => StorageLike | null | undefined,
): PreferenceStore {
  const memory = new Map<string, string>();

  function storage(): StorageLike | null {
    try {
      return getStorage() ?? null;
    } catch {
      return null;
    }
  }

  return {
    read(key) {
      if (memory.has(key)) return memory.get(key) ?? null;
      try {
        return storage()?.getItem(key) ?? null;
      } catch {
        return null;
      }
    },
    write(key, value) {
      memory.set(key, value);
      try {
        storage()?.setItem(key, value);
      } catch {
        // Denied or full storage: the in-memory value lasts for the session.
      }
    },
  };
}

export function browserStorage(): StorageLike | null {
  return typeof window === "undefined" ? null : window.localStorage;
}
