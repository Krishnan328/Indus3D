import React, { useState, useEffect, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import { X, AlertCircle, Loader2 } from "lucide-react";
import { useStore, API } from "./store";
import { useThemeTokens } from "./theme";

export function MacroPromptModal() {
  const [promptData, setPromptData] = useState(null);
  const [submittingCmd, setSubmittingCmd] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const lastPromptId = useRef(null);

  const isDarkMode = useStore((s) => s.isDarkMode);
  const t = useThemeTokens();

  const fetchPrompt = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/prompt`);
      if (res.ok) {
        const data = await res.json();
        if (data && data.active && data.prompt) {
          setPromptData(data.prompt);
          if (lastPromptId.current !== data.prompt.id) setErrorMsg(null);
          lastPromptId.current = data.prompt.id;
        } else {
          setPromptData(null);
        }
      }
    } catch {
      // Offline / network failure: keep current or ignore
    }
  }, []);

  useEffect(() => {
    fetchPrompt();
    const timer = setInterval(fetchPrompt, 1000);
    return () => clearInterval(timer);
  }, [fetchPrompt]);

  const handleRespond = async (command) => {
    if (submittingCmd) return;
    setSubmittingCmd(command);
    setErrorMsg(null);
    try {
      const res = await fetch(`${API}/api/v1/printer/prompt/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command, prompt_id: promptData?.id }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setPromptData((current) => current?.id === promptData?.id ? null : current);
      } else {
        setErrorMsg(data.error || "Failed to execute prompt command");
      }
    } catch (e) {
      setErrorMsg(String(e));
    } finally {
      setSubmittingCmd(null);
    }
  };

  const handleDismiss = async () => {
    try {
      const res = await fetch(`${API}/api/v1/printer/prompt`, { method: "DELETE" });
      if (!res.ok) throw new Error("Could not dismiss the printer prompt");
      setPromptData(null);
    } catch (error) {
      setErrorMsg(error.message || "Could not dismiss the printer prompt");
    }
  };

  if (!promptData || !promptData.active) {
    return null;
  }

  const getBtnStyle = (style, isSubmitting) => {
    const base = "px-4 py-2 rounded-lg font-bold text-xs uppercase tracking-wider transition-all active:scale-95 flex items-center justify-center gap-2";
    if (isSubmitting) {
      return `${base} opacity-50 cursor-not-allowed bg-gray-600 text-white`;
    }
    if (style === "error") {
      return `${base} bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-900/30`;
    }
    if (style === "warning") {
      return `${base} bg-amber-600 hover:bg-amber-500 text-white shadow-lg shadow-amber-900/30`;
    }
    return `${base} bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-900/30`;
  };

  const modalContent = (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fadeIn">
      <div
        className={`w-full max-w-md rounded-xl border shadow-2xl overflow-hidden flex flex-col font-mono text-xs ${
          isDarkMode
            ? "bg-gray-900 border-gray-700 text-gray-100"
            : "bg-white border-gray-300 text-gray-900"
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800 bg-gray-800/40">
          <div className="flex items-center gap-2">
            <AlertCircle size={16} className="text-blue-400" />
            <h3 className="font-bold text-sm tracking-wide">
              {promptData.title || "Macro Action Prompt"}
            </h3>
          </div>
          <button
            type="button"
            onClick={handleDismiss}
            title="Dismiss prompt"
            className="p-1 rounded opacity-60 hover:opacity-100 hover:bg-white/10 transition-colors"
          >
            <X size={15} />
          </button>
        </div>

        {/* Body Text */}
        <div className="p-5 flex flex-col gap-2.5">
          {Array.isArray(promptData.text) && promptData.text.length > 0 ? (
            promptData.text.map((line, idx) => (
              <p key={idx} className="text-xs leading-relaxed opacity-90">
                {line}
              </p>
            ))
          ) : (
            <p className="text-xs opacity-70 italic">Please select an action:</p>
          )}

          {errorMsg && (
            <div className="p-2.5 rounded bg-red-950/40 border border-red-700/60 text-red-300 text-[11px]">
              {errorMsg}
            </div>
          )}
        </div>

        {/* Action Buttons */}
        {Array.isArray(promptData.buttons) && promptData.buttons.length > 0 && (
          <div className="px-5 pb-4 flex flex-wrap gap-2 justify-end">
            {promptData.buttons.map((btn, idx) => (
              <button
                key={idx}
                type="button"
                disabled={Boolean(submittingCmd)}
                onClick={() => handleRespond(btn.command)}
                className={getBtnStyle(btn.style, submittingCmd === btn.command)}
              >
                {submittingCmd === btn.command && <Loader2 size={13} className="animate-spin" />}
                <span>{btn.label || btn.command}</span>
              </button>
            ))}
          </div>
        )}

        {/* Footer Buttons */}
        {Array.isArray(promptData.footer_buttons) && promptData.footer_buttons.length > 0 && (
          <div className="px-5 py-3 border-t border-gray-800 bg-black/20 flex flex-wrap gap-2 justify-end">
            {promptData.footer_buttons.map((btn, idx) => (
              <button
                key={idx}
                type="button"
                disabled={Boolean(submittingCmd)}
                onClick={() => handleRespond(btn.command)}
                className={getBtnStyle(btn.style, submittingCmd === btn.command)}
              >
                {submittingCmd === btn.command && <Loader2 size={13} className="animate-spin" />}
                <span>{btn.label || btn.command}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  return typeof document !== "undefined" ? createPortal(modalContent, document.body) : null;
}
