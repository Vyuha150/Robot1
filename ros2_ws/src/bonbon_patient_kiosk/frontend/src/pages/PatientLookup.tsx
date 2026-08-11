import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiClient } from "../services/api";

export function PatientLookup({ api }: { api: ApiClient }) {
  const navigate = useNavigate();
  const [identifier, setIdentifier] = useState("");
  const [message, setMessage] = useState("");

  const lookup = async () => {
    try {
      const result = await api.lookupPatient(identifier);
      setMessage(`Welcome back, ${result.display_name}!`);
      setTimeout(() => navigate("/intake"), 1200);
    } catch {
      setMessage("No record found — that's okay, we'll create one for you.");
      setTimeout(() => navigate("/intake"), 1200);
    }
  };

  return (
    <div className="screen">
      <h2>Have you visited us before?</h2>
      <p>Enter your phone number to retrieve your details, or skip if you're new.</p>
      <input
        className="kiosk-input"
        placeholder="Phone number"
        value={identifier}
        onChange={(e) => setIdentifier(e.target.value)}
        inputMode="tel"
      />
      {message && <p className="hint-text">{message}</p>}
      <div className="btn-row-large">
        <button className="primary" onClick={lookup} disabled={!identifier.trim()}>Find my record</button>
        <button className="ghost" onClick={() => navigate("/intake")}>Skip — I'm new</button>
      </div>
    </div>
  );
}
