// Live Klipper object status (heaters, temperature sensors, fans, output pins, leveling helpers)
// and the printer's capabilities, from GET /api/v1/printer/status.
//
// Nothing polls until a component calls `subscribePrinterStatus()`; the poll then runs for as long as
// at least one subscriber exists, pauses while the tab is hidden, and never overlaps itself. This keeps
// the dashboard well inside the API's 120 requests/minute allowance.
//
// Pattern for new slices: `createXSlice(set, get, getApi)` returns a plain object that store.js spreads
// into the store. Slices import nothing from store.js (no cycles) and keep timers in closures.

const EMPTY = { loaded: false, ok: false, error: null, ts: 0, status: {}, capabilities: {}, limits: {} };

export function createPrinterStatusSlice(set, get, getApi) {
  let timer = null;
  let subscribers = 0;
  let inflight = false;

  const fetchPrinterStatus = async () => {
    if (inflight) return;
    if (typeof document !== "undefined" && document.hidden) return;
    inflight = true;
    try {
      const res = await fetch(`${getApi()}/api/v1/printer/status`);
      const body = await res.json().catch(() => ({}));
      if (res.ok && body.ok) {
        set({ printerStatus: { loaded: true, ok: true, error: null, ts: body.ts, status: body.status || {},
          capabilities: body.capabilities || {}, limits: body.limits || {} } });
      } else {
        set({ printerStatus: { ...get().printerStatus, loaded: true, ok: false,
          error: body.error || `HTTP ${res.status}` } });
      }
    } catch (e) {
      set({ printerStatus: { ...get().printerStatus, loaded: true, ok: false, error: String(e) } });
    } finally {
      inflight = false;
    }
  };

  const subscribePrinterStatus = (intervalMs = 3000) => {
    subscribers += 1;
    if (subscribers === 1) {
      fetchPrinterStatus();
      timer = setInterval(fetchPrinterStatus, intervalMs);
    }
    let done = false;
    return () => {
      if (done) return;
      done = true;
      subscribers -= 1;
      if (subscribers === 0 && timer) {
        clearInterval(timer);
        timer = null;
      }
    };
  };

  return {
    printerStatus: EMPTY,
    fetchPrinterStatus,
    subscribePrinterStatus,
    _printerStatusSubscribers: () => subscribers,
  };
}
