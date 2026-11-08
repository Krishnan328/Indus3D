// Run a Klipper macro through the typed endpoint POST /api/v1/printer/macro/<name>.
// (The free-form G-code route only accepts a fixed allowlist, so user macros used to be refused.)

const NO_CONFIRM = new Set(["PAUSE", "RESUME", "CLEAR_PAUSE"]);   // mirrors the backend

export function createMacroSlice(set, get, getApi) {
  const post = async (name, params, confirmed) => {
    const res = await fetch(`${getApi()}/api/v1/printer/macro/${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params, ...(confirmed ? { confirmed: true } : {}) }),
    });
    const body = await res.json().catch(() => ({}));
    return { res, body };
  };

  return {
    macroStatus: null,   // {name, ok, message, ts} of the last run

    runMacro: async (name, params = {}) => {
      const state = get().telemetry?.state;
      const busy = state === "printing" || state === "paused";
      const finish = (ok, message) => {
        const status = { name, ok, message, ts: Date.now() };
        set({ macroStatus: status });
        setTimeout(() => { if (get().macroStatus === status) set({ macroStatus: null }); }, 8000);   // fade the note
        return { ok, message };
      };
      try {
        let confirmed = false;
        if (busy && !NO_CONFIRM.has(name.toUpperCase())) {
          if (!window.confirm(`A print is ${state}. Run macro ${name} anyway?`)) return finish(false, "cancelled");
          confirmed = true;
        }
        let { res, body } = await post(name, params, confirmed);
        if (res.status === 409 && body.needs_confirmation && !confirmed) {   // the printer started meanwhile
          if (!window.confirm(`${body.error}. Run ${name} anyway?`)) return finish(false, "cancelled");
          ({ res, body } = await post(name, params, true));
        }
        if (res.ok) return finish(true, `${name} sent`);
        return finish(false, body.error || body.detail || `HTTP ${res.status}`);
      } catch (e) {
        return finish(false, String(e));
      }
    },
  };
}
