import { ReactNode, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiClient } from "../services/api";
import { AccessibilityPrefs, AccessibilityToolbar } from "./AccessibilityToolbar";
import { useIdleTimeout } from "../hooks/useIdleTimeout";
import { PanicButton } from "./PanicButton";

const IDLE_TIMEOUT_MS = 90_000;
const WARN_BEFORE_MS = 15_000;

/** Wraps every patient-facing screen: idle-timeout + session wipe (the core
 * PHI safety control), the always-visible panic button, and the
 * accessibility toolbar. Staff/admin screens do NOT use this shell. */
export function KioskShell({
  api, sessionId, onEndSession, prefs, onPrefsChange, children,
}: {
  api: ApiClient; sessionId: string | null; onEndSession: () => void;
  prefs: AccessibilityPrefs; onPrefsChange: (p: AccessibilityPrefs) => void;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  const [dismissedWarning, setDismissedWarning] = useState(false);

  const { secondsLeft, reset } = useIdleTimeout(IDLE_TIMEOUT_MS, WARN_BEFORE_MS, () => {
    onEndSession();
    navigate("/");
  });

  const continueSession = () => { reset(); setDismissedWarning(false); };

  return (
    <div className={`kiosk-shell ${prefs.largeText ? "text-large" : ""} ${prefs.highContrast ? "high-contrast" : ""}`}>
      <header className="kiosk-header">
        <div className="kiosk-brand">🍡 BonBon</div>
        <AccessibilityToolbar prefs={prefs} onChange={onPrefsChange} />
        <PanicButton api={api} sessionId={sessionId} />
      </header>

      <main className="kiosk-main">{children}</main>

      {secondsLeft !== null && !dismissedWarning && (
        <div className="idle-warning-overlay" role="alertdialog">
          <div className="idle-warning-card">
            <p>Are you still there? This session will end in {secondsLeft}s to protect your privacy.</p>
            <button className="primary" onClick={continueSession}>I'm still here</button>
          </div>
        </div>
      )}
    </div>
  );
}
