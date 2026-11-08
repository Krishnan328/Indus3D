import { useThemeTokens, useIsBrutalist, useIsSoft } from "../theme";

// Theme-derived class strings shared by the file manager, queue and editor.
export function useUi() {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const soft = useIsSoft();
  const input = brutalist ? "bg-white border-2 border-[#111] text-[#111] rounded-none"
    : soft ? (t.softInput || "") : "bg-black/20 border border-white/10 rounded-md";
  const btn = brutalist ? "border-2 border-[#111] bg-white text-[#111] hover:bg-[#FFE9A8] rounded-none font-mono"
    : "bg-white/5 hover:bg-white/10 border border-white/10 rounded-md";
  const primary = brutalist ? "border-2 border-[#111] bg-[#B7E4C7] text-[#111] hover:bg-[#9fd9b3] rounded-none font-mono"
    : "bg-emerald-700 hover:bg-emerald-600 text-white rounded-md";
  const danger = brutalist ? "border-2 border-[#111] bg-[#F4A6A0] text-[#111] hover:bg-[#ef8f88] rounded-none font-mono"
    : "bg-red-800 hover:bg-red-700 text-white rounded-md";
  const menu = brutalist ? "bg-white border-[3px] border-[#111] text-[#111] shadow-[4px_4px_0_0_#111]"
    : "bg-gray-900 border border-gray-700 text-gray-100 shadow-xl rounded-lg";
  return { t, brutalist, soft, input, btn, primary, danger, menu };
}
