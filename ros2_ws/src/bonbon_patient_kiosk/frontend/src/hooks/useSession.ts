import { useCallback, useEffect, useState } from "react";
import { ApiClient, SessionInfo } from "../services/api";

const STORAGE_KEY = "bonbon.kiosk.sessionId";

export function useSession(api: ApiClient) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const start = useCallback(async (language: string) => {
    const created = await api.createSession(language);
    sessionStorage.setItem(STORAGE_KEY, created.session_id);
    setSession(created);
    return created;
  }, [api]);

  const end = useCallback(async () => {
    if (session) {
      try { await api.endSession(session.session_id); } catch { /* best-effort */ }
    }
    sessionStorage.removeItem(STORAGE_KEY);
    setSession(null);
  }, [api, session]);

  const refresh = useCallback((patch: Partial<SessionInfo>) => {
    setSession((s) => (s ? { ...s, ...patch } : s));
  }, []);

  useEffect(() => {
    const existing = sessionStorage.getItem(STORAGE_KEY);
    if (!existing) { setLoading(false); return; }
    api.heartbeat(existing).then(setSession).catch(() => sessionStorage.removeItem(STORAGE_KEY)).finally(() => setLoading(false));
  }, [api]);

  // Keep the server-side session alive for as long as this tab considers it
  // active, independent of navigation — page transitions with no API call
  // (reading a consent screen, choosing a language) must not let the
  // backend's idle-purge race ahead of a genuinely present patient. The
  // client's own useIdleTimeout (real touch/keyboard activity) remains the
  // authority on when to actually end the session.
  useEffect(() => {
    if (!session) return;
    const id = window.setInterval(() => {
      api.heartbeat(session.session_id).catch(() => { /* next purge cycle will end it */ });
    }, 20_000);
    return () => window.clearInterval(id);
  }, [api, session?.session_id]);

  return { session, loading, start, end, refresh };
}
