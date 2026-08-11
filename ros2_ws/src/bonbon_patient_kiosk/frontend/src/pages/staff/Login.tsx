import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiClient } from "../../services/api";

export function StaffLogin({ api, onLoggedIn }: { api: ApiClient; onLoggedIn: (token: string) => void }) {
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const login = async () => {
    try {
      const result = await api.staffLogin(username, password);
      onLoggedIn(result.access_token);
      navigate("/staff/dashboard");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="screen staff-screen">
      <h2>Staff Login</h2>
      <label>Username<input className="kiosk-input" value={username} onChange={(e) => setUsername(e.target.value)} /></label>
      <label>Password<input className="kiosk-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      {error && <p className="error-text">{error}</p>}
      <div className="btn-row-large">
        <button className="primary" onClick={login}>Log in</button>
        <button className="ghost" onClick={() => navigate("/")}>Back to kiosk</button>
      </div>
    </div>
  );
}
