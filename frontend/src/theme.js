/**
 * theme.js
 * ---------
 * Single source of truth for Indus3D's visual themes. Every component reads
 * its colors/borders/shadows from here instead of hardcoding Tailwind
 * classes, so adding a theme means adding one object here — not editing
 * every component.
 *
 * "classic" preserves the original dark/light dashboard exactly (byte-for-
 * byte equivalent class strings to what App.jsx used before theming existed).
 * "workshop" and "blueprint" are the brutalist+pastel themes: thick black
 * borders, hard offset shadows instead of blur, square corners.
 *
 * Usage in a component:
 *   import { useThemeTokens } from "./theme";
 *   const t = useThemeTokens();
 *   <div className={t.panel}> ... </div>
 */

import { useStore } from "./store";

const classicDark = {
  page:      "bg-gray-950 text-gray-100",
  header:    "bg-gray-900 border-gray-800 text-gray-400",
  panel:     "bg-gray-950 border-gray-800/80 rounded-xl border",
  panelSolid:"bg-gray-900 border-gray-800 rounded-xl border",
  cell:      "bg-gray-900 border-gray-800 text-gray-200 rounded border",
  chip:      "rounded-full",
  label:     "text-[9px] uppercase tracking-widest block mb-1 opacity-60",
  heading:   "font-semibold tracking-wide uppercase text-sm",
  border:    "border-gray-800",
  railBtn:   "text-gray-500 hover:text-gray-200",
  railBtnActive: "bg-gray-100 text-gray-900",
  shadow:    "",
  accentBg:  "bg-blue-600",
};

const classicLight = {
  page:      "bg-gray-100 text-gray-900",
  header:    "bg-gray-50 border-gray-200 text-gray-500",
  panel:     "bg-gray-50 border-gray-200 rounded-xl border",
  panelSolid:"bg-white border-gray-200 rounded-xl border shadow-sm",
  cell:      "bg-white border-gray-200 text-gray-800 rounded border shadow-sm",
  chip:      "rounded-full",
  label:     "text-[9px] uppercase tracking-widest block mb-1 opacity-60",
  heading:   "font-semibold tracking-wide uppercase text-sm",
  border:    "border-gray-300",
  railBtn:   "text-gray-400 hover:text-gray-700",
  railBtnActive: "bg-gray-800 text-white",
  shadow:    "",
  accentBg:  "bg-blue-600",
};

function brutal({ bg, panelBg, cellBg, ink, accent }) {
  const shadow = "shadow-[5px_5px_0_0_#111]";
  const shadowSm = "shadow-[3px_3px_0_0_#111]";
  return {
    page:      `${bg} text-[#111]`,
    header:    `${panelBg} border-[#111] text-[#111] border-[3px] ${shadowSm}`,
    panel:     `${panelBg} border-[#111] border-[3px] rounded-none ${shadow}`,
    panelSolid:`${panelBg} border-[#111] border-[3px] rounded-none ${shadow}`,
    cell:      `${cellBg} border-[#111] text-[#111] border-2 rounded-none font-mono`,
    chip:      "rounded-none border-2 border-[#111] font-mono",
    label:     "text-[9px] uppercase tracking-widest block mb-1 opacity-70 font-mono font-bold",
    heading:   "font-bold tracking-wide uppercase text-sm font-mono",
    border:    "border-[#111]",
    railBtn:   "text-[#111] opacity-60 hover:opacity-100",
    railBtnActive: "bg-[#111] text-white",
    shadow,
    shadowSm,
    accentBg:  accent,
    ink,
  };
}

const workshop = brutal({
  bg: "bg-[#F4F1E8]",
  panelBg: "bg-white",
  cellBg: "bg-[#F4F1E8]",
  ink: "#111111",
  accent: "bg-[#FFE9A8]",
});

const blueprint = brutal({
  bg: "bg-[#E8EEF2]",
  panelBg: "bg-white",
  cellBg: "bg-[#E8EEF2]",
  ink: "#111111",
  accent: "bg-[#FFD6AA]",
});

function soft({ bg, panelBg, cellBg, borderClass, inkClass, ink, accentBg, accentInk }) {
  const shadow = "shadow-[0_10px_30px_rgba(58,51,42,0.10)]";
  const shadowSm = "shadow-[0_3px_12px_rgba(58,51,42,0.07)]";
  return {
    page: `${bg} ${inkClass}`, header: `${panelBg} ${borderClass} ${inkClass} border ${shadowSm}`,
    panel: `${panelBg} ${borderClass} border rounded-3xl ${shadow}`,
    panelSolid: `${panelBg} ${borderClass} border rounded-3xl ${shadow}`,
    cell: `${cellBg} ${borderClass} ${inkClass} border rounded-2xl`, chip: "rounded-full",
    label: "text-[9px] uppercase tracking-widest block mb-1 opacity-45 font-semibold",
    heading: "font-semibold tracking-wide text-sm", border: borderClass,
    railBtn: `${inkClass} opacity-45 hover:opacity-90`, railBtnActive: `${accentBg} ${accentInk}`,
    shadow, shadowSm, accentBg, ink, softInput: `${cellBg} ${borderClass} border ${inkClass} rounded-xl`,
  };
}

const creme = soft({
  bg: "bg-[#F1E7D6]", panelBg: "bg-white", cellBg: "bg-[#F8F2E6]",
  borderClass: "border-[#EAE0CC]", inkClass: "text-[#3A332A]", ink: "#3A332A",
  accentBg: "bg-[#AEC6A3]", accentInk: "text-[#2E3B28]",
});

export const PASTELS = {
  workshop: { mint: "#B7E4C7", butter: "#FFE9A8", coral: "#F4A6A0", lav: "#D9C6F0" },
  blueprint:{ mint: "#A8D6EE", butter: "#FFD6AA", coral: "#FFB3BA", lav: "#C4D6E8" },
};

const THEMES = {
  classic:   { dark: classicDark, light: classicLight, brutalist: false, soft: false },
  workshop:  { dark: workshop,    light: workshop,     brutalist: true,  soft: false },
  blueprint: { dark: blueprint,   light: blueprint,     brutalist: true,  soft: false },
  creme:     { dark: creme,       light: creme,         brutalist: false, soft: true },
};

export function getThemeTokens(theme, isDarkMode) {
  const entry = THEMES[theme] || THEMES.classic;
  return entry.dark && !entry.brutalist && !entry.soft && !isDarkMode ? entry.light : (isDarkMode ? entry.dark : entry.light);
}

export function useThemeTokens() {
  const theme      = useStore((s) => s.theme);
  const isDarkMode = useStore((s) => s.isDarkMode);
  return getThemeTokens(theme, isDarkMode);
}

export function useIsBrutalist() {
  const theme = useStore((s) => s.theme);
  return THEMES[theme]?.brutalist ?? false;
}

export function useIsSoft() {
  const theme = useStore((s) => s.theme);
  return THEMES[theme]?.soft ?? false;
}

export const THEME_LIST = [
  { id: "classic",   label: "Classic" },
  { id: "workshop",  label: "Workshop" },
  { id: "blueprint", label: "Blueprint" },
  { id: "creme",     label: "Creme" },
];
