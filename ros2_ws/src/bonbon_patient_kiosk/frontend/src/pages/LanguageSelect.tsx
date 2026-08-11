import { useNavigate } from "react-router-dom";
import { AccessibilityPrefs } from "../components/AccessibilityToolbar";

const OPTIONS = [
  { code: "en", label: "English" },
  { code: "zh", label: "中文" },
  { code: "ms", label: "Bahasa Melayu" },
  { code: "ta", label: "தமிழ்" },
];

export function LanguageSelect({ prefs, onPrefsChange }: { prefs: AccessibilityPrefs; onPrefsChange: (p: AccessibilityPrefs) => void }) {
  const navigate = useNavigate();

  const choose = (code: string) => {
    onPrefsChange({ ...prefs, language: code });
    navigate("/consent");
  };

  return (
    <div className="screen">
      <h2>Choose your language</h2>
      <div className="language-grid">
        {OPTIONS.map((o) => (
          <button key={o.code} className="lang-tile" onClick={() => choose(o.code)}>{o.label}</button>
        ))}
      </div>
    </div>
  );
}
