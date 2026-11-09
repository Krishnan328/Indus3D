import React from "react";
import { Globe } from "lucide-react";
import { useTranslation } from "./i18n/i18n";
import { useThemeTokens, useIsBrutalist, useIsSoft } from "./theme";

export function LanguageSwitcher() {
  const { language, setLanguage, languages } = useTranslation();
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const soft = useIsSoft();

  return (
    <div className="flex items-center gap-1.5" title="Change Language">
      <Globe size={13} className="opacity-50 shrink-0" />
      <select
        value={language}
        onChange={(e) => setLanguage(e.target.value)}
        className={`px-2 py-1 text-[10px] font-bold uppercase tracking-wider outline-none cursor-pointer
          ${t.chip}
          ${brutalist ? "bg-white text-[#111] border-2 border-[#111]" : soft ? "bg-black/[0.04] text-gray-700" : "bg-white/5 text-gray-300 border border-white/10"}`}
      >
        {languages.map((l) => (
          <option key={l.code} value={l.code} className="bg-gray-900 text-white">
            {l.code.toUpperCase()} — {l.label}
          </option>
        ))}
      </select>
    </div>
  );
}
