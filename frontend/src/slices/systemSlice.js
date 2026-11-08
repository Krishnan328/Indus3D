// System page state: host / MCU info, services, updates, backups, devices and alerts from /api/v1/system/*
// (see backend/api/routes/system.py).
//
// Nothing polls until SystemPage calls `subscribeSystem()`. One 5 s timer then decides which resources are due
// (`dueKinds`: slow data is fetched every 30-60 s, only the tab on screen gets the faster rate), skips ticks while
// the browser tab is hidden, catches up when it becomes visible again, and never overlaps a resource with itself.
// That keeps the page far below the API's 120 requests/minute allowance.
//
// The slice always sends `confirmed: true` for state-changing calls: the confirmation dialog is the page's job.

export const KINDS = ["info", "services", "updates", "backups", "peripherals", "alerts"];

const PATHS = {
  info: "/api/v1/system/info", services: "/api/v1/system/services", updates: "/api/v1/system/updates",
  backups: "/api/v1/system/backups", peripherals: "/api/v1/system/peripherals", alerts: "/api/v1/system/alerts",
};

export const TICK_MS = 5000;
export const INTERVALS = { info: 10000, services: 15000, updates: 60000, backups: 30000, peripherals: 30000, alerts: 60000 };
export const UPDATES_ACTIVE_MS = 5000;     // while an update runs, follow its progress closely

// Which resource each tab needs (alerts are always wanted: the banner list sits above the tabs).
export const TAB_KINDS = {
  host: ["info"], mcus: ["info"], services: ["services"], updates: ["updates"], backups: ["backups"], devices: ["peripherals"],
};

export const emptyResource = () => ({ loaded: false, ok: false, unsupported: false, error: null, ts: 0, data: null });

/** Resources to fetch now. `last` maps kind -> ms timestamp of the last request (missing = never). */
export function dueKinds({ now, last, tab, updatesActive }) {
  const want = ["alerts", ...(TAB_KINDS[tab] || [])];
  return want.filter((kind) => {
    let every = INTERVALS[kind];
    if (kind === "updates" && updatesActive) every = UPDATES_ACTIVE_MS;
    return !(kind in last) || now - last[kind] >= every;
  });
}

/** Folds one HTTP answer into the stored resource: keeps the last good data across errors. */
export function reduceResource(prev, status, body) {
  const base = prev || emptyResource();
  if (status >= 200 && status < 300 && body && body.ok !== false) {
    return { loaded: true, ok: true, unsupported: false, error: null, ts: Date.now(), data: body };
  }
  if (status === 404 && body && body.unsupported) {
    return { loaded: true, ok: false, unsupported: true, error: body.error || "not available on this Moonraker", ts: Date.now(), data: null };
  }
  return { ...base, loaded: true, ok: false, unsupported: false, error: (body && body.error) || `HTTP ${status}` };
}

export function actionMessage(status, body, fallback) {
  if (status === 429) return "Too many requests: wait a moment and try again";
  if (status === 401) return "Not signed in";
  return (body && body.error) || fallback || `HTTP ${status}`;
}

