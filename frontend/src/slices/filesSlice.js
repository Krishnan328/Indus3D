// File manager and print queue state, on top of /api/v1/files/* and /api/v1/queue/* (see
// backend/api/routes/files.py and queue.py). The browser names a *root* (gcodes, config, ...) and a path inside
// it; the server validates both. Nothing here polls on its own: the queue poll only runs while a component
// has called `subscribeQueue()` (the queue card or tab is mounted) and pauses while the browser tab is hidden.
//
// Same slice pattern as printerStatusSlice.js: `createFilesSlice(set, get, getApi)` returns a plain object
// that store.js spreads into the store; no imports from store.js.

import { apiErrorMessage } from "../files/filesLogic.js";

const EMPTY_FM = {
  roots: [], rootsLoaded: false, simulator: false, root: "gcodes", path: "", entries: [], writable: true,
  diskUsage: null, print: { busy: false, filename: "" }, loading: false, error: null, unsupported: false, ts: 0,
};
const EMPTY_QUEUE = {
  loaded: false, available: true, state: null, jobs: [], totals: null, note: "", setup: null, error: null,
  simulator: false, print: null, manualStart: true, automaticTransition: null, unsupported: false, ts: 0,
};
const UPLOAD_CONCURRENCY = 2;
const THUMB_BATCH = 30;

/** URL of a file through the typed download route (``inline`` only honoured for safe preview types). */
export function fileUrl(api, root, path, inline = false) {
  return `${api}/api/v1/files/download?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}${inline ? "&inline=1" : ""}`;
}

/** Directory listing entries (folders then files) from the API response. */
export function entriesFromListing(body) {
  const dirs = (body.dirs || []).map((d) => ({ type: "dir", name: d.name, path: d.path, modified: d.modified, permissions: d.permissions }));
  const files = (body.files || []).map((f) => ({ type: "file", name: f.name, path: f.path, size: f.size, modified: f.modified,
    permissions: f.permissions, meta: f.meta || null, hasMeta: f.has_meta ?? null }));
  return [...dirs, ...files];
}

