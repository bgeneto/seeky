// SPEC-0014-R17 (§5.5): resizable preview width bounds and keyboard steps.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  PREVIEW_DEFAULT,
  PREVIEW_MIN,
  clampPreviewWidth,
  keyboardResize,
  maxPreviewWidth,
  parsePreviewWidth,
} from "../../src/layout/previewWidth.ts";

describe("resizable preview (SPEC-0014 R17)", () => {
  test("preview_width_is_clamped_to_container", () => {
    assert.equal(PREVIEW_DEFAULT, 420);
    assert.equal(PREVIEW_MIN, 300);
    assert.equal(maxPreviewWidth(1000), 600);
    assert.equal(clampPreviewWidth(900, 1000), 600);
    assert.equal(clampPreviewWidth(100, 1000), 300);
    assert.equal(clampPreviewWidth(455.6, 1000), 456);
    // A narrow content area never pushes the maximum below the minimum.
    assert.equal(maxPreviewWidth(400), 300);
    assert.equal(clampPreviewWidth(500, 400), 300);
  });

  test("invalid_stored_preview_width_uses_default", () => {
    assert.equal(parsePreviewWidth(null), 420);
    assert.equal(parsePreviewWidth(""), 420);
    assert.equal(parsePreviewWidth("abc"), 420);
    assert.equal(parsePreviewWidth("299"), 420);
    assert.equal(parsePreviewWidth("12.5"), 420);
    assert.equal(parsePreviewWidth("Infinity"), 420);
    assert.equal(parsePreviewWidth("512"), 512);
  });

  test("keyboard_resize_steps_and_clamps", () => {
    // The preview sits on the right: moving the separator left widens it.
    assert.equal(keyboardResize(420, "ArrowLeft", 1000), 436);
    assert.equal(keyboardResize(420, "ArrowRight", 1000), 404);
    assert.equal(keyboardResize(595, "ArrowLeft", 1000), 600);
    assert.equal(keyboardResize(305, "ArrowRight", 1000), 300);
    assert.equal(keyboardResize(420, "Home", 1000), 300);
    assert.equal(keyboardResize(420, "End", 1000), 600);
    assert.equal(keyboardResize(420, "Enter", 1000), null);
  });
});
