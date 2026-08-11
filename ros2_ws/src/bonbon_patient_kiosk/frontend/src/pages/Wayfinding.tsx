import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiClient, WayfindingResponse } from "../services/api";

const COMMON_DESTINATIONS = [
  { name: "cardiology_dept", label: "Cardiology" },
  { name: "orthopaedics_dept", label: "Orthopaedics" },
  { name: "paediatrics_dept", label: "Paediatrics" },
  { name: "general_practice_dept", label: "General Practice" },
];

export function Wayfinding({ api, sessionId }: { api: ApiClient; sessionId: string | null }) {
  const navigate = useNavigate();
  const [result, setResult] = useState<WayfindingResponse | null>(null);
  const [error, setError] = useState("");

  const go = async (namedLocation: string, mode: "directions" | "escort") => {
    if (!sessionId) return;
    try {
      const resp = await api.wayfind(sessionId, namedLocation, mode);
      setResult(resp);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="screen">
      <h2>Where do you need to go?</h2>
      <div className="choice-grid">
        {COMMON_DESTINATIONS.map((d) => (
          <div key={d.name} className="wayfind-tile-group">
            <span>{d.label}</span>
            <div className="wayfind-actions">
              <button className="ghost" onClick={() => go(d.name, "directions")}>Show directions</button>
              <button className="primary" onClick={() => go(d.name, "escort")}>Please guide me</button>
            </div>
          </div>
        ))}
      </div>
      {error && <p className="error-text">{error}</p>}
      {result && (
        <div className={`wayfind-result ${result.accepted ? "ok" : "warn"}`}>
          <p>{result.message}</p>
        </div>
      )}
      <div className="btn-row-large">
        <button className="ghost" onClick={() => navigate("/feedback")}>Done</button>
      </div>
    </div>
  );
}
