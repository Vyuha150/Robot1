import { useCallback, useEffect, useState } from "react";
import { ApiClient, DashboardOverview } from "../../services/api";

const POLL_INTERVAL_MS = 5000;

function timeAgo(ts: number): string {
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}

/** Staff-only Customer Interaction Dashboard — live view of everything
 * happening across all patients right now: queue, today's appointments,
 * recent intake (with red-flag alerts), panic/emergency escalations, and
 * feedback. Polls the backend's one-shot overview endpoint; no websocket
 * needed at reception-desk data volumes. */
export function Dashboard({ api }: { api: ApiClient }) {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    api.getDashboardOverview().then(setOverview).catch((e) => setError(String(e)));
  }, [api]);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  const markServed = async (tokenId: string) => {
    try { await api.markTokenServed(tokenId); refresh(); } catch (e) { setError(String(e)); }
  };

  if (error) return <div className="screen staff-screen"><p className="error-text">{error}</p></div>;
  if (!overview) return <div className="screen staff-screen"><p className="muted">Loading…</p></div>;

  return (
    <div className="screen dashboard-screen">
      <h2>Customer Interaction Dashboard</h2>

      {overview.recent_escalations.length > 0 && (
        <div className="alert-banner" role="alert">
          <strong>⚠ Active alerts</strong>
          <ul>
            {overview.recent_escalations.slice(0, 5).map((e, i) => (
              <li key={i}>
                <b>{e.action.replace(/_/g, " ")}</b> — {e.detail} <span className="muted">({timeAgo(e.timestamp)})</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="dashboard-grid">
        <section className="panel">
          <div className="section-title"><span>Live Queue</span><small>{overview.queue.reduce((n, d) => n + d.tokens.length, 0)} waiting</small></div>
          {overview.queue.length === 0 ? <p className="muted">No one waiting.</p> : (
            <div className="queue-board">
              {overview.queue.map((dept) => (
                <div key={dept.department_id} className="queue-dept-card">
                  <h4>{dept.department_name}</h4>
                  {dept.tokens.map((t) => (
                    <div key={t.token_id} className={`queue-row ${t.priority === "urgent" ? "urgent" : ""}`}>
                      <span className="queue-code">{t.token_code}</span>
                      <span>{t.priority === "urgent" ? "URGENT" : `~${Math.round(t.estimated_wait_min)} min`}</span>
                      <button className="small" onClick={() => markServed(t.token_id)}>Mark served</button>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="section-title"><span>Today's Appointments</span><small>{overview.appointments_today.length}</small></div>
          {overview.appointments_today.length === 0 ? <p className="muted">No appointments yet.</p> : (
            <table className="label-table">
              <thead><tr><th>Doctor</th><th>Department</th><th>Time</th><th>Status</th></tr></thead>
              <tbody>
                {overview.appointments_today.map((a) => (
                  <tr key={a.appointment_id}>
                    <td>{a.doctor_name}</td>
                    <td>{a.department_name}</td>
                    <td>{a.start_ts ? new Date(a.start_ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                    <td>{a.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="panel">
          <div className="section-title"><span>Recent Check-ins</span><small>{overview.recent_intake.length}</small></div>
          {overview.recent_intake.length === 0 ? <p className="muted">No check-ins yet.</p> : (
            <div className="intake-list">
              {overview.recent_intake.map((i) => (
                <div key={i.intake_id} className={`intake-row ${i.is_red_flag ? "red-flag" : ""}`}>
                  <strong>{i.full_name}</strong>
                  <span>{i.visit_reason}</span>
                  {i.is_red_flag && <span className="red-flag-tag">⚠ URGENT</span>}
                  <span className="muted">{timeAgo(i.submitted_at)}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="section-title"><span>Feedback</span><small>{overview.feedback.count} responses</small></div>
          <div className="feedback-avg">{overview.feedback.average_rating.toFixed(1)} ★</div>
          {overview.feedback.recent.map((f, i) => (
            <div key={i} className="feedback-item">
              <span>{"★".repeat(f.rating)}{"☆".repeat(5 - f.rating)}</span>
              {f.comment && <p>{f.comment}</p>}
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
