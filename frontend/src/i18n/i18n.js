/**
 * i18n.js
 * -------
 * Lightweight, high-performance localization engine for Indus3D.
 * Supports dot-notated key resolution, variable interpolation, and fallbacks.
 */

import en from "./locales/en.json" with { type: "json" };
import de from "./locales/de.json" with { type: "json" };
import fr from "./locales/fr.json" with { type: "json" };
import es from "./locales/es.json" with { type: "json" };
import zh from "./locales/zh.json" with { type: "json" };

export const SUPPORTED_LANGUAGES = [
  { code: "en", label: "English" },
  { code: "de", label: "Deutsch" },
  { code: "fr", label: "Français" },
  { code: "es", label: "Español" },
  { code: "zh", label: "简体中文" },
];

const DICTIONARIES = {
  en,
  de,
  fr,
  es,
  zh,
};

let currentLanguage = "en";
const listeners = new Set();

/**
 * Resolve a dot-notated key in an object.
 */
function resolveKey(obj, path) {
  if (!obj || typeof obj !== "object") return undefined;
  const parts = path.split(".");
  let cur = obj;
  for (const part of parts) {
    if (cur === undefined || cur === null) return undefined;
    cur = cur[part];
  }
  return cur;
}

/**
 * Translate a key string into the current language, interpolating params.
 */
export function t(key, params = {}, lang = currentLanguage) {
  const dict = DICTIONARIES[lang] || DICTIONARIES.en;
  let text = resolveKey(dict, key);

  // Fallback to English if missing
  if (text === undefined && lang !== "en") {
    text = resolveKey(DICTIONARIES.en, key);
  }

  if (text === undefined) {
    return key;
  }

  if (typeof text !== "string") {
    return text;
  }

  // Interpolate {var}
  return text.replace(/\{(\w+)\}/g, (_, k) => (params[k] !== undefined ? params[k] : `{${k}}`));
}

export function getLanguage() {
  return currentLanguage;
}

export function setLanguage(lang) {
  if (DICTIONARIES[lang]) {
    currentLanguage = lang;
    try {
      localStorage.setItem("indus3d_language", lang);
    } catch {
      // quota or private mode
    }
    listeners.forEach((fn) => fn(lang));
  }
}

export function initLanguage() {
  try {
    const saved = localStorage.getItem("indus3d_language");
    if (saved && DICTIONARIES[saved]) {
      currentLanguage = saved;
    }
  } catch {
    // ignore
  }
}

// React hook for reactive language subscription
import { useState, useEffect } from "react";

export function useTranslation() {
  const [lang, setLang] = useState(currentLanguage);

  useEffect(() => {
    const handler = (newLang) => setLang(newLang);
    listeners.add(handler);
    return () => listeners.delete(handler);
  }, []);

  return {
    t: (key, params) => t(key, params, lang),
    language: lang,
    setLanguage,
    languages: SUPPORTED_LANGUAGES,
  };
}
