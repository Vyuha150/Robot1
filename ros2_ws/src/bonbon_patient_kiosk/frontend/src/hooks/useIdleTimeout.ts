import { useEffect, useRef, useState } from "react";

/** Tracks idle time and fires onTimeout after idleMs of no touch/click/keydown.
 * Shows a countdown warning for the last warnBeforeMs so the patient can
 * cancel by tapping — this is the PHI safety control described in the plan:
 * an abandoned kiosk session must not leave a form on screen for the next
 * patient. */
export function useIdleTimeout(idleMs: number, warnBeforeMs: number, onTimeout: () => void) {
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const lastActivity = useRef(Date.now());

  useEffect(() => {
    const bump = () => { lastActivity.current = Date.now(); };
    const events = ["pointerdown", "keydown", "touchstart"];
    events.forEach((e) => window.addEventListener(e, bump));

    const interval = window.setInterval(() => {
      const idleFor = Date.now() - lastActivity.current;
      const remaining = idleMs - idleFor;
      if (remaining <= 0) {
        onTimeout();
      } else if (remaining <= warnBeforeMs) {
        setSecondsLeft(Math.ceil(remaining / 1000));
      } else {
        setSecondsLeft(null);
      }
    }, 500);

    return () => {
      events.forEach((e) => window.removeEventListener(e, bump));
      window.clearInterval(interval);
    };
  }, [idleMs, warnBeforeMs, onTimeout]);

  const reset = () => { lastActivity.current = Date.now(); setSecondsLeft(null); };

  return { secondsLeft, reset };
}
