import { useNavigate } from "react-router-dom";

export function NextSteps() {
  const navigate = useNavigate();
  return (
    <div className="screen">
      <h2>What would you like to do?</h2>
      <div className="choice-grid">
        <button className="choice-tile" onClick={() => navigate("/appointment")}>
          📅 Book an appointment
        </button>
        <button className="choice-tile" onClick={() => navigate("/queue")}>
          🎫 Check in without an appointment
        </button>
        <button className="choice-tile" onClick={() => navigate("/chat")}>
          💬 Ask a question / get directions
        </button>
      </div>
    </div>
  );
}
