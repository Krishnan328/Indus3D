// Small, dependency-free debounce for slider-style controls (fan, flow, babystep ...).
// The backend allows ~120 interactive requests a minute; a slider that sends on every pixel of a drag
// would burn that in seconds. `debounce(fn, ms)` sends once the value has settled; `.flush()` sends
// the pending value immediately (call it on pointer-up / blur), `.cancel()` drops it.

export function debounce(initialFn, wait = 250) {
  let fn = initialFn;
  let timer = null;
  let pendingArgs = null;

  const run = () => {
    timer = null;
    const args = pendingArgs;
    pendingArgs = null;
    if (args) return fn(...args);
    return undefined;
  };

  const debounced = (...args) => {
    pendingArgs = args;
    if (timer) clearTimeout(timer);
    timer = setTimeout(run, wait);
  };
  debounced.flush = () => {
    if (!timer) return undefined;
    clearTimeout(timer);
    return run();
  };
  debounced.cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    pendingArgs = null;
  };
  debounced.pending = () => timer !== null;
  // Swap the function that will be called (used by useDebouncedCallback so it always runs the latest closure).
  debounced.update = (next) => { fn = next; };
  return debounced;
}
