import React from "react";
import { Sun, Moon } from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist, useIsSoft, THEME_LIST } from "./theme";

export function ThemeSwitcher() {
  const theme         = useStore((s) => s.theme);
  const setTheme      = useStore((s) => s.setTheme);
  const isDarkMode    = useStore((s) => s.isDarkMode);
  const setIsDarkMode = useStore((s) => s.setIsDarkMode);
  const t             = useThemeTokens();
  const brutalist     = useIsBrutalist();
  const soft          = useIsSoft();

  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-1">
        {THEME_LIST.map(({ id, label }) => {
          const active = theme === id;
          return (
            <button
              key={id}
              onClick={() => setTheme(id)}
              title={`${label} theme`}
              className={`px-2.5 py-1 text-[10px] transition-all ${soft ? "font-semibold" : "font-bold uppercase tracking-widest"}
                ${t.chip}
                ${active ? t.railBtnActive : `${brutalist ? "bg-white" : "bg-transparent"} ${t.railBtn}`}`}
            >
              {label}
            </button>
          );
        })}
      </div>
      {theme === "classic" && (
        <button
          onClick={() => setIsDarkMode(!isDarkMode)}
          title="Toggle light/dark"
          className={`p-1.5 ${t.chip} ${t.railBtn}`}
        >
          {isDarkMode ? <Sun size={13} /> : <Moon size={13} />}
        </button>
      )}
    </div>
  );
}