export function createFilesSlice(set, get, getApi) {
  const base = () => `${getApi()}/api/v1/files`;
  const qbase = () => `${getApi()}/api/v1/queue`;
  let listSeq = 0;
  let thumbInflight = new Set();
  let uploadSeq = 0;
  const xhrs = new Map();
  let queueTimer = null;
  let queueSubscribers = 0;
  let queueInflight = false;
  let queueSeq = 0;

  const call = async (method, url, body) => {
    try {
      const res = await fetch(url, {
        method, ...(body !== undefined ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
      });
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, status: res.status, body: data, message: res.ok ? "" : apiErrorMessage(res.status, data) };
    } catch (e) {
      return { ok: false, status: 0, body: {}, message: String(e) };
    }
  };

  const setFm = (patch) => set((s) => ({ fm: { ...s.fm, ...patch } }));

  // ── Files ────────────────────────────────────────────────────────────────────────────────────────────────
  const fmLoadRoots = async () => {
    const r = await call("GET", `${base()}/roots`);
    if (r.ok) {
      const roots = r.body.roots || [];
      const cur = get().fm.root;
      setFm({ roots, rootsLoaded: true, simulator: !!r.body.simulator, print: r.body.print || get().fm.print,
        unsupported: false, error: null, root: roots.some((x) => x.name === cur) ? cur : (roots[0]?.name || cur) });
    } else {
      setFm({ rootsLoaded: true, error: r.message, unsupported: !!r.body.unsupported });
    }
    return r;
  };

  const fmOpen = async (root, path = "") => {
    const seq = (listSeq += 1);
    setFm({ root, path, loading: true, error: null });
    const r = await call("GET", `${base()}/list?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`);
    if (seq !== listSeq) return r;                                   // a newer navigation won the race
    if (r.ok) {
      setFm({ root: r.body.root, path: r.body.path, entries: entriesFromListing(r.body), writable: !!r.body.writable,
        diskUsage: r.body.disk_usage || null, print: r.body.print || get().fm.print, simulator: !!r.body.simulator,
        loading: false, error: null, unsupported: false, ts: Date.now() });
    } else {
      setFm({ entries: [], loading: false, error: r.message, unsupported: !!r.body.unsupported });
    }
    return r;
  };

  const fmRefresh = () => fmOpen(get().fm.root, get().fm.path);

  const fmOp = async (kind, payload, { refresh = true } = {}) => {
    const r = await call("POST", `${base()}/${kind}`, payload);
    if (r.ok && refresh) fmRefresh();
    return r;
  };

  const fmThumbsFor = async (items) => {
    const have = get().fmThumbs;
    const want = items.filter((i) => i.path && !(`${i.root}:${i.path}` in have) && !thumbInflight.has(`${i.root}:${i.path}`));
    const byRoot = new Map();
    for (const w of want) {
      if (!byRoot.has(w.root)) byRoot.set(w.root, []);
      byRoot.get(w.root).push(w);
    }
    for (const [root, list] of byRoot) {
      for (let i = 0; i < list.length; i += THUMB_BATCH) {
        const chunk = list.slice(i, i + THUMB_BATCH);
        chunk.forEach((c) => thumbInflight.add(`${root}:${c.path}`));
        const r = await call("POST", `${base()}/thumbs`, { root, items: chunk.map((c) => ({ path: c.path, v: c.v ?? null })) });
        const found = r.ok ? (r.body.thumbs || {}) : {};
        set((s) => {
          const next = { ...s.fmThumbs };
          for (const c of chunk) next[`${root}:${c.path}`] = found[c.path] ?? null;
          return { fmThumbs: next };
        });
        chunk.forEach((c) => thumbInflight.delete(`${root}:${c.path}`));
        if (!r.ok && (r.status === 429 || r.status === 0)) break;      // do not hammer a limited / absent API
      }
    }
  };

  const fmTreeLoad = async (root) => {
    const cached = get().fmTree;
    if (cached.root === root && Date.now() - cached.ts < 10000) return cached.files;
    const r = await call("GET", `${base()}/tree?root=${encodeURIComponent(root)}`);
    const files = r.ok ? (r.body.files || []) : [];
    set({ fmTree: { root, files, ts: Date.now() } });
    return files;
  };

  const fmDownloadZip = async (root, items) => {
    try {
      const res = await fetch(`${base()}/zip`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root, items }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        return { ok: false, status: res.status, body: data, message: apiErrorMessage(res.status, data) };
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${items.length === 1 ? items[0].split("/").pop() : root}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      return { ok: true, status: 200, body: {}, message: "" };
    } catch (e) {
      return { ok: false, status: 0, body: {}, message: String(e) };
    }
  };

  // ── Uploads (XMLHttpRequest: fetch has no upload progress) ───────────────────────────────────────────────
  const patchUpload = (id, patch) => set((s) => ({ fmUploads: s.fmUploads.map((u) => (u.id === id ? { ...u, ...patch } : u)) }));

  const pumpUploads = () => {
    const ups = get().fmUploads;
    const active = ups.filter((u) => u.status === "uploading").length;
    const next = ups.filter((u) => u.status === "queued").slice(0, Math.max(0, UPLOAD_CONCURRENCY - active));
    next.forEach(startUpload);
  };

  function startUpload(task) {
    patchUpload(task.id, { status: "uploading", loaded: 0, error: null });
    const form = new FormData();
    form.append("root", task.root);
    form.append("path", task.dir);
    if (task.overwrite) form.append("overwrite", "1");
    form.append("file", task.file, task.name);
    const xhr = new XMLHttpRequest();
    xhrs.set(task.id, xhr);
    xhr.open("POST", `${base()}/upload`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) patchUpload(task.id, { loaded: ev.loaded }); };
    const finish = (patch) => {
      xhrs.delete(task.id);
      patchUpload(task.id, patch);
      if (patch.status === "done" && task.root === get().fm.root) fmRefresh();
      pumpUploads();
    };
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText || "{}"); } catch { body = {}; }
      if (xhr.status >= 200 && xhr.status < 300) finish({ status: "done", loaded: task.size });
      else if (xhr.status === 409 && body.code === "exists") finish({ status: "exists", error: body.error });
      else finish({ status: "error", error: apiErrorMessage(xhr.status, body) });
    };
    xhr.onerror = () => finish({ status: "error", error: "Network error" });
    xhr.onabort = () => finish({ status: "canceled" });
    xhr.send(form);
  }

  const fmUpload = (root, dir, fileList, { overwrite = false } = {}) => {
    const tasks = Array.from(fileList).map((file) => ({
      id: (uploadSeq += 1), file, name: file.name, size: file.size, root, dir, overwrite, loaded: 0, status: "queued", error: null,
    }));
    set((s) => ({ fmUploads: [...s.fmUploads, ...tasks] }));
    pumpUploads();
    return tasks.map((t) => t.id);
  };

  const fmUploadResolve = (id, action) => {
    if (action === "overwrite") {
      set((s) => ({ fmUploads: s.fmUploads.map((u) => (u.id === id ? { ...u, overwrite: true, status: "queued", error: null } : u)) }));
      pumpUploads();
    } else {
      patchUpload(id, { status: "canceled", error: null });
    }
  };

  const fmUploadCancel = (id) => {
    const x = xhrs.get(id);
    if (x) x.abort();
    else patchUpload(id, { status: "canceled" });
  };

  // ── Print queue ──────────────────────────────────────────────────────────────────────────────────────────
  const fetchQueue = async () => {
    if (queueInflight) return;
    if (typeof document !== "undefined" && document.hidden) return;
    queueInflight = true;
    const seq = (queueSeq += 1);
    try {
      const r = await call("GET", `${qbase()}/status`);
      if (seq !== queueSeq) return;
      if (r.ok) {
        const b = r.body;
        set({ queue: { loaded: true, available: b.available !== false, state: b.state ?? null, jobs: b.jobs || [], totals: b.totals || null,
          note: b.note || "", setup: b.setup || null, error: null, simulator: !!b.simulator, print: b.print || null,
          manualStart: b.manual_start !== false, automaticTransition: b.automatic_transition ?? null, unsupported: false, ts: Date.now() } });
      } else {
        set({ queue: { ...get().queue, loaded: true, error: r.message, unsupported: !!r.body.unsupported } });
      }
    } finally {
      queueInflight = false;
    }
  };

  const subscribeQueue = (intervalMs = 7000) => {
    queueSubscribers += 1;
    if (queueSubscribers === 1) {
      fetchQueue();
      queueTimer = setInterval(fetchQueue, intervalMs);
    }
    let done = false;
    return () => {
      if (done) return;
      done = true;
      queueSubscribers -= 1;
      if (queueSubscribers === 0 && queueTimer !== null) {
        clearInterval(queueTimer);
        queueTimer = null;
      }
    };
  };

  const queueCall = async (path, body) => {
    const r = await call("POST", `${qbase()}/${path}`, body ?? {});
    if (r.body?.setup && !r.ok) set({ queue: { ...get().queue, available: false, setup: r.body.setup } });
    fetchQueueNow();
    return r;
  };
  // after a change: refresh now, even if a poll is in flight
  const fetchQueueNow = () => { queueInflight = false; return fetchQueue(); };

  const queueReorder = async (ids) => {
    const cur = get().queue;
    const byId = new Map(cur.jobs.map((j) => [j.id, j]));
    if (ids.length !== cur.jobs.length || ids.some((i) => !byId.has(i))) return { ok: false, status: 0, body: {}, message: "Queue changed" };
    set({ queue: { ...cur, jobs: ids.map((i) => byId.get(i)) } });          // optimistic: the drop already happened visually
    const r = await queueCall("reorder", { ids });
    return r;
  };

  return {
    fm: EMPTY_FM,
    fmThumbs: {},          // "root:path" -> data URI | null (no thumbnail)
    fmUploads: [],         // [{id, name, root, dir, size, loaded, status: queued|uploading|done|exists|error|canceled, error}]
    fmTree: { root: null, files: [], ts: 0 },
    queue: EMPTY_QUEUE,

    fmLoadRoots,
    fmOpen,
    fmRefresh,
    fmOp,
    fmDelete: (root, items, confirmed = false) => fmOp("delete", { root, items, ...(confirmed ? { confirmed: true } : {}) }),
    fmMkdir: (root, path) => fmOp("mkdir", { root, path }),
    fmRename: (root, path, newName) => fmOp("rename", { root, path, new_name: newName }),
    fmTransfer: (kind, root, items, destDir, { destRoot, overwrite = false } = {}) =>
      fmOp(kind, { root, items, dest_dir: destDir, ...(destRoot ? { dest_root: destRoot } : {}), ...(overwrite ? { overwrite: true } : {}) }),
    fmThumbsFor,
    fmTreeLoad,
    fmDownloadZip,
    fmReadText: (root, path) => call("GET", `${base()}/text?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`),
    fmWriteText: (root, path, content, expectedModified, force = false) =>
      call("PUT", `${base()}/text`, { root, path, content, ...(expectedModified != null ? { expected_modified: expectedModified } : {}), ...(force ? { force: true } : {}) }),
    fmRefreshMeta: async (path) => {
      const r = await call("POST", `${base()}/metascan`, { path });
      if (r.ok) fmRefresh();
      return r;
    },
    fmUpload,
    fmUploadResolve,
    fmUploadCancel,
    fmUploadsClear: () => set((s) => ({ fmUploads: s.fmUploads.filter((u) => u.status === "uploading" || u.status === "queued") })),

    fetchQueue,
    subscribeQueue,
    queueAdd: (filenames, { repeat = 1, position = "end", interleave = false } = {}) =>
      queueCall("add", { filenames, ...(repeat > 1 ? { repeat } : {}), ...(position !== "end" ? { position } : {}), ...(interleave ? { interleave: true } : {}) }),
    queueRemove: (ids) => queueCall("remove", { ids }),
    queueClear: () => queueCall("remove", { all: true }),
    queuePause: () => queueCall("pause"),
    queueStart: () => queueCall("start"),
    queueJump: (id) => queueCall("jump", { id }),
    queueReorder,
  };
}
