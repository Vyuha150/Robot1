import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiClient, Department, QueueStatus } from "../services/api";
import { TokenDisplay } from "../components/TokenDisplay";

export function QueueCheckIn({ api, sessionId }: { api: ApiClient; sessionId: string | null }) {
  const navigate = useNavigate();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [status, setStatus] = useState<QueueStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { api.listDepartments().then(setDepartments).catch(() => setError("Could not load departments.")); }, [api]);

  const checkIn = async (departmentId: string) => {
    if (!sessionId) return;
    try {
      const result = await api.checkIn(sessionId, departmentId, "");
      setStatus(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (status) {
    return (
      <div className="screen">
        <h2>Here's your token</h2>
        <TokenDisplay status={status} />
        <div className="btn-row-large">
          <button className="primary" onClick={() => navigate("/chat")}>Need directions to wait there?</button>
          <button className="ghost" onClick={() => navigate("/feedback")}>Done</button>
        </div>
      </div>
    );
  }

  return (
    <div className="screen">
      <h2>Which department do you need?</h2>
      {error && <p className="error-text">{error}</p>}
      <div className="choice-grid">
        {departments.map((d) => (
          <button key={d.department_id} className="choice-tile" onClick={() => checkIn(d.department_id)}>
            {d.name}<br /><small>Floor {d.floor}</small>
          </button>
        ))}
      </div>
    </div>
  );
}
