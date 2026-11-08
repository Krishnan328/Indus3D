import React, { useState } from "react";
import {
  AlertTriangle, RotateCcw, RefreshCw, Download, Copy, Check, TerminalSquare, WifiOff
} from "lucide-react";
import { useStore, API } from "./store";
import { useIsBrutalist } from "./theme";

export function KlippyStateBanner() {
  const telemetry = useStore((s) => s.telemetry);
  const powerAction = useStore((s) => s.powerAction);
  const brutalist = useIsBrutalist();

  const [loadingAction, setLoadingAction] = useState(null);
  const [copied, setCopied] = useState(false);
  const [actionFeedback, setActionFeedback] = useState("");
  const [checking, setChecking] = useState(false);

  const checkStatus = async () => {
    setChecking(true);
    setActionFeedback("Checking Klipper status...");
    try {
      const res = await fetch(`${API}/api/v1/twin/state`);
      if (res.ok) {
        const data = await res.json();
        const state = (data.klippy_state || "ready").toLowerCase();
        if (state === "ready" && data.klippy_connected !== false) {
          useStore.setState((s) => ({
            telemetry: {
              ...s.telemetry,
              klippy_state: "ready",
              klippy_connected: true,
              state_message: data.state_message || "Printer is ready",
              fault: false,
            },
          }));
          setActionFeedback("Printer is ready!");
          return true;
        } else {
          setActionFeedback(`Klipper state: ${data.klippy_state || "unknown"}`);
        }
      }
    } catch (err) {
      setActionFeedback(`Status check failed: ${err.message || String(err)}`);
    } finally {
      setChecking(false);
      setTimeout(() => setActionFeedback(""), 4000);
    }
    return false;
  };

  const online = telemetry?.online !== false;
  const klippyState = (telemetry?.klippy_state || "ready").toLowerCase();
  const klippyConnected = telemetry?.klippy_connected !== false;
  const stateMessage = telemetry?.state_message || "";

  const isShutdown = klippyState === "shutdown";
  const isDisconnected = klippyState === "disconnected" || (!klippyConnected && online);
  const isError = klippyState === "error";
  const isStartup = klippyState === "startup";
  const isOffline = !online || klippyState === "offline";

  // If Klipper and Moonraker are fully ready and online, don't show the banner
  if (!isShutdown && !isDisconnected && !isError && !isStartup && !isOffline) {
    return null;
  }

  // Header Title matching Mainsail format
  const title = isShutdown
    ? "Klipper reports: SHUTDOWN"
    : isError
    ? "Klipper reports: ERROR"
    : isOffline
    ? "Moonraker reports: OFFLINE"
    : isDisconnected
    ? "Moonraker reports: KLIPPER DISCONNECTED"
    : "Klipper reports: STARTUP";

  const handleAction = async (actionType) => {
    setLoadingAction(actionType);
    setActionFeedback("");
    try {
      const res = await powerAction(actionType);
      if (res && res.error) {
        setActionFeedback(`Error: ${res.error}`);
        setLoadingAction(null);
        return;
      }

      if (actionType === "restart" || actionType === "firmware_restart") {
        setActionFeedback("Restart command sent. Waiting for Klipper to come online...");
        // Poll twin state up to 15 times (every 800ms) to detect recovery
        let recovered = false;
        for (let i = 0; i < 15; i++) {
          await new Promise((resolve) => setTimeout(resolve, 800));
          try {
            const checkRes = await fetch(`${API}/api/v1/twin/state`);
            if (checkRes.ok) {
              const checkData = await checkRes.json();
              const state = (checkData.klippy_state || "").toLowerCase();
              if (state === "ready" && checkData.klippy_connected !== false) {
                useStore.setState((s) => ({
                  telemetry: {
                    ...s.telemetry,
                    klippy_state: "ready",
                    klippy_connected: true,
                    state_message: checkData.state_message || "Printer is ready",
                    fault: false,
                  },
                }));
                recovered = true;
                setActionFeedback("Klipper is ready!");
                break;
              }
            }
          } catch {
            // Keep the banner visible until Klipper reports a recovered state.
          }
        }
        if (!recovered) {
          setActionFeedback("Restart sent. If Klipper has recovered, click 'Check Status'.");
        }
      } else {
        setActionFeedback(`Command sent successfully.`);
      }
    } catch (err) {
      setActionFeedback(`Failed: ${err.message || String(err)}`);
    } finally {
      setTimeout(() => setLoadingAction(null), 1200);
      setTimeout(() => setActionFeedback(""), 6000);
    }
  };

  const copyMessage = () => {
    if (!stateMessage) return;
    navigator.clipboard.writeText(stateMessage);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadLog = (service) => {
    window.open(`${API}/api/v1/system/logs/${service}`, "_blank");
  };

  return (
    <div
      className={`mb-4 transition-all duration-200 overflow-hidden shrink-0 ${
        brutalist
          ? "border-[3px] border-[#111] bg-[#FFF2CC] text-[#111] p-5 shadow-[4px_4px_0px_#111]"
          : "rounded-xl border border-amber-600/50 bg-[#161310] text-amber-400 p-5 shadow-2xl shadow-black/80"
      }`}
    >
      {/* 1. Mainsail-style Warning Header */}
      <div className="flex items-center justify-between pb-3 border-b border-amber-500/20">
        <div className="flex items-center gap-2.5">
          <AlertTriangle size={22} className="text-amber-400 shrink-0 stroke-[2.5]" />
          <h2 className="text-base md:text-lg font-extrabold tracking-wide text-amber-400 uppercase font-mono">
            {title}
          </h2>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={checkStatus}
            disabled={checking}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-mono font-bold transition-all rounded ${
              brutalist
                ? "border-2 border-[#111] bg-white text-[#111] hover:bg-gray-100"
                : "bg-amber-950/40 hover:bg-amber-900/60 active:bg-amber-950 text-amber-300 border border-amber-500/30"
            }`}
            title="Check if Klipper has recovered and update status"
          >
            <RefreshCw size={12} className={checking ? "animate-spin text-amber-400" : "text-amber-400"} />
            <span>{checking ? "Checking…" : "Check Status"}</span>
          </button>
          {stateMessage && (
            <button
              onClick={copyMessage}
              className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-mono font-bold transition-all rounded ${
                brutalist
                  ? "border-2 border-[#111] bg-white text-[#111] hover:bg-gray-100"
                  : "bg-amber-950/40 hover:bg-amber-900/60 active:bg-amber-950 text-amber-300 border border-amber-500/30"
              }`}
              title="Copy error details to clipboard"
            >
              {copied ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
              <span>{copied ? "Copied" : "Copy Error"}</span>
            </button>
          )}
          <span
            className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded font-bold ${
              brutalist
                ? "border border-[#111] bg-black text-white"
                : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
            }`}
          >
            {klippyState}
          </span>
        </div>
      </div>

      {/* 2. Error Message Body in Amber Monospace */}
      {stateMessage ? (
        <pre
          className={`my-4 p-3.5 rounded-lg font-mono text-xs md:text-sm overflow-x-auto whitespace-pre-wrap select-text leading-relaxed ${
            brutalist
              ? "bg-black text-[#00FF66] border-2 border-[#111]"
              : "bg-[#0d0b09] text-amber-200/90 border border-amber-500/25"
          }`}
        >
          {stateMessage}
        </pre>
      ) : (
        <div className="my-4 p-3 rounded-lg font-mono text-xs text-amber-300/80 bg-black/30 border border-amber-500/20">
          {isOffline
            ? "Lost communication with Moonraker. Check host power, Moonraker systemd service, or local network."
            : isDisconnected
            ? "Lost communication with Klippy host process. Firmware or host daemon may be restarting."
            : "Printer is shutdown. Review logs or execute firmware restart to recover."}
        </div>
      )}

      {/* Feedback Message */}
      {actionFeedback && (
        <div className="mb-3 text-xs font-mono font-bold px-3 py-1.5 rounded bg-black/60 border border-amber-500/40 text-amber-300 inline-block animate-fade-in">
          {actionFeedback}
        </div>
      )}

      {/* 3. Action Buttons in Mainsail 2x2 Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {/* RESTART */}
        <button
          onClick={() => handleAction("restart")}
          disabled={loadingAction !== null}
          className={`flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg font-bold text-xs uppercase tracking-wider transition-all shadow-sm ${
            brutalist
              ? "bg-white text-[#111] border-2 border-[#111] hover:bg-gray-200 active:scale-98"
              : "bg-[#211a14] hover:bg-[#2c231b] active:bg-[#1a140f] text-amber-300 border border-amber-500/30"
          } ${loadingAction === "restart" ? "opacity-60 cursor-wait" : ""}`}
          title="Restart Klippy host software process (RESTART)"
        >
          <RotateCcw
            size={15}
            className={`text-amber-400 ${loadingAction === "restart" ? "animate-spin" : ""}`}
          />
          <span>Restart</span>
        </button>

        {/* KLIPPER LOG */}
        <button
          onClick={() => downloadLog("klipper")}
          className={`flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg font-bold text-xs uppercase tracking-wider transition-all shadow-sm ${
            brutalist
              ? "bg-white text-[#111] border-2 border-[#111] hover:bg-gray-200 active:scale-98"
              : "bg-[#211a14] hover:bg-[#2c231b] active:bg-[#1a140f] text-amber-300 border border-amber-500/30"
          }`}
          title="Download full Klipper host log (klippy.log)"
        >
          <Download size={15} className="text-amber-400" />
          <span>Klipper Log</span>
        </button>

        {/* FIRMWARE RESTART */}
        <button
          onClick={() => handleAction("firmware_restart")}
          disabled={loadingAction !== null}
          className={`flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg font-bold text-xs uppercase tracking-wider transition-all shadow-md ${
            brutalist
              ? "bg-[#FFAA00] text-[#111] border-2 border-[#111] hover:bg-black hover:text-white active:scale-98"
              : "bg-amber-500 hover:bg-amber-400 active:bg-amber-600 text-black border border-amber-400 font-extrabold"
          } ${loadingAction === "firmware_restart" ? "opacity-60 cursor-wait" : ""}`}
          title="Reset firmware on microcontrollers and restart host software (FIRMWARE_RESTART)"
        >
          <RefreshCw
            size={15}
            className={loadingAction === "firmware_restart" ? "animate-spin" : ""}
          />
          <span>Firmware Restart</span>
        </button>

        {/* MOONRAKER LOG */}
        <button
          onClick={() => downloadLog("moonraker")}
          className={`flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg font-bold text-xs uppercase tracking-wider transition-all shadow-sm ${
            brutalist
              ? "bg-white text-[#111] border-2 border-[#111] hover:bg-gray-200 active:scale-98"
              : "bg-[#211a14] hover:bg-[#2c231b] active:bg-[#1a140f] text-amber-300 border border-amber-500/30"
          }`}
          title="Download Moonraker API server log (moonraker.log)"
        >
          <Download size={15} className="text-amber-400" />
          <span>Moonraker Log</span>
        </button>

        {/* RESTART MOONRAKER (if offline) */}
        {isOffline && (
          <button
            onClick={() => handleAction("server_restart")}
            disabled={loadingAction !== null}
            className={`col-span-1 sm:col-span-2 flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg font-bold text-xs uppercase tracking-wider transition-all ${
              brutalist
                ? "bg-[#32E0C4] text-[#111] border-2 border-[#111] hover:bg-black hover:text-white"
                : "bg-blue-600 hover:bg-blue-500 text-white"
            } ${loadingAction === "server_restart" ? "opacity-60 cursor-wait" : ""}`}
            title="Restart Moonraker service"
          >
            <RotateCcw
              size={15}
              className={loadingAction === "server_restart" ? "animate-spin" : ""}
            />
            <span>Restart Moonraker</span>
          </button>
        )}
      </div>
    </div>
  );
}
