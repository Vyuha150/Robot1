export type AccessibilityPrefs = { largeText: boolean; highContrast: boolean; language: string };

const LANGUAGES: { code: string; label: string }[] = [
  { code: "en", label: "EN" },
  { code: "zh", label: "中文" },
  { code: "ms", label: "BM" },
  { code: "ta", label: "தமிழ்" },
];

export function AccessibilityToolbar({
  prefs, onChange,
}: { prefs: AccessibilityPrefs; onChange: (p: AccessibilityPrefs) => void }) {
  return (
    <div className="a11y-toolbar" role="toolbar" aria-label="Accessibility options">
      <button
        className={`a11y-btn ${prefs.largeText ? "active" : ""}`}
        onClick={() => onChange({ ...prefs, largeText: !prefs.largeText })}
        aria-pressed={prefs.largeText}
      >
        A{prefs.largeText ? "+" : ""}
      </button>
      <button
        className={`a11y-btn ${prefs.highContrast ? "active" : ""}`}
        onClick={() => onChange({ ...prefs, highContrast: !prefs.highContrast })}
        aria-pressed={prefs.highContrast}
      >
        ◐ Contrast
      </button>
      <div className="a11y-lang-group">
        {LANGUAGES.map((l) => (
          <button
            key={l.code}
            className={`a11y-btn ${prefs.language === l.code ? "active" : ""}`}
            onClick={() => onChange({ ...prefs, language: l.code })}
          >
            {l.label}
          </button>
        ))}
      </div>
    </div>
  );
}