export function createSystemSlice(set, get, getApi) {
  let timer = null;
  let subscribers = 0;
  let onVisible = null;
  let noteTimer = null;
  const last = {};
  const inflight = {};

  const fetchSystem = async (kind, { force = false } = {}) => {
    if (!PATHS[kind] || inflight[kind]) return;
    if (!force && typeof document !== "undefined" && document.hidden) return;
    inflight[kind] = true;
    last[kind] = Date.now();
    try {
      const res = await fetch(`${getApi()}${PATHS[kind]}`);
      const body = await res.json().catch(() => ({}));
      set((s) => ({ systemData: { ...s.systemData, [kind]: reduceResource(s.systemData[kind], res.status, body) } }));
    } catch (e) {
      set((s) => ({ systemData: { ...s.systemData, [kind]: { ...(s.systemData[kind] || emptyResource()), loaded: true, ok: false, error: String(e) } } }));
    } finally {
      inflight[kind] = false;
    }
  };

  const tick = () => {
    if (typeof document !== "undefined" && document.hidden) return;
    const st = get();
    const job = st.systemData.updates?.data?.job;
    const updatesActive = !!(job && job.state === "running") || !!st.systemData.updates?.data?.busy;
    for (const kind of dueKinds({ now: Date.now(), last, tab: st.systemTab, updatesActive })) fetchSystem(kind);
  };

  const refreshNow = (...kinds) => { for (const k of kinds) { delete last[k]; fetchSystem(k, { force: true }); } };

  const note = (tone, text) => {
    const n = { tone, text, ts: Date.now() };
    set({ systemNotice: n });
    if (noteTimer) clearTimeout(noteTimer);
    noteTimer = setTimeout(() => { if (get().systemNotice === n) set({ systemNotice: null }); }, 8000);
    if (noteTimer && noteTimer.unref) noteTimer.unref();      // node (tests): do not keep the process alive
  };

  // POST/DELETE with JSON body; never throws. Returns {ok, status, body, message}.
  const send = async (method, path, body, okMessage) => {
    set({ systemBusy: path });
    try {
      const res = await fetch(`${getApi()}${path}`, {
        method, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmed: true, ...body }),
      });
      const json = await res.json().catch(() => ({}));
      if (res.ok) {
        note("ok", typeof okMessage === "function" ? okMessage(json) : okMessage);
        return { ok: true, status: res.status, body: json, message: null };
      }
      const message = actionMessage(res.status, json, null);
      note("error", message);
      return { ok: false, status: res.status, body: json, message };
    } catch (e) {
      note("error", String(e));
      return { ok: false, status: 0, body: {}, message: String(e) };
    } finally {
      set({ systemBusy: null });
    }
  };

  const subscribeSystem = () => {
    subscribers += 1;
    if (subscribers === 1) {
      tick();
      timer = setInterval(tick, TICK_MS);
      if (typeof document !== "undefined" && document.addEventListener) {
        onVisible = () => { if (!document.hidden) tick(); };
        document.addEventListener("visibilitychange", onVisible);
      }
    }
    let done = false;
    return () => {
      if (done) return;
      done = true;
      subscribers -= 1;
      if (subscribers === 0) {
        if (timer) clearInterval(timer);
        timer = null;
        if (onVisible && typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisible);
        onVisible = null;
      }
    };
  };

  const encode = encodeURIComponent;

  return {
    systemTab: "host",
    systemData: Object.fromEntries(KINDS.map((k) => [k, emptyResource()])),
    systemBusy: null,          // path of the state-changing request in flight
    systemNotice: null,        // {tone: "ok"|"error", text, ts}
    systemDismissed: {},       // alert id -> true (info banners the user closed; cleared on reload)

    fetchSystem,
    refreshSystem: (...kinds) => refreshNow(...(kinds.length ? kinds : KINDS)),
    subscribeSystem,
    _systemSubscribers: () => subscribers,
    setSystemTab: (tab) => { set({ systemTab: tab }); tick(); },
    dismissSystemAlert: (id) => set((s) => ({ systemDismissed: { ...s.systemDismissed, [id]: true } })),

    serviceAction: async (name, action, { confirmSelf = false } = {}) => {
      const r = await send("POST", `/api/v1/system/services/${encode(name)}/${encode(action)}`,
        confirmSelf ? { confirm_self: true } : {}, `${name}: ${action} sent`);
      refreshNow("services");
      return r;
    },
    startUpdate: async (component) => {
      const r = await send("POST", `/api/v1/system/updates/${encode(component)}`, {},
        component === "full" ? "Updating everything..." : `Updating ${component}...`);
      refreshNow("updates");
      return r;
    },
    recoverComponent: async (component, hard = false) => {
      const r = await send("POST", `/api/v1/system/updates/${encode(component)}/recover`, { hard },
        `Recovering ${component}...`);
      refreshNow("updates");
      return r;
    },
    createBackup: async (filename) => {
      const r = await send("POST", "/api/v1/system/backups", filename ? { filename } : {}, "Backup created");
      refreshNow("backups");
      return r;
    },
    restoreBackup: async (filename) => {
      const r = await send("POST", `/api/v1/system/backups/${encode(filename)}/restore`, {},
        "Database restored: Moonraker is restarting");
      refreshNow("backups");
      return r;
    },
    deleteBackup: async (filename) => {
      const r = await send("DELETE", `/api/v1/system/backups/${encode(filename)}`, {}, "Backup deleted");
      refreshNow("backups");
      return r;
    },
  };
}
