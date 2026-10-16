import { useEffect, useRef } from "react";

/** Calls `fn` every `ms` while `active` (and once right away); pauses while the tab is hidden. */
export function usePolling(fn: () => void, ms: number, active: boolean) {
  const saved = useRef(fn);
  saved.current = fn;

  useEffect(() => {
    if (!active) return;
    const tick = () => document.visibilityState === "visible" && saved.current();
    const timer = window.setInterval(tick, ms);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [ms, active]);
}
