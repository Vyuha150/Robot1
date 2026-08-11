import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiClient } from "../services/api";

export function Feedback({ api, sessionId, onEndSession }: { api: ApiClient; sessionId: string | null; onEndSession: () => void }) {
  const navigate = useNavigate();
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [done, setDone] = useState(false);

  const finish = async () => {
    if (sessionId && rating > 0) {
      try { await api.submitFeedback(sessionId, rating, comment); } catch { /* best-effort */ }
    }
    setDone(true);
    setTimeout(() => { onEndSession(); navigate("/"); }, 2500);
  };

  if (done) {
    return (
      <div className="screen">
        <h2>Thank you! 🍡</h2>
        <p>Take care, and get well soon.</p>
      </div>
    );
  }

  return (
    <div className="screen">
      <h2>How did we do?</h2>
      <div className="rating-row">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} className={`rating-star ${rating >= n ? "filled" : ""}`} onClick={() => setRating(n)}>★</button>
        ))}
      </div>
      <textarea className="kiosk-input" placeholder="Any comments? (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
      <div className="btn-row-large">
        <button className="primary" onClick={finish}>Finish</button>
        <button className="ghost" onClick={finish}>Skip</button>
      </div>
    </div>
  );
}
