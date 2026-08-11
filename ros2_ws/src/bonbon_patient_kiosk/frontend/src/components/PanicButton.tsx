import { useState } from "react";
import { ApiClient } from "../services/api";

export function PanicButton({ api, sessionId }: { api: ApiClient; sessionId: string | null }) {
  const [sent, setSent] = useState(false);

  const trigger = async () => {
    if (!sessionId) return;
    try {
      await api.panic(sessionId, "patient_requested");
      setSent(true);
      setTimeout(() => setSent(false), 6000);
    } catch { /* the button must never crash the UI even if this fails */ }
  };

  return (
    <button className="panic-button" onClick={trigger} disabled={!sessionId} aria-label="Call staff for help">
      {sent ? "✓ Staff notified" : "🆘 Call Staff"}
    </button>
  );
}
