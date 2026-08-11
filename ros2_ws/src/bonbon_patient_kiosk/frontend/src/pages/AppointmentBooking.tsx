import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiClient, AvailabilitySlot, Department, Doctor } from "../services/api";

export function AppointmentBooking({ api, sessionId }: { api: ApiClient; sessionId: string | null }) {
  const navigate = useNavigate();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [slots, setSlots] = useState<AvailabilitySlot[]>([]);
  const [departmentId, setDepartmentId] = useState<string | null>(null);
  const [doctorId, setDoctorId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { api.listDepartments().then(setDepartments).catch(() => setError("Could not load departments.")); }, [api]);
  useEffect(() => {
    if (!departmentId) return;
    api.listDoctors(departmentId).then(setDoctors).catch(() => setError("Could not load doctors."));
  }, [api, departmentId]);
  useEffect(() => {
    if (!doctorId) return;
    api.listSlots(doctorId).then(setSlots).catch(() => setError("Could not load available times."));
  }, [api, doctorId]);

  const book = async (slotId: string) => {
    if (!sessionId || !doctorId) return;
    try {
      const appt = await api.bookAppointment(sessionId, doctorId, slotId, reason);
      setConfirmation(appt.appointment_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (confirmation) {
    return (
      <div className="screen">
        <h2>You're all set!</h2>
        <p>Your appointment is confirmed. Reference: <b>{confirmation.slice(0, 8)}</b></p>
        <div className="btn-row-large">
          <button className="primary" onClick={() => navigate("/chat")}>Need directions there?</button>
          <button className="ghost" onClick={() => navigate("/feedback")}>Done</button>
        </div>
      </div>
    );
  }

  return (
    <div className="screen">
      <h2>Book an appointment</h2>
      {error && <p className="error-text">{error}</p>}

      {!departmentId && (
        <div className="choice-grid">
          {departments.map((d) => (
            <button key={d.department_id} className="choice-tile" onClick={() => setDepartmentId(d.department_id)}>
              {d.name}<br /><small>Floor {d.floor}</small>
            </button>
          ))}
        </div>
      )}

      {departmentId && !doctorId && (
        <>
          <div className="choice-grid">
            {doctors.map((doc) => (
              <button key={doc.doctor_id} className="choice-tile" onClick={() => setDoctorId(doc.doctor_id)}>
                {doc.display_name}
              </button>
            ))}
          </div>
          <button className="ghost" onClick={() => setDepartmentId(null)}>← Back to departments</button>
        </>
      )}

      {doctorId && (
        <>
          <label>Reason for visit (optional)
            <input className="kiosk-input" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="slot-grid">
            {slots.map((s) => (
              <button key={s.slot_id} className="slot-tile" onClick={() => book(s.slot_id)}>
                {new Date(s.start_ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </button>
            ))}
            {slots.length === 0 && <p className="muted">No slots available right now.</p>}
          </div>
          <button className="ghost" onClick={() => setDoctorId(null)}>← Back to doctors</button>
        </>
      )}
    </div>
  );
}
