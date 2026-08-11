import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiClient } from "../services/api";
import { useSpeech } from "../hooks/useSpeech";

const emptyForm = (sessionId: string) => ({
  session_id: sessionId,
  full_name: "",
  date_of_birth: "",
  contact_phone: "",
  contact_email: "",
  visit_reason: "",
  symptoms: [] as string[],
  allergies: [] as string[],
  current_medications: [] as string[],
  preferred_language: "en",
  emergency_contact_name: "",
  emergency_contact_phone: "",
  insurance_provider: "",
  insurance_id: "",
  is_red_flag: false,
});

export function IntakeForm({ api, sessionId }: { api: ApiClient; sessionId: string | null }) {
  const navigate = useNavigate();
  const [form, setForm] = useState(emptyForm(sessionId ?? ""));
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const speech = useSpeech();

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const proceedToConfirm = async () => {
    if (!sessionId) return;
    try {
      await api.saveDraft({ ...form, session_id: sessionId });
      setConfirming(true);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const confirmSubmit = async () => {
    if (!sessionId) return;
    try {
      const result = await api.submitIntake(sessionId);
      navigate(result.is_red_flag ? "/feedback" : "/next-steps");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (confirming) {
    return (
      <div className="screen">
        <h2>Please confirm your details</h2>
        <div className="confirm-summary">
          <p><b>Name:</b> {form.full_name}</p>
          <p><b>Date of birth:</b> {form.date_of_birth}</p>
          <p><b>Phone:</b> {form.contact_phone}</p>
          <p><b>Visit reason:</b> {form.visit_reason}</p>
          {form.symptoms.length > 0 && <p><b>Symptoms:</b> {form.symptoms.join(", ")}</p>}
          {form.allergies.length > 0 && <p><b>Allergies:</b> {form.allergies.join(", ")}</p>}
        </div>
        {error && <p className="error-text">{error}</p>}
        <div className="btn-row-large">
          <button className="primary" onClick={confirmSubmit}>Confirm and submit</button>
          <button className="ghost" onClick={() => setConfirming(false)}>Go back and edit</button>
        </div>
      </div>
    );
  }

  return (
    <div className="screen">
      <h2>Tell us about your visit</h2>
      <div className="form-grid">
        <label>Full name
          <input className="kiosk-input" value={form.full_name} onChange={(e) => set("full_name", e.target.value)} />
        </label>
        <label>Date of birth
          <input className="kiosk-input" type="date" value={form.date_of_birth} onChange={(e) => set("date_of_birth", e.target.value)} />
        </label>
        <label>Phone number
          <input className="kiosk-input" inputMode="tel" value={form.contact_phone} onChange={(e) => set("contact_phone", e.target.value)} />
        </label>
        <label>Reason for visit
          <div className="input-with-mic">
            <textarea
              className="kiosk-input"
              value={form.visit_reason}
              onChange={(e) => set("visit_reason", e.target.value)}
              placeholder="e.g. Follow-up checkup, cough, sprained ankle…"
            />
            {speech.supported && (
              <button
                type="button"
                className={`mic-btn ${speech.listening ? "active" : ""}`}
                onClick={() => speech.listen((text) => set("visit_reason", `${form.visit_reason} ${text}`.trim()))}
              >🎙</button>
            )}
          </div>
        </label>
        <label>Allergies (comma-separated, optional)
          <input
            className="kiosk-input"
            value={form.allergies.join(", ")}
            onChange={(e) => set("allergies", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
          />
        </label>
        <label>Current medications (comma-separated, optional)
          <input
            className="kiosk-input"
            value={form.current_medications.join(", ")}
            onChange={(e) => set("current_medications", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
          />
        </label>
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="btn-row-large">
        <button
          className="primary"
          onClick={proceedToConfirm}
          disabled={!form.full_name || !form.date_of_birth || !form.contact_phone || !form.visit_reason}
        >
          Review my details
        </button>
      </div>
    </div>
  );
}
