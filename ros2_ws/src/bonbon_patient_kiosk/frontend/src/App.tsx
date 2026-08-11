import { ReactNode, useEffect, useMemo, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { ApiClient } from "./services/api";
import { useSession } from "./hooks/useSession";
import { KioskShell } from "./components/KioskShell";
import { AccessibilityPrefs } from "./components/AccessibilityToolbar";

import { Welcome } from "./pages/Welcome";
import { LanguageSelect } from "./pages/LanguageSelect";
import { Consent } from "./pages/Consent";
import { PatientLookup } from "./pages/PatientLookup";
import { IntakeForm } from "./pages/IntakeForm";
import { NextSteps } from "./pages/NextSteps";
import { AppointmentBooking } from "./pages/AppointmentBooking";
import { QueueCheckIn } from "./pages/QueueCheckIn";
import { ChatAssistant } from "./pages/ChatAssistant";
import { Wayfinding } from "./pages/Wayfinding";
import { Feedback } from "./pages/Feedback";
import { StaffLogin } from "./pages/staff/Login";
import { Dashboard } from "./pages/staff/Dashboard";
import { FacilityMapEditor } from "./pages/staff/FacilityMapEditor";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8090";
const PREFS_KEY = "bonbon.kiosk.a11yPrefs";

function loadPrefs(): AccessibilityPrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* fall through to defaults */ }
  return { largeText: false, highContrast: false, language: "en" };
}

export default function App() {
  const [staffToken, setStaffToken] = useState(sessionStorage.getItem("bonbon.kiosk.staffToken") || "");
  const api = useMemo(() => new ApiClient(DEFAULT_API_BASE_URL, staffToken), [staffToken]);
  const { session, start, end, refresh } = useSession(api);
  const [prefs, setPrefs] = useState<AccessibilityPrefs>(loadPrefs());

  useEffect(() => { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); }, [prefs]);
  useEffect(() => {
    if (staffToken) sessionStorage.setItem("bonbon.kiosk.staffToken", staffToken);
  }, [staffToken]);

  const sessionId = session?.session_id ?? null;

  const beginSession = () => { void start(prefs.language); };
  const endSession = () => { void end(); };

  const staffLogout = () => { setStaffToken(""); sessionStorage.removeItem("bonbon.kiosk.staffToken"); };

  return (
    <Routes>
      <Route path="/staff/login" element={<StaffLogin api={api} onLoggedIn={setStaffToken} />} />
      <Route
        path="/staff/dashboard"
        element={
          <StaffGate token={staffToken} onLogout={staffLogout}>
            <Dashboard api={api} />
          </StaffGate>
        }
      />
      <Route
        path="/staff/facility-map"
        element={
          <StaffGate token={staffToken} onLogout={staffLogout}>
            <FacilityMapEditor api={api} />
          </StaffGate>
        }
      />

      <Route
        path="/*"
        element={
          <KioskShell api={api} sessionId={sessionId} onEndSession={endSession} prefs={prefs} onPrefsChange={setPrefs}>
            <Routes>
              <Route path="/" element={<Welcome onBegin={beginSession} />} />
              <Route path="/language" element={<LanguageSelect prefs={prefs} onPrefsChange={setPrefs} />} />
              <Route path="/consent" element={<Consent api={api} sessionId={sessionId} />} />
              <Route path="/lookup" element={<PatientLookup api={api} />} />
              <Route path="/intake" element={<IntakeForm api={api} sessionId={sessionId} />} />
              <Route path="/next-steps" element={<NextSteps />} />
              <Route path="/appointment" element={<AppointmentBooking api={api} sessionId={sessionId} />} />
              <Route path="/queue" element={<QueueCheckIn api={api} sessionId={sessionId} />} />
              <Route path="/chat" element={<ChatAssistant api={api} sessionId={sessionId} />} />
              <Route path="/wayfinding" element={<Wayfinding api={api} sessionId={sessionId} />} />
              <Route path="/feedback" element={<Feedback api={api} sessionId={sessionId} onEndSession={endSession} />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </KioskShell>
        }
      />
    </Routes>
  );
}

function StaffGate({ token, onLogout, children }: { token: string; onLogout: () => void; children: ReactNode }) {
  const navigate = useNavigate();
  useEffect(() => { if (!token) navigate("/staff/login"); }, [token, navigate]);
  if (!token) return null;
  return (
    <div className="staff-app">
      <nav className="staff-nav">
        <a href="/staff/dashboard">Dashboard</a>
        <a href="/staff/facility-map">Facility Map</a>
        <button className="ghost small" onClick={() => { onLogout(); navigate("/staff/login"); }}>Logout</button>
      </nav>
      {children}
    </div>
  );
}
