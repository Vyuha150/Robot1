import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiClient, ChatQueryResponse } from "../services/api";
import { useSpeech } from "../hooks/useSpeech";

type Turn = { role: "patient" | "bonbon"; text: string };

export function ChatAssistant({ api, sessionId }: { api: ApiClient; sessionId: string | null }) {
  const navigate = useNavigate();
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([
    { role: "bonbon", text: "Hi! Ask me anything about departments, doctors, or how to get somewhere." },
  ]);
  const [lastResponse, setLastResponse] = useState<ChatQueryResponse | null>(null);
  const speech = useSpeech();

  const send = async (text: string) => {
    if (!sessionId || !text.trim()) return;
    setTurns((t) => [...t, { role: "patient", text }]);
    setInput("");
    try {
      const resp = await api.chatQuery(sessionId, text);
      setLastResponse(resp);
      setTurns((t) => [...t, { role: "bonbon", text: resp.response_text }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "bonbon", text: "Sorry, I couldn't process that. Please ask a staff member." }]);
    }
  };

  return (
    <div className="screen chat-screen">
      <h2>Ask BonBon</h2>
      <div className="chat-log" role="log">
        {turns.map((t, i) => (
          <div key={i} className={`chat-turn ${t.role}`}>{t.text}</div>
        ))}
      </div>
      {lastResponse?.suggested_department_id && (
        <button className="ghost" onClick={() => navigate("/queue")}>Check in to that department</button>
      )}
      <div className="chat-input-row">
        <input
          className="kiosk-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send(input)}
          placeholder="Type your question…"
        />
        {speech.supported && (
          <button className={`mic-btn ${speech.listening ? "active" : ""}`} onClick={() => speech.listen(send)}>🎙</button>
        )}
        <button className="primary" onClick={() => send(input)}>Send</button>
      </div>
      <div className="btn-row-large">
        <button className="ghost" onClick={() => navigate("/wayfinding")}>Get directions to a room</button>
        <button className="ghost" onClick={() => navigate("/feedback")}>Done</button>
      </div>
    </div>
  );
}
