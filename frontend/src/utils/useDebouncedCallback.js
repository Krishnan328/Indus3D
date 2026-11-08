import { useEffect, useState } from "react";
import { debounce } from "./debounce";

// A debounced function with a stable identity that always calls the latest `fn`.
// `wait` is read once, on mount. Pending calls are flushed on unmount so a value is never silently dropped.
export function useDebouncedCallback(fn, wait = 250) {
  const [debounced] = useState(() => debounce(fn, wait));
  useEffect(() => { debounced.update(fn); }, [debounced, fn]);
  useEffect(() => () => { debounced.flush(); }, [debounced]);
  return debounced;
}
