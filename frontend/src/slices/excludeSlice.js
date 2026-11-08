// Object exclusion (cancel one part of a running print) on top of POST /api/v1/twin/exclude_object.
// The UI marks the object excluded right away; if the request fails or the backend answers non-2xx
// (Klipper refused, Moonraker down, unknown object, no active print) that mark is rolled back and the
// error is kept in `excludeError` ({name, message, ts}) for a few seconds so the drawer can show a toast.
//
// Same slice pattern as filesSlice.js: `createExcludeSlice(set, get, getApi)` returns a plain object.

export const EXCLUDE_ERROR_MS = 6000;

/** Add `name` to excluded_objects; returns the patch (or null when it is already there). */
export function withExcluded(state, name) {
  const cur = state.exclude_object?.excluded_objects || [];
  if (cur.includes(name)) return null;
  return { exclude_object: { ...(state.exclude_object || {}), excluded_objects: [...cur, name] } };
}

/** Remove `name` from excluded_objects again. */
export function withoutExcluded(state, name) {
  const cur = state.exclude_object?.excluded_objects || [];
  if (!cur.includes(name)) return null;
  return { exclude_object: { ...(state.exclude_object || {}), excluded_objects: cur.filter((n) => n !== name) } };
}

async function errorMessage(res) {
  try {
    const body = await res.json();
    if (body && typeof body.error === "string" && body.error) return body.error;
  } catch { /* not JSON */ }
  return `Could not exclude the object (HTTP ${res.status})`;
}

export function createExcludeSlice(set, get, getApi) {
  let timer = null;
  const fail = (name, message) => {
    const ts = Date.now();
    set({ excludeError: { name, message, ts } });
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      if (get().excludeError?.ts === ts) set({ excludeError: null });
    }, EXCLUDE_ERROR_MS);
  };

  return {
    excludeError: null,

    clearExcludeError: () => { if (timer) clearTimeout(timer); set({ excludeError: null }); },

    excludeObject: async (name) => {
      const added = withExcluded(get(), name);          // optimistic; only roll back what we added
      if (added) set(added);
      const rollback = () => { if (added) { const p = withoutExcluded(get(), name); if (p) set(p); } };
      try {
        const res = await fetch(`${getApi()}/api/v1/twin/exclude_object`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        if (!res.ok) {
          rollback();
          fail(name, await errorMessage(res));
          return false;
        }
        return true;
      } catch (e) {
        rollback();
        fail(name, `Could not reach the server: ${e?.message || e}`);
        return false;
      }
    },
  };
}
