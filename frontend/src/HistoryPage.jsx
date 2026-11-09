import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Clock, CheckCircle, XCircle, AlertCircle, Play, FileDown,
  Trash2, FileText, Video, Search, RefreshCw, BarChart2,
  Zap, Scale, Award, ChevronLeft, ChevronRight, AlertTriangle
} from "lucide-react";
import { useStore } from "./store";
import { useThemeTokens, useIsBrutalist, useIsSoft } from "./theme";

export function HistoryPage({ isDarkMode }) {
  const t = useThemeTokens();
  const brutalist = useIsBrutalist();
  const soft = useIsSoft();

  const API = useStore((s) => s.API);
  const printerState = useStore((s) => s.telemetry?.state);
  const isPrinting = printerState === "printing" || printerState === "paused";

  const [jobs, setJobs] = useState([]);
  const [stats, setStats] = useState(null);
  const [totalCount, setTotalCount] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(15);
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const [confirmJob, setConfirmJob] = useState(null);
  const [reprinting, setReprinting] = useState(false);
  const [actionNotice, setActionNotice] = useState(null);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setErrorMsg("");
    try {
      const params = new URLSearchParams({
        page: String(page),
        limit: String(limit),
        status: statusFilter,
        search: searchQuery.trim(),
        order: "desc",
      });
      const res = await fetch(`${API}/api/v1/history?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setJobs(data.jobs || []);
      setStats(data.stats || null);
      setTotalCount(data.total || 0);
      setTotalPages(data.pages || 1);
    } catch (err) {
      console.error("Failed to fetch print history:", err);
      setErrorMsg("Failed to load print history from host.");
    } finally {
      setLoading(false);
    }
  }, [API, page, limit, statusFilter, searchQuery]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const handleReprint = async (filename) => {
    if (!filename) return;
    setReprinting(true);
    try {
      const res = await fetch(`${API}/api/v1/history/reprint`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || "Reprint request failed");
      }
      setActionNotice({ type: "success", msg: `Reprint started for ${filename}` });
      setConfirmJob(null);
    } catch (err) {
      setActionNotice({ type: "error", msg: `Failed to reprint: ${err.message}` });
    } finally {
      setReprinting(false);
      setTimeout(() => setActionNotice(null), 5000);
    }
  };

  const handleDelete = async (id, filename) => {
    if (!window.confirm(`Delete history entry #${id} (${filename})?`)) return;
    try {
      const res = await fetch(`${API}/api/v1/history/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Delete failed");
      setActionNotice({ type: "success", msg: `Removed job #${id} from history` });
      fetchHistory();
    } catch (err) {
      setActionNotice({ type: "error", msg: `Could not delete job: ${err.message}` });
    } finally {
      setTimeout(() => setActionNotice(null), 4000);
    }
  };

  const exportUrl = `${API}/api/v1/history/export?status=${encodeURIComponent(statusFilter)}&search=${encodeURIComponent(searchQuery.trim())}`;

  // Mini Chart data calculation: recent 12 jobs max duration
  const chartBars = useMemo(() => {
    if (!jobs.length) return [];
    const sample = jobs.slice(0, 14).reverse();
    const maxDur = Math.max(...sample.map((j) => j.print_time_seconds || 0), 60);
    return sample.map((j) => ({
      id: j.id,
      name: j.filename,
      dur: j.print_time_seconds || 0,
      status: j.status,
      pct: Math.max(8, Math.round(((j.print_time_seconds || 0) / maxDur) * 100)),
      timeLabel: j.print_time_formatted || "0s",
    }));
  }, [jobs]);

  return (
    <div className="flex-1 min-w-0 overflow-auto p-4 flex flex-col gap-4" data-testid="history-page">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-blue-500/10 text-blue-400">
            <Clock size={24} />
          </div>
          <div>
            <h2 className={`${t.heading} text-lg font-bold flex items-center gap-2`}>
              Print History & Intelligence
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-mono ${brutalist ? "border border-[#111] bg-gray-200" : "bg-white/10 text-gray-300"}`}>
                {totalCount} {totalCount === 1 ? "Job" : "Jobs"}
              </span>
            </h2>
            <p className="text-xs opacity-60">Full telemetry audit log, QA reports, reprint dispatch, and energy metrics</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <a
            href={exportUrl}
            download="indus3d_print_history.csv"
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition-colors
              ${brutalist ? "border-2 border-[#111] bg-white hover:bg-black hover:text-white" : "bg-white/5 hover:bg-white/10 border border-white/10 text-gray-200"}`}
            title="Export filtered records as CSV"
          >
            <FileDown size={14} />
            Export CSV
          </a>
          <button
            onClick={() => fetchHistory()}
            disabled={loading}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition-colors
              ${brutalist ? "border-2 border-[#111] bg-white hover:bg-black hover:text-white" : "bg-blue-600 hover:bg-blue-700 text-white"}
              ${loading ? "opacity-50 cursor-not-allowed" : ""}`}
            title="Refresh history table"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {actionNotice && (
        <div className={`p-3 rounded-lg text-xs font-semibold flex items-center gap-2 animate-fade-in
          ${actionNotice.type === "success" ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30" : "bg-red-500/10 text-red-400 border border-red-500/30"}`}>
          {actionNotice.type === "success" ? <CheckCircle size={15} /> : <AlertTriangle size={15} />}
          {actionNotice.msg}
        </div>
      )}

      {errorMsg && (
        <div className="p-3 text-xs rounded-lg border border-red-500/50 bg-red-500/10 text-red-400 flex items-center gap-2">
          <AlertCircle size={15} />
          {errorMsg}
        </div>
      )}

      {/* Aggregate KPI Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 shrink-0">
          <div className={`p-3 rounded-xl flex items-center gap-3 ${t.panel}`}>
            <div className="p-2.5 rounded-lg bg-emerald-500/10 text-emerald-400 shrink-0">
              <Award size={20} />
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider opacity-60 font-semibold block">Success Rate</span>
              <div className="text-base font-bold font-mono text-emerald-400">
                {stats.success_rate_pct}%
              </div>
              <span className="text-[9px] opacity-50 block font-mono">
                {stats.completed_count} ok / {stats.cancelled_count} canc / {stats.error_count} err
              </span>
            </div>
          </div>

          <div className={`p-3 rounded-xl flex items-center gap-3 ${t.panel}`}>
            <div className="p-2.5 rounded-lg bg-blue-500/10 text-blue-400 shrink-0">
              <Clock size={20} />
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider opacity-60 font-semibold block">Total Print Time</span>
              <div className="text-base font-bold font-mono">
                {stats.total_hours} <span className="text-xs font-normal opacity-70">hours</span>
              </div>
              <span className="text-[9px] opacity-50 block font-mono">
                {Math.round(stats.total_seconds / 60)} minutes runtime
              </span>
            </div>
          </div>

          <div className={`p-3 rounded-xl flex items-center gap-3 ${t.panel}`}>
            <div className="p-2.5 rounded-lg bg-purple-500/10 text-purple-400 shrink-0">
              <Scale size={20} />
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider opacity-60 font-semibold block">Total Filament</span>
              <div className="text-base font-bold font-mono">
                {stats.total_filament_kg} <span className="text-xs font-normal opacity-70">kg</span>
              </div>
              <span className="text-[9px] opacity-50 block font-mono">
                {stats.total_filament_g} g consumed
              </span>
            </div>
          </div>

          <div className={`p-3 rounded-xl flex items-center gap-3 ${t.panel}`}>
            <div className="p-2.5 rounded-lg bg-amber-500/10 text-amber-400 shrink-0">
              <Zap size={20} />
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider opacity-60 font-semibold block">Power & Cost</span>
              <div className="text-base font-bold font-mono">
                {stats.total_power_kwh} <span className="text-xs font-normal opacity-70">kWh</span>
              </div>
              <span className="text-[9px] opacity-50 block font-mono">
                ${stats.total_cost_usd} USD est.
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Mini Job Duration Bar Chart */}
      {chartBars.length > 0 && (
        <div className={`p-4 rounded-xl flex flex-col gap-2 shrink-0 ${t.panel}`}>
          <div className="flex items-center justify-between text-xs opacity-70 mb-1">
            <span className="flex items-center gap-1.5 font-semibold">
              <BarChart2 size={14} className="text-blue-400" />
              Recent Jobs Duration Profile
            </span>
            <span className="text-[10px] font-mono opacity-60">Showing {chartBars.length} most recent prints</span>
          </div>
          <div className="flex items-end gap-1.5 h-16 pt-2 pb-1 px-1 border-b border-white/5">
            {chartBars.map((b) => (
              <div
                key={b.id}
                className="flex-1 flex flex-col items-center gap-1 group relative cursor-pointer"
                title={`${b.name}\nDuration: ${b.timeLabel}\nStatus: ${b.status}`}
              >
                <div
                  className={`w-full rounded-t transition-all duration-300
                    ${b.status === "completed" ? "bg-emerald-500/80 group-hover:bg-emerald-400"
                      : b.status === "cancelled" ? "bg-amber-500/80 group-hover:bg-amber-400"
                      : "bg-red-500/80 group-hover:bg-red-400"}`}
                  style={{ height: `${b.pct}%` }}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Search & Filter Controls */}
      <div className={`p-3 rounded-xl flex flex-wrap items-center justify-between gap-3 ${t.panel}`}>
        {/* Status filter tabs */}
        <div className="flex items-center gap-1 text-xs">
          {[
            { id: "all", label: "All" },
            { id: "completed", label: "Completed", color: "text-emerald-400" },
            { id: "cancelled", label: "Cancelled", color: "text-amber-400" },
            { id: "error", label: "Errors", color: "text-red-400" },
          ].map((tab) => {
            const active = statusFilter === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => { setStatusFilter(tab.id); setPage(1); }}
                className={`px-3 py-1.5 rounded-lg font-medium transition-colors
                  ${active
                    ? (brutalist ? "bg-black text-white" : "bg-blue-600 text-white font-bold")
                    : (brutalist ? "hover:bg-gray-200" : "hover:bg-white/5 opacity-70 hover:opacity-100")}`}
              >
                <span className={tab.color || ""}>{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Search Input */}
        <div className="flex items-center gap-2 flex-1 max-w-sm ml-auto">
          <div className="relative w-full">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 opacity-40 pointer-events-none" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
              placeholder="Search by filename..."
              className={`w-full pl-9 pr-3 py-1.5 text-xs rounded-lg font-mono focus:outline-none transition-colors
                ${brutalist ? "border-2 border-[#111] bg-white text-[#111]" : "bg-black/30 border border-white/10 text-gray-200 focus:border-blue-500"}`}
            />
            {searchQuery && (
              <button
                onClick={() => { setSearchQuery(""); setPage(1); }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs opacity-50 hover:opacity-100"
              >
                ×
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Main Table */}
      <div className={`rounded-xl overflow-hidden flex-1 min-h-[300px] flex flex-col ${t.panel}`}>
        <div className="overflow-x-auto flex-1">
          <table className="w-full text-left text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-white/10 opacity-60 text-[10px] uppercase tracking-wider bg-white/[0.02]">
                <th className="py-2.5 px-3">Status</th>
                <th className="py-2.5 px-3">File</th>
                <th className="py-2.5 px-3">Duration</th>
                <th className="py-2.5 px-3">Filament</th>
                <th className="py-2.5 px-3">Energy</th>
                <th className="py-2.5 px-3">Time</th>
                <th className="py-2.5 px-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {jobs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-xs opacity-50 italic">
                    {loading ? "Loading print records..." : "No matching print history found."}
                  </td>
                </tr>
              ) : (
                jobs.map((job) => {
                  const status = (job.status || "completed").toLowerCase();
                  const isCompleted = status === "completed";
                  const isCancelled = status === "cancelled";
                  const isError = !isCompleted && !isCancelled;

                  const reportUrl = job.report_path ? `${API}/api/v1/reports/${encodeURIComponent(job.report_path)}` : null;

                  return (
                    <tr key={job.id} className="hover:bg-white/[0.03] transition-colors group">
                      {/* Status */}
                      <td className="py-3 px-3 shrink-0">
                        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold uppercase
                          ${isCompleted ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                            : isCancelled ? "bg-amber-500/10 text-amber-400 border border-amber-500/30"
                            : "bg-red-500/10 text-red-400 border border-red-500/30"}`}>
                          {isCompleted ? <CheckCircle size={11} /> : isCancelled ? <AlertCircle size={11} /> : <XCircle size={11} />}
                          {job.status}
                        </span>
                      </td>

                      {/* File */}
                      <td className="py-3 px-3 max-w-xs truncate font-sans">
                        <span className="font-semibold text-gray-200 block truncate" title={job.filename}>
                          {job.filename}
                        </span>
                        <span className="text-[10px] opacity-40 font-mono">#{job.id}</span>
                        {job.excursions_count > 0 && (
                          <span className="ml-2 text-[9px] px-1 rounded bg-amber-500/20 text-amber-300">
                            {job.excursions_count} alert{job.excursions_count > 1 ? "s" : ""}
                          </span>
                        )}
                      </td>

                      {/* Duration */}
                      <td className="py-3 px-3 whitespace-nowrap opacity-90">
                        {job.print_time_formatted || "0s"}
                      </td>

                      {/* Filament */}
                      <td className="py-3 px-3 whitespace-nowrap opacity-80">
                        {job.filament_used_g ? `${Number(job.filament_used_g).toFixed(1)} g` : "--"}
                      </td>

                      {/* Energy */}
                      <td className="py-3 px-3 whitespace-nowrap opacity-80">
                        {job.power_used_wh ? `${Number(job.power_used_wh).toFixed(1)} Wh` : "--"}
                      </td>

                      {/* Date/Time */}
                      <td className="py-3 px-3 whitespace-nowrap opacity-50 text-[10px]">
                        {job.timestamp ? new Date(job.timestamp * 1000).toLocaleString() : "--"}
                      </td>

                      {/* Actions */}
                      <td className="py-3 px-3 text-right whitespace-nowrap">
                        <div className="flex items-center justify-end gap-1.5 opacity-90">
                          {/* Reprint */}
                          <button
                            onClick={() => setConfirmJob(job)}
                            className={`p-1.5 rounded hover:bg-emerald-500/20 text-emerald-400 transition-colors
                              ${isPrinting ? "opacity-40 cursor-not-allowed" : ""}`}
                            title={isPrinting ? "Printer is currently busy" : "Print Again"}
                            disabled={isPrinting}
                          >
                            <Play size={14} />
                          </button>

                          {/* QA Report */}
                          {reportUrl && (
                            <a
                              href={reportUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="p-1.5 rounded hover:bg-blue-500/20 text-blue-400 transition-colors"
                              title="Download Research QA Report"
                            >
                              <FileText size={14} />
                            </a>
                          )}

                          {/* Timelapse */}
                          {job.timelapse_path && (
                            <a
                              href={`${API}/api/v1/timelapse/${encodeURIComponent(job.timelapse_path)}`}
                              target="_blank"
                              rel="noreferrer"
                              className="p-1.5 rounded hover:bg-purple-500/20 text-purple-400 transition-colors"
                              title="Watch Print Timelapse"
                            >
                              <Video size={14} />
                            </a>
                          )}

                          {/* Delete */}
                          <button
                            onClick={() => handleDelete(job.id, job.filename)}
                            className="p-1.5 rounded hover:bg-red-500/20 text-red-400 transition-colors"
                            title="Delete Record"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div className="p-3 border-t border-white/10 flex items-center justify-between text-xs font-mono opacity-80 shrink-0">
          <div>
            Showing {jobs.length > 0 ? (page - 1) * limit + 1 : 0} – {Math.min(page * limit, totalCount)} of {totalCount} jobs
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
              className={`p-1 rounded border border-white/10 transition-colors
                ${page <= 1 ? "opacity-30 cursor-not-allowed" : "hover:bg-white/10"}`}
              title="Previous Page"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="font-bold">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
              className={`p-1 rounded border border-white/10 transition-colors
                ${page >= totalPages ? "opacity-30 cursor-not-allowed" : "hover:bg-white/10"}`}
              title="Next Page"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Confirmation Modal for Reprint */}
      {confirmJob && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className={`max-w-md w-full p-6 rounded-2xl flex flex-col gap-4 border shadow-2xl ${t.panel}`}>
            <div className="flex items-center gap-3 text-emerald-400">
              <Play size={24} />
              <h3 className="font-bold text-base text-gray-100">Confirm Print Job Dispatch</h3>
            </div>

            <p className="text-xs text-gray-300">
              Do you want to re-print this historical file? The G-code file must still reside on the printer storage.
            </p>

            <div className="p-3 rounded-lg bg-black/40 border border-white/10 font-mono text-xs flex flex-col gap-1">
              <div><span className="opacity-50">Filename:</span> <strong className="text-white">{confirmJob.filename}</strong></div>
              <div><span className="opacity-50">Past Duration:</span> {confirmJob.print_time_formatted}</div>
              <div><span className="opacity-50">Past Filament:</span> {confirmJob.filament_used_g ? `${confirmJob.filament_used_g} g` : "N/A"}</div>
            </div>

            {isPrinting && (
              <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-2">
                <AlertTriangle size={16} className="shrink-0" />
                <span>The printer is currently printing or paused. Starting a new job now may be rejected by Klipper.</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setConfirmJob(null)}
                className="px-4 py-2 rounded-lg text-xs font-semibold hover:bg-white/10 text-gray-300 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleReprint(confirmJob.filename)}
                disabled={reprinting}
                className="px-4 py-2 rounded-lg text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-2 transition-colors disabled:opacity-50"
              >
                {reprinting ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
                Start Printing Now
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
