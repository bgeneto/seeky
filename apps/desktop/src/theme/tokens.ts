// The two semantic color token sets (SPEC-0014 §4.4, R10; ADR-0012).
// This file is the single palette source: theme.ts turns it into
// `--color-<token>` CSS variables and the native background, and
// scripts/check-theme.mjs checks every declared pair for WCAG 2.2 AA
// contrast (R14, R15). Component CSS never uses palette literals.
//
// Surfaces and text colors are opaque. Only the state backgrounds (`*Bg`),
// `mark`, and `shadow` are translucent; the checker composites them over
// their real backdrop before measuring contrast.

export const light = {
  // Surfaces
  bg: "#f3f5f8",
  panel: "#ffffff",
  panelRaised: "#f7f9fb",
  sidebar: "#eaedf2",
  preview: "#fbfcfd",
  input: "#ffffff",
  hover: "#e6eaf0",
  selected: "#e2eafc",
  statusbar: "#eaedf2",
  // Borders and focus
  border: "#d8dde5",
  borderStrong: "#727c8b",
  focusRing: "#2456c7",
  // Text
  text: "#141a22",
  muted: "#465161",
  subtle: "#566172",
  placeholder: "#5e6979",
  onAccent: "#ffffff",
  onMark: "#141a22",
  // Accent and action
  accent: "#2c5bcc",
  accentHover: "#244db0",
  accentText: "#234fb5",
  accentSecondary: "#0b6e63",
  // Semantic states
  danger: "#b3261e",
  dangerBg: "rgba(220, 38, 38, 0.08)",
  warning: "#8a4b00",
  warningBg: "rgba(217, 119, 6, 0.12)",
  success: "#0b6e63",
  successBg: "rgba(13, 148, 136, 0.1)",
  info: "#5b3cc4",
  infoBg: "rgba(109, 90, 230, 0.1)",
  // Highlight and disabled
  mark: "rgba(44, 91, 204, 0.16)",
  disabled: "#e3e7ec",
  onDisabled: "#7d8693",
  // Effects (exempt from contrast ratios)
  shadow: "rgba(20, 30, 50, 0.08)",
};

export const dark: Record<keyof typeof light, string> = {
  // Surfaces
  bg: "#0b0e12",
  panel: "#11161d",
  panelRaised: "#151c25",
  sidebar: "#080b0f",
  preview: "#0d1117",
  input: "#10151c",
  hover: "#19212b",
  selected: "#192335",
  statusbar: "#080b0f",
  // Borders and focus
  border: "#242c37",
  borderStrong: "#5f6c7d",
  focusRing: "#8fb2ff",
  // Text
  text: "#e8edf4",
  muted: "#a0abb9",
  subtle: "#8794a5",
  placeholder: "#8692a3",
  onAccent: "#0b0e12",
  onMark: "#eef3ff",
  // Accent and action
  accent: "#6d9bff",
  accentHover: "#86adff",
  accentText: "#a3bdff",
  accentSecondary: "#71e3d3",
  // Semantic states
  danger: "#ffa3a3",
  dangerBg: "rgba(255, 80, 80, 0.1)",
  warning: "#ffc978",
  warningBg: "rgba(255, 190, 100, 0.1)",
  success: "#8be9dc",
  successBg: "rgba(113, 227, 211, 0.08)",
  info: "#c9c1ff",
  infoBg: "rgba(160, 150, 255, 0.1)",
  // Highlight and disabled
  mark: "rgba(109, 155, 255, 0.3)",
  disabled: "#161c24",
  onDisabled: "#5d6775",
  // Effects (exempt from contrast ratios)
  shadow: "rgba(0, 0, 0, 0.3)",
};

export type SemanticToken = keyof typeof light;
export type ThemeTokens = Record<SemanticToken, string>;
