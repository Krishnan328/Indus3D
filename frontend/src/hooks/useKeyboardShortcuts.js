/**
 * useKeyboardShortcuts.js
 * -----------------------
 * Global keyboard shortcuts listener for Indus3D matching Mainsail/Fluidd conventions.
 */

import { useEffect } from "react";
import { useStore } from "../store";

export function useKeyboardShortcuts({
  onToggleShortcuts,
  onEmergencyStop,
  onCloseModals,
  onFocusConsole,
  setPage,
}) {
  const isPrinting = useStore((s) => s.telemetry?.state === "printing");
  const jog = useStore((s) => s.jog);

  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ignore if user is currently typing inside an input, textarea, select, or contenteditable element
      const tag = (e.target?.tagName || "").toLowerCase();
      const isInput = tag === "input" || tag === "textarea" || tag === "select" || e.target?.isContentEditable;

      // Escape always closes modals even if inside an input
      if (e.key === "Escape") {
        if (onCloseModals) onCloseModals();
        return;
      }

      if (isInput) {
        return;
      }

      // '?' opens shortcuts modal
      if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        if (onToggleShortcuts) onToggleShortcuts();
        return;
      }

      // Space -> Emergency stop
      if (e.code === "Space" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        if (onEmergencyStop) onEmergencyStop();
        return;
      }

      // Ctrl+K or '/' -> Focus console
      if ((e.key === "/" && !e.ctrlKey && !e.metaKey) || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) {
        e.preventDefault();
        if (onFocusConsole) onFocusConsole();
        return;
      }

      // Number keys 1-7 for tab navigation
      if (!e.ctrlKey && !e.metaKey && !e.altKey) {
        if (e.key === "1") { e.preventDefault(); setPage("dashboard"); return; }
        if (e.key === "2") { e.preventDefault(); setPage("fleet"); return; }
        if (e.key === "3") { e.preventDefault(); setPage("twin"); return; }
        if (e.key === "4") { e.preventDefault(); setPage("lab"); return; }
        if (e.key === "5") { e.preventDefault(); setPage("files"); return; }
        if (e.key === "6") { e.preventDefault(); setPage("history"); return; }
        if (e.key === "7") { e.preventDefault(); setPage("system"); return; }
      }

      // Jogs (only if not printing)
      if (!isPrinting) {
        if (e.altKey && e.key === "ArrowLeft") {
          e.preventDefault();
          if (jog) jog("X", -10);
          return;
        }
        if (e.altKey && e.key === "ArrowRight") {
          e.preventDefault();
          if (jog) jog("X", 10);
          return;
        }
        if (e.altKey && e.key === "ArrowUp") {
          e.preventDefault();
          if (jog) jog("Y", 10);
          return;
        }
        if (e.altKey && e.key === "ArrowDown") {
          e.preventDefault();
          if (jog) jog("Y", -10);
          return;
        }
        if (e.key === "PageUp") {
          e.preventDefault();
          if (jog) jog("Z", 1);
          return;
        }
        if (e.key === "PageDown") {
          e.preventDefault();
          if (jog) jog("Z", -1);
          return;
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onToggleShortcuts, onEmergencyStop, onCloseModals, onFocusConsole, setPage, isPrinting, jog]);
}
