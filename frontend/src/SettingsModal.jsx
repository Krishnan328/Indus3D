
import React, { createElement, useState, useEffect, useMemo } from "react";
import { X, Info, Bell, BellOff, MessageCircle, Send, LogOut, Layout, Server, Camera, Monitor, Thermometer, ShieldCheck, ChevronRight, Activity, Trash2, Edit3, Plus, Sliders, TerminalSquare, RefreshCw, Snowflake, FileEdit, Film, Network, Check, Download, Upload, User, PlaySquare, Eye, EyeOff, ArrowUp, ArrowDown, Lightbulb, ScanEye, WifiOff, Wifi, Layers, Box, Crosshair, FileCode } from "lucide-react";
import { useStore, API } from "./store";
import { useThemeTokens, useIsBrutalist } from "./theme";
import { ThemeSwitcher } from "./ThemeSwitcher";

function TabButton({ id, icon, label, activeTab, setActiveTab, brutalist }) {
  const isActive = activeTab === id;
  return (
    <button
      onClick={() => setActiveTab(id)}
      className={`flex items-center gap-3 px-3 py-2 text-sm text-left transition-colors ${
        isActive
          ? (brutalist ? "bg-[#FFE9A8] border-2 border-[#111] font-bold" : "bg-emerald-500/20 text-emerald-500 font-bold border-2 border-transparent")
          : "opacity-70 hover:opacity-100 hover:bg-gray-500/10 border-2 border-transparent"
      } ${!brutalist && "rounded-lg"}`}
    >
      {createElement(icon, { size: 16 })}
      {label}
    </button>
  );
}

