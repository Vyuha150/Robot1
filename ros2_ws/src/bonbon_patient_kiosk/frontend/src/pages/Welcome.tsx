import { useNavigate } from "react-router-dom";

export function Welcome({ onBegin }: { onBegin: () => void }) {
  const navigate = useNavigate();

  const begin = () => { onBegin(); navigate("/language"); };

  return (
    <div className="screen welcome-screen">
      <h1>Welcome to BonBon</h1>
      <p className="subtitle">Your friendly hospital reception assistant.</p>
      <div className="welcome-actions">
        <button className="primary huge" onClick={begin}>Tap to begin</button>
      </div>
      <div className="welcome-secondary">
        <button className="ghost" onClick={begin}>I just have a question / need directions</button>
      </div>
      <footer className="welcome-footer">
        <a href="/staff/login">Staff login</a>
      </footer>
    </div>
  );
}
