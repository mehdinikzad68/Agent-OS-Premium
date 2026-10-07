// Status colors, accent colors, palette and the hex->rgba helper.
// Minified names in bundle: De (STATUS_COLOR), ur (SUN), lt (MAG), vt (PALETTE), xe (hexA).

export const STATUS_COLOR = {
  running: "#4fd6ff",
  awaiting: "#ff9a52",
  complete: "#5ff0a8",
  offline: "#6b7fa6",
};

export const SUN = "#38e8ff";
export const MAG = "#c77dff";

export const PALETTE = ["#38e8ff", "#5ff0a8", "#c77dff", "#ffd166", "#ff7eb6", "#7aa2ff"];

export const hexA = (hex, alpha) => {
  const h = hex.replace("#", "");
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
};
