// Resizable preview width (SPEC-0014 R17, §5.5). Pure logic; CSS applies the
// same bounds with clamp() so window resizes need no script.

export const PREVIEW_WIDTH_KEY = "seeky.ui.previewWidth.v1";
export const PREVIEW_DEFAULT = 420;
export const PREVIEW_MIN = 300;
export const PREVIEW_MAX_FRACTION = 0.6;
export const PREVIEW_STEP = 16;

export function maxPreviewWidth(containerWidth: number): number {
  return Math.max(
    PREVIEW_MIN,
    Math.floor(containerWidth * PREVIEW_MAX_FRACTION),
  );
}

export function clampPreviewWidth(width: number, containerWidth: number) {
  return Math.min(
    maxPreviewWidth(containerWidth),
    Math.max(PREVIEW_MIN, Math.round(width)),
  );
}

/** A stored width is used only when it is a finite integer ≥ the minimum. */
export function parsePreviewWidth(stored: string | null): number {
  if (stored === null || !/^\d+$/.test(stored)) return PREVIEW_DEFAULT;
  const value = Number(stored);
  return Number.isSafeInteger(value) && value >= PREVIEW_MIN
    ? value
    : PREVIEW_DEFAULT;
}

/** New width for a separator key press, or null when the key is not ours. */
export function keyboardResize(
  width: number,
  key: string,
  containerWidth: number,
): number | null {
  switch (key) {
    case "ArrowLeft":
      return clampPreviewWidth(width + PREVIEW_STEP, containerWidth);
    case "ArrowRight":
      return clampPreviewWidth(width - PREVIEW_STEP, containerWidth);
    case "Home":
      return PREVIEW_MIN;
    case "End":
      return maxPreviewWidth(containerWidth);
    default:
      return null;
  }
}
