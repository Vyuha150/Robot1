import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiClient } from "../services/api";

export function Consent({ api, sessionId }: { api: ApiClient; sessionId: string | null }) {
  const navigate = useNavigate();
  const [text, setText] = useState("Loading...");
  const [error, setError] = useState("");

  useEffect(() => {
    api.getDisclosure().then((d) => setText(d.text)).catch(() => setText(
      "BonBon will collect the information you enter to check you in, book or " +
      "manage your appointment, and help you find your way."
    ));
  }, [api]);

  const respond = async (given: boolean) => {
    if (!sessionId) return;
    try {
      await api.recordConsent(sessionId, given);
      navigate(given ? "/lookup" : "/chat");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="screen">
      <h2>Before we continue</h2>
      <p className="disclosure-text">{text}</p>
      {error && <p className="error-text">{error}</p>}
      <div className="btn-row-large">
        <button className="primary" onClick={() => respond(true)}>I agree — continue</button>
        <button className="ghost" onClick={() => respond(false)}>No thanks, just answer a question</button>
      </div>
    </div>
  );
}