// ── Reusable toggle switch, used across Interface / Control / Console tabs ──
function Toggle({ label, description, checked, onChange, borderClass, brutalist }) {
  return (
    <div className={`p-4 flex items-center justify-between gap-4 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
      <div>
        <div className="font-bold text-sm">{label}</div>
        {description && <div className="text-xs opacity-50 mt-0.5">{description}</div>}
      </div>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`shrink-0 w-11 h-6 flex items-center px-0.5 transition-colors ${brutalist ? "border-2 border-[#111]" : "rounded-full"} ${checked ? "bg-emerald-500 justify-end" : "bg-gray-500/30 justify-start"}`}
      >
        <span className={`w-5 h-5 bg-white ${brutalist ? "" : "rounded-full"} shadow`} />
      </button>
    </div>
  );
}

export function SettingsModal({ onClose }) {
  const [activeTab, setActiveTab] = useState("general");
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const notif = useStore((s) => s.notificationStatus);
  const dashboardMode = useStore((s) => s.dashboardMode);
  const setDashboardMode = useStore((s) => s.setDashboardMode);
  const fetchNotificationStatus = useStore((s) => s.fetchNotificationStatus);
  const authStatus = useStore((s) => s.authStatus);
  const logout = useStore((s) => s.logout);
  const tele = useStore((s) => s.telemetry);
  const uiPrefs = useStore((s) => s.uiPrefs);
  const setUiPref = useStore((s) => s.setUiPref);

  useEffect(() => { fetchNotificationStatus(); }, [fetchNotificationStatus]);

  const borderClass = brutalist ? "border-[#111] border-2" : `border ${t.border}`;

  const tabLabels = {
    general: "General", ui: "Interface", machine: "Machine", bed: "Print Bed", control: "Control", console: "Console",
    editor: "Editor", timelapse: "Timelapse", webcams: "Webcams", presets: "Presets", macros: "Macros",
    leds: "LEDs", vision: "Vision Inspector", printers: "Printers", notifications: "Notifications", about: "About",
  };

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-4 sm:p-10 bg-black/70 backdrop-blur-md">
      <div className={`w-full max-w-4xl h-full max-h-[640px] flex overflow-hidden ${t.panel}`}>

        {/* Sidebar */}
        <div className={`w-48 sm:w-56 shrink-0 flex flex-col p-3 gap-1 overflow-y-auto ${brutalist ? "border-r-[3px] border-[#111]" : `border-r ${t.border} bg-gray-500/5`}`}>
          <div className="flex items-center gap-2 px-2 py-3 mb-2">
            <ShieldCheck size={20} className={brutalist ? "" : "text-emerald-500"} />
            <h2 className="font-bold text-lg tracking-wide uppercase">Settings</h2>
          </div>

          <TabButton id="general" icon={User} label="General" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="ui" icon={Layout} label="Interface" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="machine" icon={Server} label="Machine" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="bed" icon={Layers} label="Print Bed" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="printers" icon={Network} label="Printers" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="control" icon={Sliders} label="Control" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="console" icon={TerminalSquare} label="Console" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="editor" icon={FileEdit} label="Editor" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="timelapse" icon={Film} label="Timelapse" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="webcams" icon={Camera} label="Webcams" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="presets" icon={Thermometer} label="Presets" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="macros" icon={PlaySquare} label="Macros" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="leds" icon={Lightbulb} label="LEDs" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="vision" icon={ScanEye} label="Vision Inspector" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="notifications" icon={Bell} label="Notifications" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />
          <TabButton id="about" icon={Info} label="About" activeTab={activeTab} setActiveTab={setActiveTab} t={t} brutalist={brutalist} />


          <div className="mt-auto pt-4 flex flex-col gap-2">
            {authStatus?.auth_required && (
              <button
                onClick={async () => { await logout(); onClose(); }}
                className={`flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold transition-all ${borderClass} ${brutalist ? "bg-white hover:bg-red-100" : "bg-red-500/10 text-red-500 hover:bg-red-500/20 rounded"}`}
              >
                <LogOut size={14} /> Sign Out
              </button>
            )}
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className={`px-6 py-4 flex justify-between items-center shrink-0 ${brutalist ? "border-b-[3px] border-[#111]" : `border-b ${t.border}`}`}>
            <h2 className={t.heading}>{tabLabels[activeTab] || activeTab.toUpperCase()}</h2>
            <button onClick={onClose} className="p-2 bg-gray-500/10 hover:bg-gray-500/20 rounded-full transition-colors"><X size={18} /></button>
          </div>

          <div className="flex-1 overflow-y-auto p-6">

            {activeTab === "general" && (
              <GeneralTab borderClass={borderClass} brutalist={brutalist} t={t} />
            )}

            {activeTab === "ui" && (
              <div className="flex flex-col gap-6 max-w-lg">
                <div>
                  <h4 className={`mb-3 ${t.label}`}>Dashboard Theme</h4>
                  <ThemeSwitcher />
                  <p className="text-xs opacity-50 mt-3 leading-relaxed">
                    Classic supports OS light/dark modes. Workshop, Blueprint, and Creme are fixed-appearance design systems.
                  </p>
                </div>

                <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
                  <h4 className={`mb-3 ${t.label}`}>Dashboard Mode</h4>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setDashboardMode("dynamic")}
                      className={`flex-1 px-4 py-3 text-xs font-bold transition-all ${borderClass} ${dashboardMode === "dynamic" ? (brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded") : (brutalist ? "bg-white" : "bg-gray-500/10 rounded")}`}
                    >
                      Dynamic
                    </button>
                    <button
                      onClick={() => setDashboardMode("classic")}
                      className={`flex-1 px-4 py-3 text-xs font-bold transition-all ${borderClass} ${dashboardMode === "classic" ? (brutalist ? "bg-blue-300" : "bg-blue-500 text-white rounded") : (brutalist ? "bg-white" : "bg-gray-500/10 rounded")}`}
                    >
                      Static
                    </button>
                  </div>
                  <p className="text-xs opacity-50 mt-3 leading-relaxed">
                    Dynamic mode includes advanced features like predictive quality analytics, TrueTwin digital twin, and lifetime odometry. Static mode provides a lightweight, focused view of essential 3D printer telemetry without the advanced analytic overhead.
                  </p>
                </div>

                <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
                  <h4 className={`mb-3 ${t.label}`}>Layout Management</h4>
                  <button
                    onClick={() => { localStorage.removeItem("indus3d_layout_dynamic_v5"); localStorage.removeItem("indus3d_layout_static_v5"); window.location.reload(); }}
                    className={`px-4 py-2 text-xs font-bold transition-all ${borderClass} ${brutalist ? "bg-red-200" : "bg-red-500/20 text-red-500 rounded"}`}
                  >
                    Reset Grid Layout to Default
                  </button>
                  <p className="text-xs opacity-50 mt-2">Clears all custom dragging and resizing, restoring the original dashboard grid.</p>
                </div>

                <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
                  <h4 className={`mb-3 ${t.label}`}>Confirmations</h4>
                  <div className="flex flex-col gap-2">
                    <Toggle label="Confirm on Emergency Stop" description="Ask before triggering M112 / E-STOP."
                      checked={uiPrefs.confirmEstop} onChange={(v) => setUiPref("confirmEstop", v)} borderClass={borderClass} brutalist={brutalist} />
                    <Toggle label="Confirm on Cancel Print" description="Ask before cancelling an active job."
                      checked={uiPrefs.confirmCancelPrint} onChange={(v) => setUiPref("confirmCancelPrint", v)} borderClass={borderClass} brutalist={brutalist} />
                    <Toggle label="Confirm on Cooldown" description="Ask before zeroing hotend/bed targets from a preset."
                      checked={uiPrefs.confirmCooldown} onChange={(v) => setUiPref("confirmCooldown", v)} borderClass={borderClass} brutalist={brutalist} />
                    <Toggle label="Confirm on Power Toggle" description="Ask before switching a smart-plug device on/off."
                      checked={uiPrefs.confirmPowerToggle} onChange={(v) => setUiPref("confirmPowerToggle", v)} borderClass={borderClass} brutalist={brutalist} />
                  </div>
                </div>

                <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
                  <h4 className={`mb-3 ${t.label}`}>Miscellaneous</h4>
                  <div className="flex flex-col gap-2">
                    <Toggle label="Show Progress as Favicon" description="Replace the browser tab icon with a live progress ring while printing."
                      checked={uiPrefs.showProgressFavicon} onChange={(v) => setUiPref("showProgressFavicon", v)} borderClass={borderClass} brutalist={brutalist} />
                    <Toggle label="Hide Upload Button" description="Hide the Upload & Print control on the print status card."
                      checked={uiPrefs.hideUploadButton} onChange={(v) => setUiPref("hideUploadButton", v)} borderClass={borderClass} brutalist={brutalist} />
                  </div>
                </div>

                <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
                  <h4 className={`mb-3 ${t.label}`}>G-code Viewer</h4>
                  <div className="flex flex-col gap-2">
                    <Toggle label="Show Axes" description="Overlay an XYZ axes helper in the TrueTwin viewport."
                      checked={uiPrefs.gcodeShowAxes} onChange={(v) => setUiPref("gcodeShowAxes", v)} borderClass={borderClass} brutalist={brutalist} />
                    <Toggle label="Color by Height" description="Gradient the toolpath by Z height (blue = low, red = high) instead of a flat color."
                      checked={uiPrefs.gcodeColorByHeight} onChange={(v) => setUiPref("gcodeColorByHeight", v)} borderClass={borderClass} brutalist={brutalist} />
                    <Toggle label="Show Travel Moves" description="Overlay non-extruding travel moves as thin amber lines."
                      checked={uiPrefs.gcodeShowTravel} onChange={(v) => setUiPref("gcodeShowTravel", v)} borderClass={borderClass} brutalist={brutalist} />
                  </div>
                  <p className="text-xs opacity-50 mt-3 leading-relaxed">
                    Extrusion-width rendering isn't available — WebGL doesn't reliably support variable line thickness, and building it properly would mean rewriting the toolpath renderer's core (performance-tuned) geometry pipeline. Left out rather than shipped as a setting that silently doesn't work on most browsers.
                  </p>
                </div>
              </div>
            )}

            {activeTab === "machine" && (
              <div className="flex flex-col gap-6">
                <div>
                  <h4 className={`mb-3 ${t.label}`}>System Information</h4>
                  <div className={`p-4 grid grid-cols-2 gap-4 text-sm ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
                    <div>
                      <span className="opacity-50 block text-xs mb-1">Klipper State</span>
                      <span className="font-bold flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${tele?.online ? "bg-green-500" : "bg-red-500"}`}></div>
                        {tele?.online ? "Connected" : "Disconnected"}
                      </span>
                    </div>
                    <div>
                      <span className="opacity-50 block text-xs mb-1">Moonraker IP</span>
                      <span className="font-mono">{API || "localhost"}</span>
                    </div>
                    <div>
                      <span className="opacity-50 block text-xs mb-1">Indus3D API</span>
                      <span className="font-mono">v1.0.0 (Port 5001)</span>
                    </div>
                  </div>
                </div>

                <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
                  <h4 className={`mb-3 ${t.label}`}>Power Devices</h4>
                  <p className="text-xs opacity-50 mb-4">Power devices are auto-discovered from Moonraker. Manage on/off and confirmation behavior from the Power panel on the dashboard.</p>
                </div>
              </div>
            )}

            {activeTab === "bed" && (
              <BedTab borderClass={borderClass} brutalist={brutalist} t={t} />
            )}

            {activeTab === "control" && (
              <ControlTab uiPrefs={uiPrefs} setUiPref={setUiPref} borderClass={borderClass} brutalist={brutalist} t={t} />
            )}

            {activeTab === "console" && (
              <div className="flex flex-col gap-6 max-w-lg">
                <div>
                  <h4 className={`mb-3 ${t.label}`}>Entry Direction</h4>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setUiPref("consoleDirection", "top")}
                      className={`flex-1 px-4 py-3 text-xs font-bold transition-all ${borderClass} ${uiPrefs.consoleDirection === "top" ? (brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded") : (brutalist ? "bg-white" : "bg-gray-500/10 rounded")}`}
                    >
                      Newest on Top
                    </button>
                    <button
                      onClick={() => setUiPref("consoleDirection", "bottom")}
                      className={`flex-1 px-4 py-3 text-xs font-bold transition-all ${borderClass} ${uiPrefs.consoleDirection === "bottom" ? (brutalist ? "bg-blue-300" : "bg-blue-500 text-white rounded") : (brutalist ? "bg-white" : "bg-gray-500/10 rounded")}`}
                    >
                      Newest on Bottom
                    </button>
                  </div>
                  <p className="text-xs opacity-50 mt-3 leading-relaxed">
                    "Newest on Bottom" also moves the command input above the log, shell-style.
                  </p>
                </div>
                <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
                  <h4 className={`mb-3 ${t.label}`}>Display</h4>
                  <div className="flex flex-col gap-2">
                    <Toggle label="Compact Entries" description="Tighter line spacing and panel padding."
                      checked={uiPrefs.consoleCompact} onChange={(v) => setUiPref("consoleCompact", v)} borderClass={borderClass} brutalist={brutalist} />
                    <Toggle label="Hide Temperature Reports" description="Filter out M105-style T:/B: status lines from the log."
                      checked={uiPrefs.hideTempsInConsole} onChange={(v) => setUiPref("hideTempsInConsole", v)} borderClass={borderClass} brutalist={brutalist} />
                  </div>
                </div>
              </div>
            )}

            {activeTab === "editor" && (
              <div className="flex flex-col gap-6 max-w-lg">
                <div className="flex flex-col gap-2">
                  <Toggle label="Close on Esc" description="Press Escape to close the Configuration Editor."
                    checked={uiPrefs.editorCloseOnEsc} onChange={(v) => setUiPref("editorCloseOnEsc", v)} borderClass={borderClass} brutalist={brutalist} />
                  <Toggle label="Confirm Unsaved Changes" description="Ask before discarding edits when switching files or closing the editor."
                    checked={uiPrefs.editorConfirmUnsaved} onChange={(v) => setUiPref("editorConfirmUnsaved", v)} borderClass={borderClass} brutalist={brutalist} />
                </div>
                <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
                  <h4 className={`mb-3 ${t.label}`}>Tab Size</h4>
                  <div className="flex gap-2">
                    {[2, 4, 8].map((size) => (
                      <button key={size} onClick={() => setUiPref("editorTabSize", size)}
                        className={`flex-1 px-4 py-3 text-xs font-bold transition-all ${borderClass} ${uiPrefs.editorTabSize === size ? (brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded") : (brutalist ? "bg-white" : "bg-gray-500/10 rounded")}`}
                      >
                        {size} spaces
                      </button>
                    ))}
                  </div>
                  <p className="text-xs opacity-50 mt-3 leading-relaxed">
                    Number of spaces inserted when pressing Tab inside the Configuration Editor.
                  </p>
                </div>
              </div>
            )}

            {activeTab === "printers" && (
              <PrintersTab borderClass={borderClass} brutalist={brutalist} t={t} />
            )}

            {activeTab === "timelapse" && (
              <TimelapseTab borderClass={borderClass} brutalist={brutalist} t={t} />
            )}

            {activeTab === "webcams" && (
              <WebcamsTab borderClass={borderClass} brutalist={brutalist} t={t} />
            )}

            {activeTab === "presets" && (
              <PresetsTab borderClass={borderClass} brutalist={brutalist} t={t} uiPrefs={uiPrefs} />
            )}

            {activeTab === "macros" && (
              <MacrosTab borderClass={borderClass} brutalist={brutalist} t={t} />
            )}

            {activeTab === "leds" && (
              <LedsTab borderClass={borderClass} brutalist={brutalist} t={t} />
            )}

            {activeTab === "vision" && (
              <VisionTab borderClass={borderClass} brutalist={brutalist} t={t} />
            )}

            {activeTab === "notifications" && (
              <div className="flex flex-col gap-6 max-w-lg">
                <div>
                  <h4 className={`mb-3 ${t.label}`}>Web Push (Browser)</h4>
                  <div className={`p-4 flex items-center justify-between ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
                    <div>
                      <div className="font-bold">Desktop Notifications</div>
                      <div className="text-xs opacity-50">Show popups when prints finish or fail.</div>
                    </div>
                    <button
                      onClick={() => window.Notification && Notification.requestPermission()}
                      className={`px-4 py-2 text-xs font-bold ${borderClass} ${brutalist ? "bg-white" : "bg-gray-500/20 rounded"}`}
                    >
                      Request Permission
                    </button>
                  </div>
                </div>

                <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
                  <h4 className={`mb-3 ${t.label}`}>Webhooks</h4>
                  <div className="flex flex-col gap-3">
                    <div className={`p-4 flex items-center justify-between ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
                      <div className="flex items-center gap-3">
                        <MessageCircle size={24} className={notif.channels?.discord ? "text-indigo-500" : "opacity-30"} />
                        <div>
                          <div className="font-bold">Discord</div>
                          <div className="text-xs opacity-50">{notif.channels?.discord ? "Connected" : "Not configured in .env"}</div>
                        </div>
                      </div>
                    </div>

                    <div className={`p-4 flex items-center justify-between ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
                      <div className="flex items-center gap-3">
                        <Send size={24} className={notif.channels?.telegram ? "text-blue-500" : "opacity-30"} />
                        <div>
                          <div className="font-bold">Telegram</div>
                          <div className="text-xs opacity-50">{notif.channels?.telegram ? "Connected" : "Not configured in .env"}</div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="text-[11px] opacity-50 leading-relaxed mt-4">
                    Webhooks are configured via <code>.env</code> on the server to protect credentials.
                    Set <code>DISCORD_WEBHOOK_URL</code> or <code>TELEGRAM_BOT_TOKEN</code>.
                  </div>
                </div>
              </div>
            )}

            {activeTab === "about" && (
              <div className="flex flex-col gap-6 max-w-2xl">
                <div>
                  <h4 className={`mb-3 ${t.label}`}>About Indus3D</h4>
                  <p className="text-sm opacity-80 leading-relaxed mb-4">
                    Indus3D is a next-generation 3D printer interface built on top of Klipper/Moonraker. It provides a heavily stylized, highly customizable workspace.
                  </p>
                  <p className="text-sm opacity-80 leading-relaxed mb-4">
                    To make adequate use of Indus3D, utilize the <strong>Dynamic Mode</strong> to leverage advanced analytics like the <em>TrueTwin</em> digital twin and the predictive <em>Quality Panel</em>. You can drag, drop, and resize any widget in the Live Dashboard or the Digital Twin tab by clicking "Unlock Dashboard".
                  </p>
                  <p className="text-sm opacity-80 leading-relaxed">
                    Themes can be instantly swapped here in settings. Each theme not only completely redesigns the dashboard but applies custom color palettes to the deeper modals like the Config Editor and Surface Topography.
                  </p>
                </div>
              </div>
            )}

          </div>
        </div>
      </div>
    </div>
  );
}

// ── Macros tab: hide/show + reorder which macros appear on the dashboard's
//    Macros card. Purely a display preference — doesn't touch the macros
//    themselves in printer.cfg. ──────────────────────────────────────────
// ── LEDs tab: per-printer state->color mapping (idle/heating/printing/
//    paused/complete/error/homing/probing), applied automatically by the
//    backend's telemetry loop — see workers/telemetry_worker.py. Also a
//    manual "test a color right now" control that bypasses the profile.
// ── Vision Inspector tab: status of the companion device (see backend/edge/
//    and api/routes/edge.py) plus enable/threshold/cooldown for what happens
//    when it reports a detection. The actual detector runs on a SEPARATE
//    device — nothing here starts or stops that process, it only shows
//    whether it's currently checking in and configures how Indus3D reacts.
function VisionTab({ borderClass, brutalist, t }) {
  const edgeStatus = useStore((s) => s.edgeStatus);
  const fetchEdgeStatus = useStore((s) => s.fetchEdgeStatus);
  const saveEdgeConfig = useStore((s) => s.saveEdgeConfig);

  const [draft, setDraft] = useState(edgeStatus.config);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    fetchEdgeStatus();
    const id = setInterval(fetchEdgeStatus, 5000); // poll while the tab's open, connection state is live info
    return () => clearInterval(id);
  }, [fetchEdgeStatus]);

  useEffect(() => { setDraft(edgeStatus.config); }, [edgeStatus.config]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(edgeStatus.config);

  const save = async () => {
    setSaving(true);
    setMsg("");
    const result = await saveEdgeConfig(draft);
    setMsg(result.error ? `Failed: ${result.error}` : "Saved");
    setSaving(false);
    setTimeout(() => setMsg(""), 4000);
  };

  const lastDetection = edgeStatus.last_detection;
  const ago = (ts) => {
    if (!ts) return "";
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    return `${Math.round(s / 3600)}h ago`;
  };

  return (
    <div className="flex flex-col gap-6 max-w-lg">
      <div className={`p-4 flex items-center gap-3 ${borderClass} ${!brutalist && "rounded-lg"} ${edgeStatus.connected ? "bg-emerald-500/10" : "bg-gray-500/10"}`}>
        {edgeStatus.connected ? <Wifi size={20} className="text-emerald-500 shrink-0" /> : <WifiOff size={20} className="opacity-40 shrink-0" />}
        <div className="min-w-0">
          <div className="font-bold text-sm">{edgeStatus.connected ? "Companion Device Connected" : "No Companion Device Detected"}</div>
          <div className="text-xs opacity-50">
            {edgeStatus.connected
              ? `${edgeStatus.last_heartbeat_info?.device_id || "Unknown device"} · ${edgeStatus.last_heartbeat_info?.detector || "?"} detector`
              : "Run edge/watchdog.py or edge/inspector.py on a separate device — see backend/edge/config.py."}
          </div>
        </div>
      </div>

      {lastDetection && (
        <div className={`p-4 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
          <div className="text-xs opacity-50 mb-1">Last Detection</div>
          <div className="font-bold text-sm">{lastDetection.label} — {lastDetection.confidence.toFixed(0)}% confidence</div>
          <div className="text-xs opacity-50">{lastDetection.detector} detector · {ago(lastDetection.ts)}</div>
        </div>
      )}

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <Toggle label="Enable Automatic Pause" description="Pause the print when a detection clears the confidence threshold below. Always logged either way."
          checked={!!draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} borderClass={borderClass} brutalist={brutalist} />
      </div>

      <div className={draft.enabled ? "" : "opacity-40 pointer-events-none"}>
        <h4 className={`mb-3 ${t.label}`}>Confidence Threshold</h4>
        <div className="flex items-center gap-3">
          <input type="range" min="0" max="100" value={draft.threshold_pct}
            onChange={(e) => setDraft({ ...draft, threshold_pct: Number(e.target.value) })}
            className="flex-1" />
          <span className="text-xs font-mono w-10 text-right">{draft.threshold_pct}%</span>
        </div>
        <p className="text-xs opacity-50 mt-2">Detections below this are recorded but don't pause anything.</p>
      </div>

      <div className={draft.enabled ? "" : "opacity-40 pointer-events-none"}>
        <h4 className={`mb-3 ${t.label}`}>Cooldown</h4>
        <div className="flex items-center gap-2">
          <input type="number" min="0" value={draft.cooldown_s}
            onChange={(e) => setDraft({ ...draft, cooldown_s: Math.max(0, Number(e.target.value) || 0) })}
            className={`w-24 px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`} />
          <span className="text-xs opacity-60">seconds before another detection can trigger a pause</span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button onClick={save} disabled={!dirty || saving}
          className={`px-4 py-2 text-xs font-bold transition-all ${borderClass} ${brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded"} disabled:opacity-40`}>
          {saving ? "Saving…" : "Save"}
        </button>
        {msg && <span className={`text-xs font-bold ${msg.startsWith("Failed") ? "text-red-500" : "text-emerald-500"}`}>{msg}</span>}
      </div>

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <h4 className={`mb-3 ${t.label}`}>Setup</h4>
        <p className="text-xs opacity-50 leading-relaxed">
          This runs on a separate device (not the printer's own Pi) — a second Pi, a laptop, anything with spare CPU. On that device:
        </p>
        <pre className={`mt-2 p-3 text-[11px] font-mono overflow-x-auto ${borderClass} ${!brutalist && "rounded-lg bg-black/5"}`}>
{`pip install -r requirements.txt -r requirements-vision.txt
export INDUS3D_PRINTER_HOST=<printer's IP>
export INDUS3D_BACKEND_URL=http://<this Indus3D host>:5001
python edge/watchdog.py     # works immediately, no training data needed
# or, once you've trained a model (see edge/harvester.py):
python edge/inspector.py`}
        </pre>
      </div>
    </div>
  );
}

const LED_STATE_META = [
  ["idle",     "Idle",              "Printer connected, no job running"],
  ["heating",  "Heating",           "Printing has started but a heater hasn't reached target yet"],
  ["printing", "Printing",          "Actively printing, heaters at target (flat color — see Progress Gradient below to override)"],
  ["paused",   "Paused",            "Print paused"],
  ["complete", "Complete",          "Print finished successfully"],
  ["error",    "Error",             "Print failed or printer faulted"],
  ["homing",   "Homing",            "Applied for the duration of a G28 triggered from Indus3D"],
  ["probing",  "Probing / Leveling","Applied for the duration of a bed mesh calibration"],
  ["alert",    "Alert Flash",       "Pulses briefly when a corrective action (e.g. thermal runaway) fires, then settles back to Error or Printing"],
];

function LedsTab({ borderClass, brutalist, t }) {
  const leds = useStore((s) => s.leds);
  const fetchLeds = useStore((s) => s.fetchLeds);
  const ledProfile = useStore((s) => s.ledProfile);
  const fetchLedProfile = useStore((s) => s.fetchLedProfile);
  const saveLedProfile = useStore((s) => s.saveLedProfile);
  const setLedColorLive = useStore((s) => s.setLedColorLive);
  const applyLedProfileState = useStore((s) => s.applyLedProfileState);
  const turnLedsOff = useStore((s) => s.turnLedsOff);

  const [draft, setDraft] = useState(ledProfile);
  const [loadingLeds, setLoadingLeds] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [testColor, setTestColor] = useState("#ffffff");
  const [testLed, setTestLed] = useState("");
  const [testMsg, setTestMsg] = useState("");
  const [quickMsg, setQuickMsg] = useState("");

  useEffect(() => {
    (async () => {
      await Promise.all([fetchLeds(), fetchLedProfile()]);
      setLoadingLeds(false);
    })();
  }, [fetchLeds, fetchLedProfile]);

  useEffect(() => { setDraft(ledProfile); }, [ledProfile]);
  useEffect(() => { if (leds.length && !testLed) setTestLed(leds[0].name); }, [leds, testLed]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(ledProfile);

  const setColor = (state, hex) => setDraft({ ...draft, colors: { ...draft.colors, [state]: hex } });

  const toggleLed = (name) => {
    const current = draft.led_names || [];
    const next = current.includes(name) ? current.filter((n) => n !== name) : [...current, name];
    setDraft({ ...draft, led_names: next });
  };

  const save = async () => {
    setSaving(true);
    setMsg("");
    const result = await saveLedProfile(draft);
    setMsg(result.error ? `Failed: ${result.error}` : "Saved");
    setSaving(false);
    setTimeout(() => setMsg(""), 4000);
  };

  const runTest = async () => {
    setTestMsg("");
    const result = await setLedColorLive(testLed, testColor);
    setTestMsg(result.error ? `Failed: ${result.error}` : "Sent");
    setTimeout(() => setTestMsg(""), 3000);
  };

  const quickApply = async (state) => {
    setQuickMsg("");
    const result = state === "off" ? await turnLedsOff() : await applyLedProfileState(state);
    setQuickMsg(result.error ? `Failed: ${result.error}` : "Applied");
    setTimeout(() => setQuickMsg(""), 3000);
  };

  if (loadingLeds) {
    return <div className="text-xs opacity-40 italic">Looking for configured LEDs…</div>;
  }

  if (!leds.length) {
    return (
      <div className={`p-4 text-sm opacity-70 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
        No LED hardware found in your Klipper config. Indus3D looks for <code>[neopixel]</code>, <code>[led]</code>, <code>[dotstar]</code>, <code>[pca9533]</code>, or <code>[pca9632]</code> sections — add one in printer.cfg and reopen this tab.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 max-w-lg">
      <Toggle label="Enable Automatic Status Colors" description="Have the printer's LEDs change color automatically based on print state."
        checked={!!draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} borderClass={borderClass} brutalist={brutalist} />

      <div className={draft.enabled ? "" : "opacity-40 pointer-events-none"}>
        <h4 className={`mb-3 ${t.label}`}>LEDs to Control</h4>
        <p className="text-xs opacity-50 mb-2">All selected LEDs receive the same status color at the same time.</p>
        <div className="flex flex-col gap-2">
          {leds.map((l) => {
            const checked = (draft.led_names || []).includes(l.name);
            return (
              <label key={l.name} className={`px-3 py-2 flex items-center gap-3 cursor-pointer ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
                <input type="checkbox" checked={checked} onChange={() => toggleLed(l.name)} className="w-4 h-4" />
                <span className="text-sm font-mono">{l.name}</span>
                <span className="text-[10px] opacity-40 ml-auto uppercase">{l.type}</span>
              </label>
            );
          })}
        </div>
      </div>

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`} ${draft.enabled ? "" : "opacity-40 pointer-events-none"}`}>
        <h4 className={`mb-3 ${t.label}`}>Brightness</h4>
        <div className="flex items-center gap-3">
          <input type="range" min="0" max="100" value={draft.brightness ?? 100}
            onChange={(e) => setDraft({ ...draft, brightness: Number(e.target.value) })}
            className="flex-1" />
          <span className="text-xs font-mono w-10 text-right">{draft.brightness ?? 100}%</span>
        </div>
        <p className="text-xs opacity-50 mt-2">Scales every status color below — dim the whole setup without re-picking each color.</p>
      </div>

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`} ${draft.enabled ? "" : "opacity-40 pointer-events-none"}`}>
        <Toggle label="Progress Gradient While Printing" description="Instead of a flat Printing color, shift hue smoothly from blue (0%) to red (100%) as the print progresses."
          checked={!!draft.printing_gradient} onChange={(v) => setDraft({ ...draft, printing_gradient: v })} borderClass={borderClass} brutalist={brutalist} />
      </div>

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`} ${draft.enabled ? "" : "opacity-40 pointer-events-none"}`}>
        <h4 className={`mb-3 ${t.label}`}>Status Colors</h4>
        <div className="flex flex-col gap-2">
          {LED_STATE_META.map(([key, label, desc]) => (
            <div key={key} className={`p-3 flex items-center justify-between gap-3 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"} ${key === "printing" && draft.printing_gradient ? "opacity-40" : ""}`}>
              <div className="min-w-0">
                <div className="font-bold text-sm">{label}</div>
                <div className="text-[11px] opacity-50">{desc}</div>
              </div>
              <input type="color" value={draft.colors?.[key] || "#000000"}
                onChange={(e) => setColor(key, e.target.value)}
                disabled={key === "printing" && draft.printing_gradient}
                className="w-10 h-10 shrink-0 rounded cursor-pointer border-0 bg-transparent disabled:opacity-40" />
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button onClick={save} disabled={!dirty || saving}
          className={`px-4 py-2 text-xs font-bold transition-all ${borderClass} ${brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded"} disabled:opacity-40`}>
          {saving ? "Saving…" : "Save LED Settings"}
        </button>
        {msg && <span className={`text-xs font-bold ${msg.startsWith("Failed") ? "text-red-500" : "text-emerald-500"}`}>{msg}</span>}
      </div>

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <h4 className={`mb-3 ${t.label}`}>Quick Control</h4>
        <p className="text-xs opacity-50 mb-3">Apply a saved status color (or turn everything off) right now — uses the LEDs and brightness from the saved profile above, not the draft.</p>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={() => quickApply("idle")} className={`px-3 py-1.5 text-xs font-bold ${borderClass} ${brutalist ? "bg-white" : "bg-gray-500/10 rounded"}`}>Idle</button>
          <button onClick={() => quickApply("printing")} className={`px-3 py-1.5 text-xs font-bold ${borderClass} ${brutalist ? "bg-white" : "bg-gray-500/10 rounded"}`}>Printing</button>
          <button onClick={() => quickApply("complete")} className={`px-3 py-1.5 text-xs font-bold ${borderClass} ${brutalist ? "bg-white" : "bg-gray-500/10 rounded"}`}>Complete</button>
          <button onClick={() => quickApply("off")} className={`px-3 py-1.5 text-xs font-bold ${borderClass} ${brutalist ? "bg-white" : "bg-gray-500/10 rounded"}`}>Off</button>
          {quickMsg && <span className={`text-xs font-bold ${quickMsg.startsWith("Failed") ? "text-red-500" : "text-emerald-500"}`}>{quickMsg}</span>}
        </div>
      </div>

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <h4 className={`mb-3 ${t.label}`}>Test a Color</h4>
        <p className="text-xs opacity-50 mb-3">Sends a one-off color directly to one LED, ignoring brightness — doesn't touch the saved profile. Automatic status colors will overwrite it on the next state change.</p>
        <div className="flex items-center gap-2">
          <select value={testLed} onChange={(e) => setTestLed(e.target.value)}
            className={`flex-1 px-3 py-2 text-sm outline-none ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
            {leds.map((l) => <option key={l.name} value={l.name}>{l.name}</option>)}
          </select>
          <input type="color" value={testColor} onChange={(e) => setTestColor(e.target.value)}
            className="w-10 h-10 shrink-0 rounded cursor-pointer border-0 bg-transparent" />
          <button onClick={runTest} className={`px-4 py-2 text-xs font-bold ${borderClass} ${brutalist ? "bg-white" : "bg-gray-500/10 rounded"}`}>
            Set Now
          </button>
          {testMsg && <span className={`text-xs font-bold ${testMsg.startsWith("Failed") ? "text-red-500" : "text-emerald-500"}`}>{testMsg}</span>}
        </div>
      </div>
    </div>
  );
}

function MacrosTab({ borderClass, brutalist }) {
  const rawMacros = useStore((s) => s.macros);
  const fetchSensorData = useStore((s) => s.fetchSensorData);
  const hiddenMacros = useStore((s) => s.uiPrefs.hiddenMacros);
  const macroOrder = useStore((s) => s.uiPrefs.macroOrder);
  const setUiPref = useStore((s) => s.setUiPref);

  useEffect(() => { if (!rawMacros || !rawMacros.length) fetchSensorData(); }, [rawMacros, fetchSensorData]);

  const allMacros = useMemo(
    () => (rawMacros || []).filter((m) => typeof m === "string" && !m.startsWith("_")),
    [rawMacros]
  );

  // Same merge logic as the dashboard card: explicitly ordered macros
  // first, then anything not yet in macroOrder (new macros, or before the
  // first reorder) appended in their natural order.
  const orderedMacros = useMemo(() => {
    if (!macroOrder || !macroOrder.length) return allMacros;
    const orderIndex = new Map(macroOrder.map((m, i) => [m, i]));
    const known = allMacros.filter((m) => orderIndex.has(m)).sort((a, b) => orderIndex.get(a) - orderIndex.get(b));
    const rest = allMacros.filter((m) => !orderIndex.has(m));
    return [...known, ...rest];
  }, [allMacros, macroOrder]);

  const toggleHidden = (name) => {
    const set = new Set(hiddenMacros || []);
    if (set.has(name)) set.delete(name); else set.add(name);
    setUiPref("hiddenMacros", Array.from(set));
  };

  const move = (name, dir) => {
    const idx = orderedMacros.indexOf(name);
    const swapWith = idx + dir;
    if (idx < 0 || swapWith < 0 || swapWith >= orderedMacros.length) return;
    const next = orderedMacros.slice();
    [next[idx], next[swapWith]] = [next[swapWith], next[idx]];
    setUiPref("macroOrder", next); // locks in the full order from here on
  };

  const resetOrder = () => setUiPref("macroOrder", []);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm opacity-70">
        Choose which macros show up on the dashboard's Macros card, and the order they appear in. Doesn't change the macros themselves.
      </p>

      {!allMacros.length ? (
        <div className={`p-4 text-xs opacity-50 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
          No macros found in Klipper yet.
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {orderedMacros.map((name, i) => {
            const hidden = (hiddenMacros || []).includes(name);
            return (
              <div key={name} className={`px-3 py-2 flex items-center justify-between gap-3 ${borderClass} ${!brutalist && "rounded-lg"} ${hidden ? "opacity-40" : ""} bg-gray-500/5`}>
                <span className="font-mono text-xs truncate">{name}</span>
                <div className="flex items-center gap-1 shrink-0">
                  <button onClick={() => move(name, -1)} disabled={i === 0}
                    className="p-1.5 opacity-50 hover:opacity-100 disabled:opacity-20"><ArrowUp size={14} /></button>
                  <button onClick={() => move(name, 1)} disabled={i === orderedMacros.length - 1}
                    className="p-1.5 opacity-50 hover:opacity-100 disabled:opacity-20"><ArrowDown size={14} /></button>
                  <button onClick={() => toggleHidden(name)} className="p-1.5 opacity-50 hover:opacity-100">
                    {hidden ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {macroOrder && macroOrder.length > 0 && (
        <button onClick={resetOrder} className={`self-start flex items-center gap-2 px-3 py-1.5 text-xs font-bold ${borderClass} ${brutalist ? "bg-white" : "bg-gray-500/10 rounded"}`}>
          <RefreshCw size={13} /> Reset to Default Order
        </button>
      )}
    </div>
  );
}

// ── General tab: display name override, date/time format, settings
//    backup/restore. All client-side — doesn't touch printer.cfg or the
//    server-side printer registry (Settings > Printers owns that). ────────
function GeneralTab({ borderClass, brutalist, t }) {
  const uiPrefs = useStore((s) => s.uiPrefs);
  const setUiPref = useStore((s) => s.setUiPref);
  const exportSettingsBackup = useStore((s) => s.exportSettingsBackup);
  const importSettingsBackup = useStore((s) => s.importSettingsBackup);

  const [nameDraft, setNameDraft] = useState(uiPrefs.printerDisplayName);
  const [importMsg, setImportMsg] = useState("");
  const fileInputRef = React.useRef(null);

  const commitName = () => setUiPref("printerDisplayName", nameDraft.trim());

  const handleBackup = () => {
    const data = exportSettingsBackup();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const stamp = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `indus3d-settings-${stamp}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleRestoreFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file) return;
    setImportMsg("");
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const result = importSettingsBackup(parsed);
      setImportMsg(result.error ? `Failed: ${result.error}` : "Settings restored");
    } catch {
      setImportMsg("Failed: not a valid JSON file");
    }
    setTimeout(() => setImportMsg(""), 4000);
  };

  return (
    <div className="flex flex-col gap-6 max-w-lg">
      <div>
        <h4 className={`mb-3 ${t.label}`}>Printer Display Name</h4>
        <input type="text" value={nameDraft}
          onChange={(e) => setNameDraft(e.target.value)}
          onBlur={commitName}
          onKeyDown={(e) => e.key === "Enter" && commitName()}
          placeholder="Leave blank to use the name from printer.cfg"
          className={`w-full px-3 py-2 text-sm outline-none ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`} />
        <p className="text-xs opacity-50 mt-2">Shown in the top bar instead of Klipper's own printer name — display only, doesn't change printer.cfg.</p>
      </div>

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <h4 className={`mb-3 ${t.label}`}>Date Format</h4>
        <div className="flex gap-2">
          {[["browser", "Browser Default"], ["iso", "YYYY-MM-DD"], ["dmy", "DD/MM/YYYY"], ["mdy", "MM/DD/YYYY"]].map(([id, label]) => (
            <button key={id} onClick={() => setUiPref("dateFormat", id)}
              className={`flex-1 px-2 py-3 text-[11px] font-bold transition-all ${borderClass} ${uiPrefs.dateFormat === id ? (brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded") : (brutalist ? "bg-white" : "bg-gray-500/10 rounded")}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <h4 className={`mb-3 ${t.label}`}>Time Format</h4>
        <div className="flex gap-2">
          {[["browser", "Browser Default"], ["24h", "24-hour"], ["12h", "12-hour"]].map(([id, label]) => (
            <button key={id} onClick={() => setUiPref("timeFormat", id)}
              className={`flex-1 px-3 py-3 text-xs font-bold transition-all ${borderClass} ${uiPrefs.timeFormat === id ? (brutalist ? "bg-blue-300" : "bg-blue-500 text-white rounded") : (brutalist ? "bg-white" : "bg-gray-500/10 rounded")}`}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="text-xs opacity-50 mt-2">Applies to timestamps in the Action Log and File Manager.</p>
      </div>

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <h4 className={`mb-3 ${t.label}`}>Backup & Restore</h4>
        <p className="text-xs opacity-50 mb-3">
          Save your theme, dashboard mode, presets, and preferences to a file — or restore them on a new device or after a factory reset. Doesn't include printer.cfg or the registered printer list.
        </p>
        <div className="flex gap-2 items-center">
          <button onClick={handleBackup}
            className={`flex items-center gap-2 px-4 py-2 text-xs font-bold transition-all ${borderClass} ${brutalist ? "bg-white hover:bg-gray-100" : "bg-gray-500/10 hover:bg-gray-500/20 rounded"}`}>
            <Download size={14} /> Backup
          </button>
          <button onClick={() => fileInputRef.current?.click()}
            className={`flex items-center gap-2 px-4 py-2 text-xs font-bold transition-all ${borderClass} ${brutalist ? "bg-white hover:bg-gray-100" : "bg-gray-500/10 hover:bg-gray-500/20 rounded"}`}>
            <Upload size={14} /> Restore
          </button>
          <input ref={fileInputRef} type="file" accept="application/json" className="hidden" onChange={handleRestoreFile} />
          {importMsg && <span className={`text-xs font-bold ${importMsg.startsWith("Failed") ? "text-red-500" : "text-emerald-500"}`}>{importMsg}</span>}
        </div>
      </div>
    </div>
  );
}

// ── Bed tab: OrcaSlicer profile import, STL model upload, screws keepout zones ──
function BedTab({ borderClass, brutalist, t }) {
  const bed = useStore((s) => s.bed);
  const importOrcaBed = useStore((s) => s.importOrcaBed);
  const uploadBedStl = useStore((s) => s.uploadBedStl);
  const deleteBedStl = useStore((s) => s.deleteBedStl);
  const addCornerScrewsPreset = useStore((s) => s.addCornerScrewsPreset);
  const clearBedExclusions = useStore((s) => s.clearBedExclusions);

  const [uploading, setUploading] = useState(false);
  const [feedback, setFeedback] = useState("");

  const handleOrcaUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setFeedback("");
    const res = await importOrcaBed(file);
    setUploading(false);
    if (res.status === "ok") {
      setFeedback(`✅ ${res.message}`);
    } else {
      setFeedback(`❌ ${res.error || "Failed to import OrcaSlicer profile"}`);
    }
  };

  const handleStlUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setFeedback("");
    const res = await uploadBedStl(file);
    setUploading(false);
    if (res.status === "ok") {
      setFeedback(`✅ ${res.message}`);
    } else {
      setFeedback(`❌ ${res.error || "Failed to upload STL model"}`);
    }
  };

  return (
    <div className="flex flex-col gap-6 max-w-xl">
      {feedback && (
        <div className={`p-3 rounded text-xs font-mono font-bold ${feedback.startsWith("✅") ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30" : "bg-red-500/20 text-red-400 border border-red-500/30"}`}>
          {feedback}
        </div>
      )}

      {/* Bed Dimensions Overview */}
      <div>
        <h4 className={`mb-3 ${t.label}`}>Active Bed Geometry</h4>
        <div className={`p-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center text-sm ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
          <div>
            <span className="opacity-50 block text-xs mb-1">X Width</span>
            <span className="font-mono font-bold text-emerald-400">{bed?.size_x_mm ?? 300} mm</span>
          </div>
          <div>
            <span className="opacity-50 block text-xs mb-1">Y Depth</span>
            <span className="font-mono font-bold text-emerald-400">{bed?.size_y_mm ?? 300} mm</span>
          </div>
          <div>
            <span className="opacity-50 block text-xs mb-1">Z Height</span>
            <span className="font-mono font-bold text-emerald-400">{bed?.size_z_mm ?? 400} mm</span>
          </div>
          <div>
            <span className="opacity-50 block text-xs mb-1">Origin</span>
            <span className="font-mono font-bold text-blue-400">{bed?.origin_center ? "Center (0,0)" : "Corner (0,0)"}</span>
          </div>
        </div>
      </div>

      {/* Slicer Profile & STL Importer */}
      <div>
        <h4 className={`mb-3 ${t.label}`}>Import & Bed 3D Model</h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className={`p-4 flex flex-col justify-between gap-3 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
            <div>
              <div className="flex items-center gap-2 font-bold text-sm mb-1">
                <FileCode size={16} className="text-blue-400" />
                <span>OrcaSlicer Profile</span>
              </div>
              <p className="text-xs opacity-50">Upload OrcaSlicer machine JSON to configure bed dimensions and screw zones.</p>
            </div>
            <label className="flex items-center justify-center gap-2 px-3 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs cursor-pointer transition-colors">
              <Upload size={14} />
              <span>{uploading ? "Importing…" : "Upload Orca JSON"}</span>
              <input type="file" accept=".json" onChange={handleOrcaUpload} disabled={uploading} className="hidden" />
            </label>
          </div>

          <div className={`p-4 flex flex-col justify-between gap-3 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
            <div>
              <div className="flex items-center gap-2 font-bold text-sm mb-1">
                <Box size={16} className="text-purple-400" />
                <span>Bed 3D Model (STL)</span>
              </div>
              <p className="text-xs opacity-50">Upload custom bed plate mesh to render in the Three.js viewport.</p>
            </div>
            <div className="flex items-center gap-2">
              <label className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs cursor-pointer transition-colors">
                <Upload size={14} />
                <span>{uploading ? "Uploading…" : "Upload STL"}</span>
                <input type="file" accept=".stl" onChange={handleStlUpload} disabled={uploading} className="hidden" />
              </label>
              {bed?.has_custom_model && (
                <button onClick={deleteBedStl} title="Delete STL" className="p-2 rounded bg-red-500/20 text-red-400 hover:bg-red-500 hover:text-white transition-colors">
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Hardware Screw Keepout Zones */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h4 className={t.label}>Bed Screws & Hardware Keepout</h4>
          <span className="text-xs opacity-50 font-mono">{bed?.bed_exclude_area?.length ?? 0} active zones</span>
        </div>
        <p className="text-xs opacity-50 mb-3">
          Downward Z adjustments and low-altitude moves are strictly forbidden over leveling screws to prevent nozzle crashes.
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => addCornerScrewsPreset(30, 30, 12)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition-colors"
          >
            <Plus size={13} />
            <span>Add 4 Corner Screws Preset</span>
          </button>
          <button
            onClick={clearBedExclusions}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-gray-700 hover:border-red-500 hover:text-red-400 text-xs transition-colors"
          >
            <Trash2 size={13} />
            <span>Clear Zones</span>
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Control tab: toolhead jog speeds, move distances, axis inversion ────────
function ControlTab({ uiPrefs, setUiPref, borderClass, brutalist, t }) {
  const [distancesText, setDistancesText] = useState(uiPrefs.moveDistances.join(", "));

  const commitDistances = () => {
    const parsed = distancesText
      .split(",")
      .map((v) => parseFloat(v.trim()))
      .filter((v) => Number.isFinite(v) && v > 0);
    if (parsed.length) {
      setUiPref("moveDistances", parsed);
      setDistancesText(parsed.join(", "));
    } else {
      setDistancesText(uiPrefs.moveDistances.join(", "));
    }
  };

  return (
    <div className="flex flex-col gap-6 max-w-lg">
      <div>
        <h4 className={`mb-3 ${t.label}`}>Jog Speed</h4>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="opacity-60">XY Speed (mm/s)</span>
            <input type="number" min="1" max="500" value={uiPrefs.toolheadSpeedXY}
              onChange={(e) => setUiPref("toolheadSpeedXY", Math.max(1, Number(e.target.value) || 1))}
              className={`px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`} />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="opacity-60">Z Speed (mm/s)</span>
            <input type="number" min="0.5" max="100" step="0.5" value={uiPrefs.toolheadSpeedZ}
              onChange={(e) => setUiPref("toolheadSpeedZ", Math.max(0.5, Number(e.target.value) || 0.5))}
              className={`px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`} />
          </label>
        </div>
        <p className="text-xs opacity-50 mt-2">Applied as the G0/G1 feedrate for manual jog moves from the Toolhead Control panel.</p>
      </div>

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <h4 className={`mb-3 ${t.label}`}>Move Distances</h4>
        <input type="text" value={distancesText}
          onChange={(e) => setDistancesText(e.target.value)}
          onBlur={commitDistances}
          onKeyDown={(e) => e.key === "Enter" && commitDistances()}
          placeholder="0.1, 1, 10, 50"
          className={`w-full px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`} />
        <p className="text-xs opacity-50 mt-2">Comma-separated mm values shown as the step-size chips on the Toolhead Control panel.</p>
      </div>

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <h4 className={`mb-3 ${t.label}`}>Invert Axis Controls</h4>
        <p className="text-xs opacity-50 mb-3">Flips the jog direction sent from the on-screen arrows only — this does not change your printer's own axis configuration.</p>
        <div className="flex flex-col gap-2">
          <Toggle label="Invert X" checked={uiPrefs.invertX} onChange={(v) => setUiPref("invertX", v)} borderClass={borderClass} brutalist={brutalist} />
          <Toggle label="Invert Y" checked={uiPrefs.invertY} onChange={(v) => setUiPref("invertY", v)} borderClass={borderClass} brutalist={brutalist} />
          <Toggle label="Invert Z" checked={uiPrefs.invertZ} onChange={(v) => setUiPref("invertZ", v)} borderClass={borderClass} brutalist={brutalist} />
        </div>
      </div>
    </div>
  );
}

// ── Timelapse tab: real settings backed by indus_overrides.cfg on the
//    server (mode/interval/fps), plus a link to the existing gallery on the
//    Digital Twin page — this tab only owns configuration, not playback. ──
// ── Printers tab: switch-based multi-printer management (see
//    config/printers.py on the backend). Only one Moonraker connection is
//    ever active — "activating" an entry stops the current telemetry
//    worker and starts a new one against the selected host/port, which
//    takes a few seconds and is reflected in the "Switching…" state below.
function PrintersTab({ borderClass, brutalist, t }) {
  const data = useStore((s) => s.printerInstances);
  const fetchInstances = useStore((s) => s.fetchPrinterInstances);
  const addInstance = useStore((s) => s.addPrinterInstance);
  const removeInstance = useStore((s) => s.removePrinterInstance);
  const activateInstance = useStore((s) => s.activatePrinterInstance);

  const [form, setForm] = useState(null); // null = form closed
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => { fetchInstances(); }, [fetchInstances]);

  const startAdd = () => { setForm({ name: "", host: "", port: 7125 }); setError(""); };

  const submitAdd = async () => {
    setError("");
    const result = await addInstance(form.name, form.host, Number(form.port));
    if (result.error) { setError(result.error); return; }
    setForm(null);
  };

  const activate = async (id) => {
    setBusyId(id);
    setError("");
    const result = await activateInstance(id);
    if (result.error) setError(result.error);
    setBusyId(null);
  };

  const remove = async (id) => {
    setError("");
    const result = await removeInstance(id);
    if (result.error) setError(result.error);
  };

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm opacity-70">
        Indus3D switches between printers rather than connecting to several at once — activating one stops the current telemetry connection and starts a fresh one against the printer you pick. This takes a few seconds.
      </p>

      {error && <div className={`p-3 text-xs text-red-500 ${borderClass} ${!brutalist && "rounded-lg"} bg-red-500/5`}>{error}</div>}

      <div className="flex flex-col gap-2">
        {data.printers.map((p) => {
          const isActive = p.id === data.active;
          return (
            <div key={p.id} className={`p-4 flex items-center justify-between gap-3 ${borderClass} ${!brutalist && "rounded-lg"} ${isActive ? "bg-emerald-500/10" : "bg-gray-500/5"}`}>
              <div className="flex items-center gap-3 min-w-0">
                <div className={`w-2 h-2 rounded-full shrink-0 ${isActive ? "bg-emerald-500" : "bg-gray-400"}`} />
                <div className="min-w-0">
                  <div className="font-bold flex items-center gap-2">
                    {p.name}
                    {isActive && <span className="text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-500 font-bold">ACTIVE</span>}
                  </div>
                  <div className="text-xs opacity-50 font-mono">{p.host}:{p.port}</div>
                </div>
              </div>
              <div className="flex gap-2 shrink-0">
                {!isActive && (
                  <button
                    onClick={() => activate(p.id)}
                    disabled={busyId === p.id}
                    className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold transition-all ${borderClass} ${brutalist ? "bg-white hover:bg-emerald-100" : "bg-emerald-500/20 text-emerald-500 hover:bg-emerald-500/30 rounded"} disabled:opacity-40`}
                  >
                    <Check size={13} /> {busyId === p.id ? "Switching…" : "Activate"}
                  </button>
                )}
                {!isActive && (
                  <button onClick={() => remove(p.id)} className="p-2 opacity-50 hover:opacity-100 hover:text-red-500"><Trash2 size={14} /></button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {form ? (
        <div className={`p-4 flex flex-col gap-3 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
          <h4 className={t.label}>Add Printer</h4>
          <div className="grid grid-cols-3 gap-3">
            <label className="flex flex-col gap-1 text-xs col-span-1">
              <span className="opacity-60">Name</span>
              <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Voron 2.4"
                className={`px-3 py-2 text-sm outline-none ${borderClass} ${!brutalist && "rounded-lg bg-white/50"}`} />
            </label>
            <label className="flex flex-col gap-1 text-xs col-span-1">
              <span className="opacity-60">Host / IP</span>
              <input type="text" value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })}
                placeholder="192.168.1.50"
                className={`px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-white/50"}`} />
            </label>
            <label className="flex flex-col gap-1 text-xs col-span-1">
              <span className="opacity-60">Moonraker Port</span>
              <input type="number" value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })}
                className={`px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-white/50"}`} />
            </label>
          </div>
          <div className="flex gap-2">
            <button onClick={submitAdd} className={`px-4 py-2 text-xs font-bold ${borderClass} ${brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded"}`}>Add</button>
            <button onClick={() => setForm(null)} className={`px-4 py-2 text-xs font-bold ${borderClass} ${brutalist ? "bg-white" : "bg-gray-500/10 rounded"}`}>Cancel</button>
          </div>
        </div>
      ) : (
        <button
          onClick={startAdd}
          className={`p-4 flex items-center justify-center gap-2 text-xs font-bold ${borderClass} ${brutalist ? "bg-white hover:bg-gray-100" : "bg-gray-500/5 hover:bg-gray-500/10 rounded-lg"}`}
        >
          <Plus size={16} /> Add Printer
        </button>
      )}
    </div>
  );
}

function TimelapseTab({ borderClass, brutalist, t }) {
  const cfg = useStore((s) => s.timelapseConfig);
  const loaded = useStore((s) => s.timelapseConfigLoaded);
  const fetchTimelapseConfig = useStore((s) => s.fetchTimelapseConfig);
  const saveTimelapseConfig = useStore((s) => s.saveTimelapseConfig);
  const status = useStore((s) => s.timelapseStatus);
  const fetchTimelapseStatus = useStore((s) => s.fetchTimelapseStatus);

  const [draft, setDraft] = useState(cfg);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    fetchTimelapseConfig();
    fetchTimelapseStatus();
  }, [fetchTimelapseConfig, fetchTimelapseStatus]);

  useEffect(() => { setDraft(cfg); }, [cfg]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(cfg);

  const save = async () => {
    setSaving(true);
    setMsg("");
    const result = await saveTimelapseConfig(draft);
    setMsg(result.error ? `Failed: ${result.error}` : "Saved");
    setSaving(false);
    setTimeout(() => setMsg(""), 4000);
  };

  return (
    <div className="flex flex-col gap-6 max-w-lg">
      {status.active && (
        <div className={`p-3 flex items-center gap-2 text-xs font-bold ${borderClass} ${!brutalist && "rounded-lg"} bg-red-500/10 text-red-500`}>
          <Activity size={14} className="animate-pulse" /> Recording in progress ({status.frame_count} frames) — settings are locked until it finishes.
        </div>
      )}

      <Toggle label="Enable Timelapse" description="Capture snapshots during prints and stitch them into a video on completion."
        checked={!!draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} borderClass={borderClass} brutalist={brutalist} />

      <div className={draft.enabled ? "" : "opacity-40 pointer-events-none"}>
        <h4 className={`mb-3 ${t.label}`}>Capture Mode</h4>
        <div className="flex gap-2">
          <button onClick={() => setDraft({ ...draft, mode: "interval" })}
            className={`flex-1 px-4 py-3 text-xs font-bold transition-all ${borderClass} ${draft.mode === "interval" ? (brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded") : (brutalist ? "bg-white" : "bg-gray-500/10 rounded")}`}>
            By Time
          </button>
          <button onClick={() => setDraft({ ...draft, mode: "layer" })}
            className={`flex-1 px-4 py-3 text-xs font-bold transition-all ${borderClass} ${draft.mode === "layer" ? (brutalist ? "bg-blue-300" : "bg-blue-500 text-white rounded") : (brutalist ? "bg-white" : "bg-gray-500/10 rounded")}`}>
            By Layer (Z)
          </button>
        </div>
        <p className="text-xs opacity-50 mt-2">
          {draft.mode === "layer"
            ? "Captures a frame whenever Z increases — no slicer macros needed."
            : "Captures a frame every N seconds while printing."}
        </p>
      </div>

      <div className={`grid grid-cols-2 gap-3 ${draft.enabled ? "" : "opacity-40 pointer-events-none"}`}>
        <label className="flex flex-col gap-1 text-xs">
          <span className="opacity-60">{draft.mode === "layer" ? "Interval (s, unused in Layer mode)" : "Interval (seconds)"}</span>
          <input type="number" min="1" value={draft.interval_s}
            disabled={draft.mode === "layer"}
            onChange={(e) => setDraft({ ...draft, interval_s: Math.max(1, Number(e.target.value) || 1) })}
            className={`px-3 py-2 text-sm font-mono outline-none disabled:opacity-40 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`} />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="opacity-60">Output FPS</span>
          <input type="number" min="1" max="60" value={draft.fps}
            onChange={(e) => setDraft({ ...draft, fps: Math.max(1, Number(e.target.value) || 1) })}
            className={`px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`} />
        </label>
      </div>

      <p className="text-xs opacity-50">
        Requires <code>ffmpeg</code> installed on the server. Applies to the next print — an in-progress capture keeps its current settings.
      </p>

      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={!dirty || saving || status.active}
          className={`px-4 py-2 text-xs font-bold transition-all ${borderClass} ${brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded"} disabled:opacity-40`}
        >
          {saving ? "Saving…" : "Save Timelapse Settings"}
        </button>
        {msg && <span className={`text-xs font-bold ${msg.startsWith("Failed") ? "text-red-500" : "text-emerald-500"}`}>{msg}</span>}
        {!loaded && <span className="text-xs opacity-40 italic">Loading current settings…</span>}
      </div>
    </div>
  );
}

// ── Webcams tab: real, read-only view of Moonraker/crowsnest-discovered
//    cameras (same source as the CameraFeeds dashboard panel). Indus3D has
//    no backend endpoint to write new camera definitions back to Moonraker,
//    so — unlike the earlier static mock — this reflects the real list
//    instead of pretending to support Add/Edit. ─────────────────────────────
function WebcamsTab({ borderClass, brutalist, t }) {
  const [cameras, setCameras] = useState(null); // null = loading
  const [error, setError] = useState(null);

  const load = async () => {
    setError(null);
    setCameras(null);
    try {
      const res = await fetch(`${API}/api/v1/printer/cameras`);
      const data = await res.json();
      setCameras(Array.isArray(data) ? data : []);
    } catch {
      setError("Could not reach the Indus3D API for camera discovery.");
      setCameras([]);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="flex items-center justify-between mb-4">
          <h4 className={t.label}>Discovered Streams</h4>
          <button onClick={load} className={`flex items-center gap-1 px-3 py-1 text-xs font-bold ${borderClass} ${brutalist ? "bg-white" : "bg-gray-500/10 rounded"}`}>
            <RefreshCw size={13} /> Rescan
          </button>
        </div>
        <p className="text-xs opacity-50 mb-4">
          Cameras are auto-discovered from your Moonraker/crowsnest configuration — the same source the dashboard's Live Feed panel uses. Add or edit streams in <code>crowsnest.conf</code> / Moonraker's webcam config, then Rescan.
        </p>

        {cameras === null && <div className="text-xs opacity-50 italic">Loading…</div>}
        {error && <div className="text-xs text-red-500">{error}</div>}
        {cameras && cameras.length === 0 && !error && (
          <div className={`p-4 text-xs opacity-50 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
            No cameras discovered yet.
          </div>
        )}
        {cameras && cameras.length > 0 && (
          <div className="flex flex-col gap-2">
            {cameras.map((cam, i) => (
              <div key={cam.name || i} className={`p-4 flex items-center justify-between ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
                <div className="flex items-center gap-3 min-w-0">
                  <Camera size={22} className="opacity-50 shrink-0" />
                  <div className="min-w-0">
                    <div className="font-bold">{cam.name || `Camera ${i + 1}`}</div>
                    <div className="text-xs opacity-50 font-mono truncate">{cam.stream_url || cam.url || cam.snapshot_url || "—"}</div>
                  </div>
                </div>
                <span className={`text-[9px] px-2 py-0.5 shrink-0 ${t.chip || ""} ${cam.enabled === false ? "bg-red-500/20 text-red-500" : "bg-emerald-500/20 text-emerald-500"} rounded-full`}>
                  {cam.enabled === false ? "Disabled" : "Active"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Presets tab: real CRUD + apply, backed by store.presets / applyPreset ──
function emptyPresetDraft() {
  return { id: null, name: "", extruder: "", bed: "", gcode: "" };
}

function PresetsTab({ borderClass, brutalist, t, uiPrefs }) {
  const presets = useStore((s) => s.presets);
  const addOrUpdatePreset = useStore((s) => s.addOrUpdatePreset);
  const deletePreset = useStore((s) => s.deletePreset);
  const applyPreset = useStore((s) => s.applyPreset);
  const applyCooldown = useStore((s) => s.applyCooldown);
  const cooldownGcode = useStore((s) => s.cooldownGcode);
  const setCooldownGcode = useStore((s) => s.setCooldownGcode);

  const [draft, setDraft] = useState(null); // null = form closed
  const [busyId, setBusyId] = useState(null);

  const startEdit = (preset) => setDraft({ ...preset });
  const startNew = () => setDraft(emptyPresetDraft());

  const save = () => {
    if (!draft.name.trim()) return;
    const id = draft.id || draft.name.trim().toLowerCase().replace(/\s+/g, "-") + "-" + Date.now().toString(36);
    addOrUpdatePreset({
      id,
      name: draft.name.trim(),
      extruder: draft.extruder === "" ? "" : Number(draft.extruder),
      bed: draft.bed === "" ? "" : Number(draft.bed),
      gcode: draft.gcode || "",
    });
    setDraft(null);
  };

  const apply = async (preset) => {
    setBusyId(preset.id);
    await applyPreset(preset);
    setBusyId(null);
  };

  const runCooldown = async () => {
    if (uiPrefs.confirmCooldown && !window.confirm("Set hotend and bed targets to 0°C?")) return;
    setBusyId("__cooldown__");
    await applyCooldown();
    setBusyId(null);
  };

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm opacity-70">
        Preheat presets set extruder/bed targets (and optional custom G-code) with one click. Applying a preset sends real M104/M140 commands to the printer.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {presets.map((p) => (
          <div key={p.id} className={`p-4 flex flex-col gap-2 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
            <div className="flex items-center justify-between">
              <div className="font-bold">{p.name}</div>
              <div className="flex gap-1">
                <button onClick={() => startEdit(p)} className="p-1.5 opacity-50 hover:opacity-100"><Edit3 size={14}/></button>
                <button onClick={() => deletePreset(p.id)} className="p-1.5 opacity-50 hover:opacity-100 hover:text-red-500"><Trash2 size={14}/></button>
              </div>
            </div>
            <div className="flex justify-between text-xs opacity-70">
              <span>Extruder: {p.extruder !== "" ? `${p.extruder}°C` : "—"}</span>
              <span>Bed: {p.bed !== "" ? `${p.bed}°C` : "—"}</span>
            </div>
            <button
              onClick={() => apply(p)}
              disabled={busyId === p.id}
              className={`mt-1 flex items-center justify-center gap-2 px-3 py-1.5 text-xs font-bold transition-all ${borderClass} ${brutalist ? "bg-white hover:bg-emerald-100" : "bg-emerald-500/20 text-emerald-500 hover:bg-emerald-500/30 rounded"} disabled:opacity-40`}
            >
              <Thermometer size={13} /> {busyId === p.id ? "Applying…" : "Apply"}
            </button>
          </div>
        ))}

        <button
          onClick={startNew}
          className={`p-4 flex items-center justify-center gap-2 text-xs font-bold ${borderClass} ${brutalist ? "bg-white hover:bg-gray-100" : "bg-gray-500/5 hover:bg-gray-500/10 rounded-lg"}`}
        >
          <Plus size={16} /> Add Preset
        </button>
      </div>

      {draft && (
        <div className={`p-4 flex flex-col gap-3 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`}>
          <h4 className={t.label}>{draft.id ? "Edit Preset" : "New Preset"}</h4>
          <div className="grid grid-cols-3 gap-3">
            <label className="flex flex-col gap-1 text-xs col-span-1">
              <span className="opacity-60">Name</span>
              <input type="text" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                className={`px-3 py-2 text-sm outline-none ${borderClass} ${!brutalist && "rounded-lg bg-white/50"}`} />
            </label>
            <label className="flex flex-col gap-1 text-xs col-span-1">
              <span className="opacity-60">Extruder °C</span>
              <input type="number" value={draft.extruder} onChange={(e) => setDraft({ ...draft, extruder: e.target.value })}
                className={`px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-white/50"}`} />
            </label>
            <label className="flex flex-col gap-1 text-xs col-span-1">
              <span className="opacity-60">Bed °C</span>
              <input type="number" value={draft.bed} onChange={(e) => setDraft({ ...draft, bed: e.target.value })}
                className={`px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-white/50"}`} />
            </label>
          </div>
          <label className="flex flex-col gap-1 text-xs">
            <span className="opacity-60">Extra G-code (optional, one command per line)</span>
            <textarea rows={2} value={draft.gcode} onChange={(e) => setDraft({ ...draft, gcode: e.target.value })}
              className={`px-3 py-2 text-sm font-mono outline-none ${borderClass} ${!brutalist && "rounded-lg bg-white/50"}`} />
          </label>
          <div className="flex gap-2">
            <button onClick={save} className={`px-4 py-2 text-xs font-bold ${borderClass} ${brutalist ? "bg-emerald-300" : "bg-emerald-500 text-white rounded"}`}>Save</button>
            <button onClick={() => setDraft(null)} className={`px-4 py-2 text-xs font-bold ${borderClass} ${brutalist ? "bg-white" : "bg-gray-500/10 rounded"}`}>Cancel</button>
          </div>
        </div>
      )}

      <div className={`pt-6 ${brutalist ? "border-t-[3px] border-[#111]" : `border-t ${t.border}`}`}>
        <h4 className={`mb-3 ${t.label}`}>Cooldown</h4>
        <p className="text-xs opacity-50 mb-3">Sets both heater targets to 0°C. Add extra G-code (e.g. to retract or park) below if needed.</p>
        <textarea rows={2} value={cooldownGcode} onChange={(e) => setCooldownGcode(e.target.value)}
          placeholder="Optional extra G-code, one command per line"
          className={`w-full px-3 py-2 text-sm font-mono outline-none mb-3 ${borderClass} ${!brutalist && "rounded-lg bg-gray-500/5"}`} />
        <button
          onClick={runCooldown}
          disabled={busyId === "__cooldown__"}
          className={`flex items-center gap-2 px-4 py-2 text-xs font-bold transition-all ${borderClass} ${brutalist ? "bg-white hover:bg-blue-100" : "bg-blue-500/20 text-blue-500 hover:bg-blue-500/30 rounded"} disabled:opacity-40`}
        >
          <Snowflake size={14} /> {busyId === "__cooldown__" ? "Applying…" : "Cooldown Now"}
        </button>
      </div>
    </div>
  );
}
