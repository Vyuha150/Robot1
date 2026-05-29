import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type * as CocoSsd from "@tensorflow-models/coco-ssd";
import { ApiClient, LlmProvider, ProviderCatalogItem, ProviderName, TestbenchStatus } from "./services/api";

// ══════════════════════════════════════════════════════════════════════════════
// TYPES
// ══════════════════════════════════════════════════════════════════════════════
type LogLevel = "ok" | "warn" | "error" | "info";
type LogEntry = { time: string; level: LogLevel; text: string };
type VideoMetrics = { fps: number; brightness: number; contrast: number; edgeScore: number; motion: number };
type ObjectDetection = { class_name: string; confidence: number; bbox?: number[] };
type SessionEventStatus = "pass" | "fail" | "warn" | "info";
type TestbenchModule = keyof TestbenchStatus;
type OutputStatus = "idle" | "ok" | "warn" | "error";
type LocalOutputUpdater = (m: TestbenchModule, s: OutputStatus, p: Record<string, unknown>) => void;
type TabId = "overview" | "perception" | "speech" | "intent" | "language" | "tts" | "safety" | "system" | "affective" | "gesture" | "behavior";
type WsStatus = "disconnected" | "connecting" | "connected";
type Emotion = "neutral" | "happy" | "excited" | "calm" | "sad" | "urgent" | "friendly" | "angry" | "whisper";
type SafetyLevel = "INITIALIZING" | "NORMAL" | "CAUTION" | "DEGRADED" | "FAULT" | "DANGER" | "SAFE_STOP";
type IntentResult = { intent: string; confidence: number; slots: { name: string; value: string }[]; is_ambiguous: boolean; fallback_response: string };
type SceneContext = { personCount: number; isCrowded: boolean; proximity: string; dominantActivity: string; spatialContext: string; confidence: number; objects: string[] };
type SceneSnapshot = { id: string; time: string; activity: string; persons: number; spatial: string; objects: number };
type BrowserSpeechRecognition = {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void;
};
type SpeechRecognitionEventLike = { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string; confidence: number } }> };
type SpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

// ══════════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ══════════════════════════════════════════════════════════════════════════════
const INIT_METRICS: VideoMetrics = { fps: 0, brightness: 0, contrast: 0, edgeScore: 0, motion: 0 };
const EMPTY_STATUS: TestbenchStatus = { speech: {}, vision: {}, llm: {}, tts: {}, system: {}, safety: {} };

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: "overview",   label: "Overview",       icon: "◉"  },
  { id: "perception", label: "Perception",      icon: "👁"  },
  { id: "speech",     label: "Speech",          icon: "🎙" },
  { id: "intent",     label: "Intent & Scene",  icon: "🧠" },
  { id: "language",   label: "Language",        icon: "💬" },
  { id: "tts",        label: "TTS",             icon: "🔊" },
  { id: "safety",     label: "Safety",          icon: "🛡"  },
  { id: "system",     label: "System",          icon: "⚙"  },
  { id: "affective",  label: "Affective AI",    icon: "😊" },
  { id: "gesture",    label: "Gesture",         icon: "🤚" },
  { id: "behavior",   label: "Behavior Engine", icon: "🤖" },
];

const FSM_STATES: SafetyLevel[] = ["INITIALIZING", "NORMAL", "CAUTION", "DEGRADED", "FAULT", "DANGER", "SAFE_STOP"];
const FSM_TONES: Record<SafetyLevel, string> = { INITIALIZING: "cyan", NORMAL: "good", CAUTION: "warn", DEGRADED: "warn", FAULT: "danger", DANGER: "danger", SAFE_STOP: "danger" };
const FSM_DESC: Record<SafetyLevel, string> = {
  INITIALIZING: "Sensors starting up", NORMAL: "All systems go", CAUTION: "Minor issue detected",
  DEGRADED: "Servo/motor fault — limited motion", FAULT: "Critical fault", DANGER: "Immediate hazard — stopping",
  SAFE_STOP: "Emergency stop active",
};

const EMOTIONS: Emotion[] = ["neutral", "happy", "excited", "calm", "sad", "urgent", "friendly", "angry", "whisper"];
const EMOTION_ICON: Record<Emotion, string> = { neutral: "😐", happy: "😊", excited: "🤩", calm: "😌", sad: "😢", urgent: "🚨", friendly: "🙂", angry: "😠", whisper: "🤫" };
const EMOTION_SPEED: Record<Emotion, string> = { neutral: "1.00×", happy: "1.08×", excited: "1.18×", calm: "0.91×", sad: "0.83×", urgent: "1.25×", friendly: "1.00×", angry: "1.14×", whisper: "0.87×" };

const ACTIVITY_ICONS: Record<string, string> = { idle: "🟢", interacting: "🔵", navigating: "🟡", serving: "🟣", crowded: "🔴", unknown: "⚪" };
const SPATIAL_ICONS: Record<string, string> = { open_space: "🟩", crowded: "🟥", near_person: "🟦", at_station: "🟪" };

// ══════════════════════════════════════════════════════════════════════════════
// PURE LOGIC — Intent Classifier (mirrors bonbon_perception_ai/intent_engine.py)
// ══════════════════════════════════════════════════════════════════════════════
const INTENT_PATTERNS: Record<string, RegExp[]> = {
  order_item: [/\b(order|bring|get|want|give\s+me|i'?d\s+like|can\s+i\s+have|may\s+i\s+have)\b/i, /\b(coffee|tea|water|juice|food|drink|snack|meal|item|menu)\b/i],
  navigate_to: [/\b(go\s+to|move\s+to|take\s+me\s+to|navigate\s+to|head\s+to|go\s+back)\b/i, /\b(follow\s+me|come\s+here|come\s+to\s+me|come\s+with\s+me)\b/i],
  ask_question: [/^(what|where|when|how|why|who|do\s+you|can\s+you|could\s+you|tell\s+me)\b/i],
  cancel: [/\b(cancel|stop\s+that|abort|never\s?mind|forget\s+it|not\s+anymore)\b/i],
  greeting: [/\b(hello|hi|hey\s*bonbon|good\s+morning|good\s+afternoon|howdy)\b/i],
  emergency_help: [/\b(help|emergency|fallen|fall|hurt|pain|call\s+nurse|call\s+doctor|i\s+need\s+help)\b/i],
  thanks: [/\b(thank\s+you|thanks|thank|much\s+appreciated)\b/i],
  status_check: [/\b(what\s+can\s+you\s+do|what\s+are\s+you|who\s+are\s+you|your\s+name|introduce\s+yourself)\b/i],
  privacy: [/\b(stop\s+recording|don'?t\s+record|privacy\s+mode|delete\s+my\s+data)\b/i],
};
const INTENT_RESPONSES: Record<string, string> = {
  order_item: "I'll bring that right over!", navigate_to: "Sure, I'll take you there.",
  ask_question: "Let me look that up for you.", greeting: "Hello! How can I help you today?",
  emergency_help: "Calling for help immediately!", cancel: "Okay, cancelling that.",
  thanks: "You're welcome! Happy to help.", status_check: "I'm BonBon, your AI service robot.",
  privacy: "Privacy mode activated.", unknown: "I'm not sure I understood. Could you rephrase that?",
};
function classifyIntent(text: string): IntentResult {
  if (!text.trim()) return { intent: "unknown", confidence: 0, slots: [], is_ambiguous: true, fallback_response: "Please say something." };
  let best = "unknown", score = 0;
  for (const [intent, patterns] of Object.entries(INTENT_PATTERNS)) {
    let s = 0; for (const p of patterns) if (p.test(text)) s += 0.55;
    if (s > score) { score = s; best = intent; }
  }
  const slots: { name: string; value: string }[] = [];
  const item = text.match(/\b(coffee|tea|water|juice|food|drink|snack|meal)\b/i);
  if (item) slots.push({ name: "item", value: item[0].toLowerCase() });
  const loc = text.match(/\b(room\s*\d+|floor\s*\d+|reception|canteen|lobby|ward[\s\w]+|corridor|entrance|exit|gate\s*\d*)\b/i);
  if (loc) slots.push({ name: "location", value: loc[0].toLowerCase() });
  const conf = Math.min(0.97, score);
  return { intent: best, confidence: conf, slots, is_ambiguous: conf < 0.4, fallback_response: INTENT_RESPONSES[best] ?? INTENT_RESPONSES.unknown };
}

// ══════════════════════════════════════════════════════════════════════════════
// PURE LOGIC — Scene Analyzer (mirrors bonbon_perception_ai/scene_analyzer.py)
// ══════════════════════════════════════════════════════════════════════════════
function analyzeScene(metrics: VideoMetrics, detections: ObjectDetection[]): SceneContext {
  const personCount = detections.filter((d) => d.class_name === "person").length;
  const isCrowded = personCount > 3 || metrics.motion > 45;
  const proximity = personCount === 0 ? "no person" : metrics.motion > 35 ? "< 2 m" : metrics.motion > 12 ? "2–4 m" : "> 4 m";
  const dominantActivity = personCount > 0 ? (metrics.motion > 25 ? "interacting" : "idle") : "idle";
  const spatialContext = isCrowded ? "crowded" : personCount > 0 ? "near_person" : "open_space";
  const objects = [...new Set(detections.filter((d) => d.class_name !== "person").map((d) => d.class_name))];
  const confidence = Math.min(0.95, 0.5 + metrics.brightness / 200);
  return { personCount, isCrowded, proximity, dominantActivity, spatialContext, confidence, objects };
}

// ══════════════════════════════════════════════════════════════════════════════
// PURE LOGIC — Frame analyser
// ══════════════════════════════════════════════════════════════════════════════
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
function analyseFrame(data: Uint8ClampedArray, prev: Uint8ClampedArray | null, w: number, h: number) {
  let sum = 0, sumSq = 0, motion = 0, edges = 0; const px = w * h;
  for (let i = 0; i < data.length; i += 4) {
    const y = 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
    sum += y; sumSq += y * y;
    if (prev) motion += Math.abs(data[i] - prev[i]);
    const nxt = i + 4;
    if (nxt < data.length) edges += Math.abs(y - (0.2126 * data[nxt] + 0.7152 * data[nxt + 1] + 0.0722 * data[nxt + 2]));
  }
  const mean = sum / px; const variance = Math.max(sumSq / px - mean * mean, 0);
  return { brightness: +((mean / 255) * 100).toFixed(1), contrast: +(Math.sqrt(variance) / 2.55).toFixed(1), edgeScore: +clamp(edges / px / 2.55, 0, 100).toFixed(1), motion: +clamp(motion / px / 2.55, 0, 100).toFixed(1) };
}

// ══════════════════════════════════════════════════════════════════════════════
// UTILITIES
// ══════════════════════════════════════════════════════════════════════════════
const nowStr = () => new Date().toLocaleTimeString();
const asText = (v: unknown, fb = "—") => v === null || v === undefined || v === "" ? fb : typeof v === "object" ? JSON.stringify(v) : String(v);
const asNumber = (v: unknown, fb = 0) => (typeof v === "number" && Number.isFinite(v) ? v : fb);
const asBool = (v: unknown) => Boolean(v);
const mergeStatus = (r: TestbenchStatus, l: TestbenchStatus): TestbenchStatus => ({ speech: { ...r.speech, ...l.speech }, vision: { ...r.vision, ...l.vision }, llm: { ...r.llm, ...l.llm }, tts: { ...r.tts, ...l.tts }, system: { ...r.system, ...l.system }, safety: { ...r.safety, ...l.safety } });
function estimateGrounding(prompt: string, response: string) { const words = new Set(prompt.toLowerCase().split(/\W+/).filter((w) => w.length > 3)); if (!words.size || !response) return 0; const hits = response.toLowerCase().split(/\W+/).filter((w) => words.has(w)).length; return +Math.min(1, hits / Math.max(4, words.size)).toFixed(2); }

// ══════════════════════════════════════════════════════════════════════════════
// MAIN APP COMPONENT
// ══════════════════════════════════════════════════════════════════════════════
export default function App() {
  // Auth & connection
  const [apiBaseUrl, setApiBaseUrl] = useState(localStorage.getItem("bonbon.apiBaseUrl") || "http://127.0.0.1:8080");
  const [token, setToken] = useState(localStorage.getItem("bonbon.token") || "");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [backendStatus, setBackendStatus] = useState<"unknown" | "online" | "offline">("unknown");
  const [robotOnline, setRobotOnline] = useState(false);
  const [wsStatus, setWsStatus] = useState<WsStatus>("disconnected");
  const [authMessage, setAuthMessage] = useState(token ? "Authenticated from saved session" : "Not logged in");
  const [authTone, setAuthTone] = useState<"good" | "warn" | "bad" | "idle">(token ? "good" : "idle");
  const wsRef = useRef<WebSocket | null>(null);

  // UI state
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [sessionId, setSessionId] = useState("");

  // Testbench
  const [testbench, setTestbench] = useState<TestbenchStatus>(EMPTY_STATUS);
  const [localOutputs, setLocalOutputs] = useState<TestbenchStatus>(EMPTY_STATUS);
  const liveStatus = useMemo(() => mergeStatus(testbench, localOutputs), [testbench, localOutputs]);

  // Lifted vision state
  const [detections, setDetections] = useState<ObjectDetection[]>([]);
  const [videoMetrics, setVideoMetrics] = useState<VideoMetrics>(INIT_METRICS);
  const [cameraActive, setCameraActive] = useState(false);

  // Lifted speech state
  const [transcript, setTranscript] = useState("");
  const [audioLevel, setAudioLevel] = useState(0);
  const [vadActive, setVadActive] = useState(false);
  const [micActive, setMicActive] = useState(false);
  const [diarization, setDiarization] = useState<{ speaker: string; text: string; time: string }[]>([]);

  // Derived intent + scene state
  const [intentResult, setIntentResult] = useState<IntentResult | null>(null);
  const [sceneContext, setSceneContext] = useState<SceneContext | null>(null);
  const [sceneHistory, setSceneHistory] = useState<SceneSnapshot[]>([]);

  // Safety state
  const [safetyLevel, setSafetyLevel] = useState<SafetyLevel>("NORMAL");

  // TTS emotion
  const [ttsEmotion, setTtsEmotion] = useState<Emotion>("neutral");

  const api = useMemo(() => new ApiClient(apiBaseUrl, token), [apiBaseUrl, token]);

  const addLog = useCallback((level: LogLevel, text: string) => setLogs((items) => [{ time: nowStr(), level, text }, ...items].slice(0, 50)), []);

  const updateLocalOutput: LocalOutputUpdater = useCallback((module, status, payload) => {
    setLocalOutputs((cur) => ({ ...cur, [module]: { ...cur[module], ...payload, status, updated_at: Date.now() / 1000 } }));
  }, []);

  // ── Persist settings ────────────────────────────────────────────────────────
  useEffect(() => localStorage.setItem("bonbon.apiBaseUrl", apiBaseUrl), [apiBaseUrl]);
  useEffect(() => { if (token) localStorage.setItem("bonbon.token", token); else localStorage.removeItem("bonbon.token"); }, [token]);

  // ── Backend health polling ──────────────────────────────────────────────────
  const checkBackend = useCallback(async () => {
    try {
      const h = await api.health(); setBackendStatus("online"); setRobotOnline(Boolean(h.robot_online));
    } catch { setBackendStatus("offline"); setRobotOnline(false); }
  }, [api]);
  useEffect(() => { void checkBackend(); const id = window.setInterval(() => void checkBackend(), 15000); return () => window.clearInterval(id); }, [checkBackend]);

  // ── Testbench polling ───────────────────────────────────────────────────────
  const refreshTestbench = useCallback(async () => {
    if (!token) return;
    try { const s = await api.testbenchStatus(); setTestbench(s); const sl = String(s.safety?.state ?? "NORMAL") as SafetyLevel; if (FSM_STATES.includes(sl)) setSafetyLevel(sl); }
    catch { /* silent */ }
  }, [api, token]);
  useEffect(() => { void refreshTestbench(); const id = window.setInterval(() => void refreshTestbench(), 4000); return () => window.clearInterval(id); }, [refreshTestbench]);

  // ── WebSocket ───────────────────────────────────────────────────────────────
  const connectWs = useCallback(() => {
    if (!token || wsRef.current?.readyState === WebSocket.OPEN) return;
    setWsStatus("connecting");
    try {
      const ws = api.openWebSocket("robot-status", (data) => {
        const d = data as Record<string, unknown>;
        if (d.safety_state) setSafetyLevel(String(d.safety_state) as SafetyLevel);
        if (d.robot_online !== undefined) setRobotOnline(Boolean(d.robot_online));
        updateLocalOutput("safety", "ok", { state: d.safety_state ?? "NORMAL", battery_pct: d.battery_pct ?? 0, motors_enabled: d.motors_enabled ?? false, watchdog_ok: d.watchdog_ok ?? false, active_faults: d.active_faults ?? [] });
        updateLocalOutput("system", "ok", { robot_online: d.robot_online ?? false, active_task: d.active_task ?? "none" });
      }, () => { setWsStatus("disconnected"); wsRef.current = null; });
      ws.onopen = () => { setWsStatus("connected"); addLog("ok", "WebSocket robot-status connected"); };
      ws.onerror = () => { setWsStatus("disconnected"); addLog("warn", "WebSocket connection failed — using REST polling"); };
      wsRef.current = ws;
    } catch { setWsStatus("disconnected"); }
  }, [token, api, addLog, updateLocalOutput]);
  useEffect(() => { if (token) connectWs(); return () => { wsRef.current?.close(); wsRef.current = null; }; }, [token, connectWs]);

  // ── Intent + scene from lifted state ───────────────────────────────────────
  useEffect(() => { if (transcript.trim()) setIntentResult(classifyIntent(transcript)); }, [transcript]);
  useEffect(() => {
    const ctx = analyzeScene(videoMetrics, detections);
    setSceneContext(ctx);
    if (cameraActive) {
      setSceneHistory((h) => [{ id: Date.now().toString(), time: nowStr(), activity: ctx.dominantActivity, persons: ctx.personCount, spatial: ctx.spatialContext, objects: ctx.objects.length }, ...h].slice(0, 12));
    }
  }, [videoMetrics, detections, cameraActive]);

  // ── Auth ────────────────────────────────────────────────────────────────────
  const login = async () => {
    setAuthMessage("Checking…"); setAuthTone("warn");
    try { const r = await api.login(username, password); setToken(r.access_token); setAuthMessage(`Authenticated as ${username} (${r.role})`); setAuthTone("good"); addLog("ok", `Logged in as ${username} (${r.role})`); }
    catch (e) { const m = `Login failed: ${e instanceof Error ? e.message : String(e)}`; setAuthMessage(m); setAuthTone("bad"); addLog("error", m); }
  };
  const logout = () => { setToken(""); wsRef.current?.close(); wsRef.current = null; setWsStatus("disconnected"); setAuthMessage("Logged out"); setAuthTone("idle"); addLog("info", "Session ended"); };

  // ── Speak with emotion ──────────────────────────────────────────────────────
  const speakWithEmotion = async (text: string, emotion: Emotion) => {
    const t0 = performance.now();
    try {
      await api.speak(text, emotion);
      const lat = Math.round(performance.now() - t0);
      updateLocalOutput("tts", "ok", { current_text: text, emotion, latency_ms: lat, is_speaking: true, backend: "piper" });
      addLog("ok", `TTS sent (${emotion}) in ${lat} ms`);
    } catch (e) { addLog("error", `TTS failed: ${e instanceof Error ? e.message : String(e)}`); }
  };

  // ── Tab content rendered persistently (display:none to preserve media state)
  const tabProps = { api, token, addLog, disabled: !token, liveStatus, updateLocalOutput, sessionId, setSessionId, refreshTestbench, detections, videoMetrics, cameraActive, setCameraActive, setDetections, setVideoMetrics, transcript, setTranscript, audioLevel, setAudioLevel, vadActive, setVadActive, micActive, setMicActive, diarization, setDiarization, intentResult, sceneContext, sceneHistory, safetyLevel, setSafetyLevel, ttsEmotion, setTtsEmotion, speakWithEmotion, backendStatus, robotOnline, wsStatus, connectWs, username, setUsername, password, setPassword, login, logout, authMessage, authTone, apiBaseUrl, setApiBaseUrl, logs, checkBackend };

  return (
    <div className="app-shell">
      <TopNav activeTab={activeTab} setActiveTab={setActiveTab} backendStatus={backendStatus} robotOnline={robotOnline} wsStatus={wsStatus} token={token} />
      <div className="tab-content">
        <div style={{ display: activeTab === "overview"   ? "" : "none" }}><OverviewTab   {...tabProps} /></div>
        <div style={{ display: activeTab === "perception" ? "" : "none" }}><PerceptionTab {...tabProps} /></div>
        <div style={{ display: activeTab === "speech"     ? "" : "none" }}><SpeechTab     {...tabProps} /></div>
        <div style={{ display: activeTab === "intent"     ? "" : "none" }}><IntentTab     {...tabProps} /></div>
        <div style={{ display: activeTab === "language"   ? "" : "none" }}><LanguageTab   {...tabProps} /></div>
        <div style={{ display: activeTab === "tts"        ? "" : "none" }}><TTSTab        {...tabProps} /></div>
        <div style={{ display: activeTab === "safety"     ? "" : "none" }}><SafetyTab     {...tabProps} /></div>
        <div style={{ display: activeTab === "system"     ? "" : "none" }}><SystemTab     {...tabProps} /></div>
        <div style={{ display: activeTab === "affective"  ? "" : "none" }}><AffectiveAITab {...tabProps} /></div>
        <div style={{ display: activeTab === "gesture"    ? "" : "none" }}><GestureTab    {...tabProps} /></div>
        <div style={{ display: activeTab === "behavior"   ? "" : "none" }}><BehaviorEngineTab {...tabProps} /></div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TOP NAV
// ══════════════════════════════════════════════════════════════════════════════
function TopNav({ activeTab, setActiveTab, backendStatus, robotOnline, wsStatus, token }: { activeTab: TabId; setActiveTab: (t: TabId) => void; backendStatus: string; robotOnline: boolean; wsStatus: WsStatus; token: string }) {
  return (
    <header className="top-nav">
      <div className="nav-brand">
        <span className="brand-dot" />
        <strong>BonBon</strong>
        <span className="brand-sub">AI Robot Dashboard</span>
      </div>
      <nav className="nav-tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab-btn ${activeTab === t.id ? "tab-active" : ""}`} onClick={() => setActiveTab(t.id)}>
            <span className="tab-icon">{t.icon}</span>
            <span className="tab-label">{t.label}</span>
          </button>
        ))}
      </nav>
      <div className="nav-status">
        <span className={`status-dot ${backendStatus === "online" ? "good" : backendStatus === "offline" ? "danger" : "warn"}`} title={`Backend: ${backendStatus}`} />
        <span className={`status-dot ${robotOnline ? "good" : "warn"}`} title={`Robot: ${robotOnline ? "online" : "offline"}`} />
        <span className={`status-dot ${wsStatus === "connected" ? "good" : wsStatus === "connecting" ? "warn" : "idle"}`} title={`WS: ${wsStatus}`} />
        <span className="status-dot-label">{token ? "●" : "○"}</span>
      </div>
    </header>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1 — OVERVIEW
// ══════════════════════════════════════════════════════════════════════════════
type TabProps = {
  api: ApiClient; token: string; addLog: (l: LogLevel, t: string) => void; disabled: boolean;
  liveStatus: TestbenchStatus; updateLocalOutput: LocalOutputUpdater;
  sessionId: string; setSessionId: (s: string) => void;
  refreshTestbench: () => Promise<void>;
  detections: ObjectDetection[]; videoMetrics: VideoMetrics;
  cameraActive: boolean; setCameraActive: (v: boolean) => void;
  setDetections: (d: ObjectDetection[]) => void; setVideoMetrics: (m: VideoMetrics) => void;
  transcript: string; setTranscript: (t: string) => void;
  audioLevel: number; setAudioLevel: (l: number) => void;
  vadActive: boolean; setVadActive: (v: boolean) => void;
  micActive: boolean; setMicActive: (v: boolean) => void;
  diarization: { speaker: string; text: string; time: string }[];
  setDiarization: (d: { speaker: string; text: string; time: string }[]) => void;
  intentResult: IntentResult | null;
  sceneContext: SceneContext | null; sceneHistory: SceneSnapshot[];
  safetyLevel: SafetyLevel; setSafetyLevel: (l: SafetyLevel) => void;
  ttsEmotion: Emotion; setTtsEmotion: (e: Emotion) => void;
  speakWithEmotion: (text: string, emotion: Emotion) => Promise<void>;
  backendStatus: string; robotOnline: boolean; wsStatus: WsStatus; connectWs: () => void;
  username: string; setUsername: (s: string) => void;
  password: string; setPassword: (s: string) => void;
  login: () => Promise<void>; logout: () => void;
  authMessage: string; authTone: "good" | "warn" | "bad" | "idle";
  apiBaseUrl: string; setApiBaseUrl: (s: string) => void;
  logs: LogEntry[]; checkBackend: () => Promise<void>;
};

function OverviewTab(p: TabProps) {
  return (
    <div className="tab-body">
      <div className="hero-banner panel">
        <div className="hero-text">
          <p className="eyebrow">BonBon Robot AI — Operator Dashboard</p>
          <h1>AI Testbench Cockpit</h1>
          <p className="subtitle">Real-time monitoring and testing for Perception, Speech, Intent, Language, TTS, Safety, and Navigation — all in one dashboard.</p>
        </div>
        <div className="hero-right">
          <div className="connection-mini panel-inset">
            <div className="section-title"><span>Connection</span></div>
            <label>API URL<input value={p.apiBaseUrl} onChange={(e) => p.setApiBaseUrl(e.target.value)} /></label>
            <div className="two-col" style={{ marginTop: 10 }}>
              <label>User<input value={p.username} onChange={(e) => p.setUsername(e.target.value)} /></label>
              <label>Password<input type="password" value={p.password} onChange={(e) => p.setPassword(e.target.value)} placeholder="runtime only" /></label>
            </div>
            <div className={`auth-banner ${p.authTone}`}><strong>Auth</strong><span>{p.authMessage}</span></div>
            <div className="btn-row">
              <button onClick={() => void p.checkBackend()}>Check</button>
              <button className="primary" onClick={() => void p.login()}>Login</button>
              <button className="ghost" onClick={p.logout}>Logout</button>
            </div>
          </div>
        </div>
      </div>

      <div className="module-grid">
        {[
          { title: "Perception", icon: "👁", items: [["Camera", p.cameraActive ? "active" : "inactive"], ["Objects", String(p.detections.length)], ["Persons", String(p.detections.filter((d) => d.class_name === "person").length)], ["FPS", p.videoMetrics.fps.toFixed(1)]], tone: p.cameraActive ? "good" : "idle" },
          { title: "Speech", icon: "🎙", items: [["Mic", p.micActive ? "listening" : "off"], ["Level", `${Math.round(p.audioLevel)}%`], ["VAD", p.vadActive ? "voice" : "silence"], ["Transcript", p.transcript.slice(0, 24) || "—"]], tone: p.micActive ? "good" : "idle" },
          { title: "Intent & Scene", icon: "🧠", items: [["Intent", p.intentResult?.intent ?? "—"], ["Confidence", p.intentResult ? `${Math.round(p.intentResult.confidence * 100)}%` : "—"], ["Activity", p.sceneContext?.dominantActivity ?? "—"], ["Spatial", p.sceneContext?.spatialContext ?? "—"]], tone: p.intentResult && p.intentResult.confidence > 0.5 ? "good" : "idle" },
          { title: "Language (LLM)", icon: "💬", items: [["Provider", asText(p.liveStatus.llm.provider)], ["Model", asText(p.liveStatus.llm.model)], ["Latency", `${asText(p.liveStatus.llm.latency_ms)} ms`], ["Safety", asText(p.liveStatus.llm.safety_filter)]], tone: asText(p.liveStatus.llm.status) === "ok" ? "good" : "idle" },
          { title: "TTS", icon: "🔊", items: [["Emotion", p.ttsEmotion], ["Speaking", asBool(p.liveStatus.tts.is_speaking) ? "yes" : "no"], ["Queue", asText(p.liveStatus.tts.queue_depth)], ["Backend", asText(p.liveStatus.tts.backend, "piper")]], tone: asBool(p.liveStatus.tts.is_speaking) ? "good" : "idle" },
          { title: "Safety", icon: "🛡", items: [["State", p.safetyLevel], ["Battery", `${asNumber(p.liveStatus.safety.battery_pct)}%`], ["Watchdog", asBool(p.liveStatus.safety.watchdog_ok) ? "OK" : "—"], ["Faults", asText(p.liveStatus.safety.active_faults, "none")]], tone: p.safetyLevel === "NORMAL" ? "good" : p.safetyLevel === "CAUTION" || p.safetyLevel === "DEGRADED" ? "warn" : p.safetyLevel === "INITIALIZING" ? "idle" : "danger" as "good" | "warn" | "idle" | "danger" },
        ].map((mod) => (
          <div key={mod.title} className={`module-card panel ${mod.tone}`}>
            <div className="module-header"><span className="module-icon">{mod.icon}</span><strong>{mod.title}</strong></div>
            {mod.items.map(([k, v]) => <div className="kv-row" key={k}><span>{k}</span><b>{v}</b></div>)}
          </div>
        ))}
      </div>

      <div className="panel" style={{ marginTop: 18 }}>
        <div className="section-title"><span>Event Console</span><small>last 20 actions</small></div>
        <div className="log-list">
          {p.logs.length === 0 ? <p className="muted">No events yet. Start testing a module.</p> : p.logs.slice(0, 20).map((e, i) => (
            <div className={`log-line ${e.level}`} key={i}><span>{e.time}</span><strong>{e.level.toUpperCase()}</strong><p>{e.text}</p></div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2 — PERCEPTION
// ══════════════════════════════════════════════════════════════════════════════
function PerceptionTab(p: TabProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const prevFrameRef = useRef<Uint8ClampedArray | null>(null);
  const animRef = useRef<number | null>(null);
  const detectorRef = useRef<CocoSsd.ObjectDetection | null>(null);
  const detectingRef = useRef(false);
  const lastDetectRef = useRef(0);
  const lastPushRef = useRef(0);
  const [modelStatus, setModelStatus] = useState("COCO-SSD not loaded");
  const [snapshot, setSnapshot] = useState("");
  const [personTrack, setPersonTrack] = useState<{ id: string; class_name: string; confidence: number; bbox: number[]; dist: string }[]>([]);

  const loadDetector = async () => {
    if (detectorRef.current) return detectorRef.current;
    setModelStatus("Loading COCO-SSD…");
    const tf = await import("@tensorflow/tfjs"); await tf.ready();
    const cs = await import("@tensorflow-models/coco-ssd");
    const model = await cs.load(); detectorRef.current = model;
    setModelStatus("COCO-SSD ready (80-class)"); p.addLog("ok", "COCO-SSD object detector loaded");
    return model;
  };

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: false });
      if (videoRef.current) { videoRef.current.srcObject = stream; await videoRef.current.play(); }
      p.setCameraActive(true);
      p.updateLocalOutput("vision", "ok", { camera_active: true, fps: 0, objects: [] });
      void loadDetector().catch((e) => { setModelStatus("Object detector unavailable"); p.addLog("warn", String(e)); });
      p.addLog("ok", "Camera started");
      processFrames();
    } catch (e) { p.addLog("error", `Camera: ${e instanceof Error ? e.message : String(e)}`); }
  };
  const stop = () => {
    if (animRef.current) window.cancelAnimationFrame(animRef.current);
    (videoRef.current?.srcObject as MediaStream | null)?.getTracks().forEach((t) => t.stop());
    if (videoRef.current) videoRef.current.srcObject = null;
    p.setCameraActive(false); p.setDetections([]); p.setVideoMetrics(INIT_METRICS);
    p.updateLocalOutput("vision", "idle", { camera_active: false });
    p.addLog("info", "Camera stopped");
  };

  const processFrames = () => {
    const video = videoRef.current; const canvas = canvasRef.current;
    if (!video || !canvas) return;
    const ctx = canvas.getContext("2d", { willReadFrequently: true }); if (!ctx) return;
    canvas.width = 640; canvas.height = 360; let last = performance.now();
    const loop = () => {
      if (!video.videoWidth) { animRef.current = window.requestAnimationFrame(loop); return; }
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const stats = analyseFrame(frame.data, prevFrameRef.current, canvas.width, canvas.height);
      prevFrameRef.current = new Uint8ClampedArray(frame.data);
      const now2 = performance.now(); const fps = +(1000 / Math.max(now2 - last, 1)).toFixed(1); last = now2;
      const nextMetrics = { ...stats, fps };

      if (now2 - lastDetectRef.current > 900 && !detectingRef.current && detectorRef.current) {
        lastDetectRef.current = now2; detectingRef.current = true;
        void detectorRef.current.detect(video, 10, 0.40).then((preds) => {
          const dets = preds.map((pr) => ({ class_name: pr.class, confidence: +pr.score.toFixed(2), bbox: pr.bbox.map((v) => +v.toFixed(1)) }));
          p.setDetections(dets);
          // Draw overlays
          ctx.lineWidth = 2.5; ctx.font = "bold 13px sans-serif";
          // Clear non-video overlay by redrawing
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          const scX = canvas.width / video.videoWidth; const scY = canvas.height / video.videoHeight;
          dets.forEach((d) => {
            const [x, y, w, h] = d.bbox ?? [0, 0, 0, 0];
            const isPerson = d.class_name === "person";
            ctx.strokeStyle = isPerson ? "#44f2a1" : "#62d4ff";
            ctx.fillStyle = isPerson ? "rgba(68,242,161,0.12)" : "rgba(98,212,255,0.12)";
            ctx.strokeRect(x * scX, y * scY, w * scX, h * scY);
            ctx.fillRect(x * scX, y * scY, w * scX, h * scY);
            // Label
            const label = `${d.class_name} ${Math.round(d.confidence * 100)}%`;
            const lw = ctx.measureText(label).width + 10;
            ctx.fillStyle = isPerson ? "rgba(68,242,161,0.85)" : "rgba(98,212,255,0.85)";
            ctx.fillRect(x * scX, y * scY - 20, lw, 20);
            ctx.fillStyle = "#061b14"; ctx.fillText(label, x * scX + 5, y * scY - 5);
            // Face region for persons
            if (isPerson) {
              const fx = x * scX + (w * scX * 0.2); const fy = y * scY;
              const fw = w * scX * 0.6; const fh = h * scY * 0.35;
              ctx.strokeStyle = "#ffc857"; ctx.setLineDash([4, 3]);
              ctx.strokeRect(fx, fy, fw, fh);
              ctx.setLineDash([]);
              ctx.fillStyle = "rgba(255,200,87,0.7)"; ctx.font = "11px sans-serif";
              ctx.fillText("face region", fx + 2, fy + 12);
              ctx.font = "bold 13px sans-serif";
            }
          });
          const tracks = dets.filter((d) => d.class_name === "person").map((d, idx) => ({ id: `person_${idx}`, ...d, dist: `~${(3 - (d.confidence * 2)).toFixed(1)} m` }));
          setPersonTrack(tracks);
        }).catch(() => { /* silent */ }).finally(() => { detectingRef.current = false; });
      }
      p.setVideoMetrics(nextMetrics);
      if (now2 - lastPushRef.current > 400) {
        lastPushRef.current = now2;
        p.updateLocalOutput("vision", "ok", { camera_active: true, fps: nextMetrics.fps, brightness: nextMetrics.brightness, motion: nextMetrics.motion, objects: p.detections, edge_score: nextMetrics.edgeScore });
      }
      animRef.current = window.requestAnimationFrame(loop);
    };
    loop();
  };

  useEffect(() => () => stop(), []);

  return (
    <div className="tab-body">
      <div className="section-hero"><h2>👁 Perception</h2><p>Object detection (COCO-SSD / YOLOv8), face region overlay, person tracking, and scene metrics. Face recognition runs on the robot via InsightFace/DeepFace.</p></div>
      <div className="grid two-thirds">
        <section className="panel">
          <div className="section-title"><span>Live Camera + Object Detection</span><small>{modelStatus}</small></div>
          <div className="video-stage">
            <video ref={videoRef} playsInline muted />
            <div className="scanline" />
            <canvas ref={canvasRef} style={{ opacity: 1, mixBlendMode: "normal" }} />
          </div>
          <div className="metric-grid-5" style={{ marginTop: 12 }}>
            {[["FPS", p.videoMetrics.fps.toFixed(1)], ["Brightness", `${p.videoMetrics.brightness}%`], ["Contrast", `${p.videoMetrics.contrast}%`], ["Edges", `${p.videoMetrics.edgeScore}%`], ["Motion", `${p.videoMetrics.motion}%`]].map(([l, v]) => <Metric key={l} label={l} value={v} />)}
          </div>
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button className="primary" onClick={() => void start()} disabled={p.cameraActive}>▶ Start Camera</button>
            <button onClick={stop} disabled={!p.cameraActive}>■ Stop</button>
            <button onClick={() => { if (canvasRef.current) setSnapshot(canvasRef.current.toDataURL()); }} disabled={!p.cameraActive}>📷 Capture</button>
          </div>
          {snapshot && <img className="snapshot" src={snapshot} alt="Captured frame" />}
        </section>

        <div className="side-stack">
          <section className="panel">
            <div className="section-title"><span>Detected Objects</span><small>{p.detections.length} objects</small></div>
            {p.detections.length === 0 ? <p className="muted">No objects detected. Start camera.</p> : (
              <div className="detection-list">
                {p.detections.map((d, i) => (
                  <div key={i} className={`detection-item ${d.class_name === "person" ? "person" : ""}`}>
                    <span className="det-class">{d.class_name}</span>
                    <div className="det-bar"><div style={{ width: `${d.confidence * 100}%` }} /></div>
                    <span className="det-conf">{Math.round(d.confidence * 100)}%</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="panel">
            <div className="section-title"><span>Person Tracking</span><small>track IDs + distance</small></div>
            <p className="hint-small">Full tracking (ByteTrack + depth) runs on robot. Browser shows detected persons.</p>
            {personTrack.length === 0 ? <p className="muted">No persons in frame.</p> : (
              <div className="tracking-list">
                {personTrack.map((t) => (
                  <div key={t.id} className="track-card">
                    <div className="track-id">{t.id}</div>
                    <div className="track-details">
                      <span>Conf: {Math.round(t.confidence * 100)}%</span>
                      <span>Dist: {t.dist}</span>
                      <span className="face-tag">👤 face region detected</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="panel">
            <div className="section-title"><span>Face Recognition</span><small>InsightFace / DeepFace on robot</small></div>
            <div className="capability-note">
              <div className="cap-row"><span>Detection</span><b className="cap-browser">Browser (COCO-SSD person)</b></div>
              <div className="cap-row"><span>Face bbox</span><b className="cap-browser">Simulated (upper 35% of person)</b></div>
              <div className="cap-row"><span>Recognition</span><b className="cap-robot">On robot (InsightFace ArcFace)</b></div>
              <div className="cap-row"><span>Age group</span><b className="cap-robot">On robot (DeepFace)</b></div>
              <div className="cap-row"><span>Gaze / facing</span><b className="cap-robot">On robot (body-pose)</b></div>
            </div>
            <p className="hint-small">Yellow dashed boxes in the video = simulated face regions. Real face IDs appear via /bonbon/vision/persons_identified ROS2 topic.</p>
          </section>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3 — SPEECH
// ══════════════════════════════════════════════════════════════════════════════
function SpeechTab(p: TabProps) {
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const animRef = useRef<number | null>(null);
  const lastPushRef = useRef(0);
  const [peak, setPeak] = useState(0);
  const [sttStatus, setSttStatus] = useState("Not started");
  const [listening, setListening] = useState(false);
  const [wakeWordArmed, setWakeWordArmed] = useState(true);
  const [wakeWordFired, setWakeWordFired] = useState(false);
  const WAKE_WORD = /hey\s*bonbon/i;

  const startSTT = () => {
    const Constructors = window as unknown as { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor };
    const SR = Constructors.SpeechRecognition ?? Constructors.webkitSpeechRecognition;
    if (!SR) { setSttStatus("Browser STT unavailable — type manually"); p.addLog("warn", "Browser STT not available"); return; }
    try {
      recognitionRef.current?.stop();
      const rec = new SR(); rec.continuous = true; rec.interimResults = true; rec.lang = "en-US";
      rec.onresult = (ev) => {
        let final = "", interim = "", conf = 0;
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const r = ev.results[i]; const txt = r[0]?.transcript ?? "";
          conf = Math.max(conf, r[0]?.confidence ?? 0);
          if (r.isFinal) final += txt; else interim += txt;
        }
        const full = `${p.transcript} ${final || interim}`.trim();
        p.setTranscript(full);
        setSttStatus(final ? `Final (conf: ${Math.round(conf * 100)}%)` : "Interim…");
        // Wake word detection
        if (wakeWordArmed && WAKE_WORD.test(full)) { setWakeWordFired(true); p.addLog("ok", '🔔 Wake word "Hey Bonbon" detected!'); setTimeout(() => setWakeWordFired(false), 3000); }
        // Diarization simulation
        if (final) {
          const spk = `Speaker ${(p.diarization.length % 2) + 1}`;
          p.setDiarization([{ speaker: spk, text: final.trim(), time: nowStr() }, ...p.diarization].slice(0, 10));
        }
      };
      rec.onerror = (e) => { setSttStatus(`Error: ${e.error ?? "unknown"}`); p.addLog("warn", `STT error: ${e.error}`); };
      rec.onend = () => { setListening(false); setSttStatus("Stopped"); };
      recognitionRef.current = rec; rec.start(); setListening(true); setSttStatus("Listening…");
      p.addLog("ok", "Browser STT started (Whisper on robot for production)");
    } catch (e) { setSttStatus(`Cannot start: ${e instanceof Error ? e.message : String(e)}`); }
  };

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      const ctx = new AudioContext(); const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser(); analyser.fftSize = 2048; src.connect(analyser);
      audioCtxRef.current = ctx; analyserRef.current = analyser; streamRef.current = stream;
      p.setMicActive(true); p.addLog("ok", "Microphone started");
      meterLoop(); startSTT();
    } catch (e) { p.addLog("error", `Mic: ${e instanceof Error ? e.message : String(e)}`); }
  };
  const stop = () => {
    if (animRef.current) window.cancelAnimationFrame(animRef.current);
    recognitionRef.current?.stop(); recognitionRef.current = null; setListening(false);
    streamRef.current?.getTracks().forEach((t) => t.stop()); void audioCtxRef.current?.close();
    p.setAudioLevel(0); p.setVadActive(false); p.setMicActive(false); setPeak(0);
    p.updateLocalOutput("speech", "idle", { audio_heard: false, level_pct: 0, vad_state: "stopped" });
    p.addLog("info", "Microphone stopped");
  };
  const meterLoop = () => {
    const analyser = analyserRef.current; if (!analyser) return;
    const samples = new Uint8Array(analyser.fftSize);
    const loop = () => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0; for (const s of samples) { const n = (s - 128) / 128; sum += n * n; }
      const rms = Math.sqrt(sum / samples.length);
      const level = clamp(rms * 220, 0, 100);
      p.setAudioLevel(level); setPeak((c) => Math.max(c * 0.97, level));
      const vad = level > 7; p.setVadActive(vad);
      const now2 = performance.now();
      if (now2 - lastPushRef.current > 250) {
        lastPushRef.current = now2;
        p.updateLocalOutput("speech", vad ? "ok" : "idle", { audio_heard: vad, level_pct: +level.toFixed(1), transcript: p.transcript, vad_state: vad ? "voice_detected" : "silence" });
      }
      animRef.current = window.requestAnimationFrame(loop);
    };
    loop();
  };
  useEffect(() => () => stop(), []);

  return (
    <div className="tab-body">
      <div className="section-hero"><h2>🎙 Speech Pipeline</h2><p>Microphone input → Voice Activity Detection → Wake Word → Speech-to-Text (Browser / Whisper on robot) → Speaker Diarization</p></div>
      <div className="grid speech-grid">
        <section className="panel">
          <div className="section-title"><span>Microphone + VAD</span><small>{p.micActive ? "active" : "idle"}</small></div>
          <div className="audio-orb" style={{ "--audio": `${p.audioLevel}%` } as CSSProperties}>
            <strong>{Math.round(p.audioLevel)}%</strong>
            <span>{p.vadActive ? "🔊 voice detected" : "silence"}</span>
          </div>
          <div className="meter"><div style={{ width: `${p.audioLevel}%` }} /></div>
          <div className="meter peak"><div style={{ width: `${peak}%` }} /></div>
          <div className="vad-indicators">
            <div className={`vad-chip ${p.vadActive ? "active" : ""}`}>VAD {p.vadActive ? "▲ ACTIVE" : "▼ quiet"}</div>
            <div className={`vad-chip ${wakeWordFired ? "wake" : wakeWordArmed ? "armed" : ""}`}>Wake Word {wakeWordFired ? "🔔 FIRED!" : wakeWordArmed ? "👂 armed" : "disarmed"}</div>
          </div>
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button className="primary" onClick={() => void start()} disabled={p.micActive}>▶ Start Mic</button>
            <button onClick={stop} disabled={!p.micActive}>■ Stop</button>
            <button onClick={() => setWakeWordArmed((a) => !a)}>{wakeWordArmed ? "🔕 Disarm WW" : "🔔 Arm WW"}</button>
          </div>
        </section>

        <section className="panel">
          <div className="section-title"><span>Speech-to-Text</span><small>Browser API (Whisper on robot)</small></div>
          <div className={`stt-status-badge ${listening ? "active" : ""}`}>{listening ? "🔴 Listening" : sttStatus}</div>
          <label style={{ marginTop: 12 }}>Transcript
            <textarea value={p.transcript} onChange={(e) => p.setTranscript(e.target.value)} placeholder="Speak or type — transcript appears here…" style={{ minHeight: 100 }} />
          </label>
          <div className="capability-note" style={{ marginTop: 10 }}>
            <div className="cap-row"><span>Browser STT</span><b className="cap-browser">Web Speech API (Chrome)</b></div>
            <div className="cap-row"><span>Robot STT</span><b className="cap-robot">OpenAI Whisper (offline)</b></div>
            <div className="cap-row"><span>Model size</span><b className="cap-robot">tiny / base / small / medium</b></div>
            <div className="cap-row"><span>VAD</span><b className="cap-robot">Silero VAD (ONNX, ~5 ms)</b></div>
          </div>
          <div className="btn-row" style={{ marginTop: 10 }}>
            <button onClick={() => { p.setTranscript(""); p.setDiarization([]); setSttStatus("Cleared"); }}>Clear transcript</button>
            <button className="primary" onClick={startSTT} disabled={!p.micActive}>↺ Restart STT</button>
          </div>
        </section>

        <section className="panel">
          <div className="section-title"><span>Speaker Diarization</span><small>pyannote.audio on robot</small></div>
          <p className="hint-small">Browser simulates speaker labels by alternating on final transcript segments. Real diarization runs via pyannote.audio on the robot hardware.</p>
          {p.diarization.length === 0 ? <p className="muted">No speech segments yet.</p> : (
            <div className="diarization-list">
              {p.diarization.map((seg, i) => (
                <div key={i} className={`diarization-seg ${seg.speaker.includes("1") ? "spk1" : "spk2"}`}>
                  <div className="seg-header"><strong>{seg.speaker}</strong><span>{seg.time}</span></div>
                  <p>{seg.text}</p>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="section-title"><span>Speech Pipeline Status</span></div>
          <div className="pipeline-flow">
            {[
              { label: "Mic / HAL", status: p.micActive ? "ok" : "idle", note: "ReSpeaker USB" },
              { label: "Audio Preproc", status: p.micActive ? "ok" : "idle", note: "Noise gate" },
              { label: "Wake Word", status: wakeWordFired ? "ok" : wakeWordArmed ? "idle" : "warn", note: "hey bonbon" },
              { label: "VAD (Silero)", status: p.vadActive ? "ok" : "idle", note: `${Math.round(p.audioLevel)}%` },
              { label: "STT (Whisper)", status: listening ? "ok" : "idle", note: "offline" },
              { label: "Diarization", status: p.diarization.length > 0 ? "ok" : "idle", note: "pyannote" },
            ].map((step, i) => (
              <div key={i} className={`pipe-step ${step.status}`}>
                <div className="pipe-dot" />
                <div><strong>{step.label}</strong><small>{step.note}</small></div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4 — INTENT & SCENE
// ══════════════════════════════════════════════════════════════════════════════
function IntentTab(p: TabProps) {
  const [manualText, setManualText] = useState("");
  const [manualResult, setManualResult] = useState<IntentResult | null>(null);
  const [classifySource, setClassifySource] = useState<"text" | "speech" | null>(null);

  // Auto-classify with 350 ms debounce as user types
  useEffect(() => {
    if (!manualText.trim()) { setManualResult(null); setClassifySource(null); return; }
    const t = setTimeout(() => { setManualResult(classifyIntent(manualText)); setClassifySource("text"); }, 350);
    return () => clearTimeout(t);
  }, [manualText]);

  // When speech transcript updates, show it in the input area and auto-classify
  useEffect(() => {
    if (p.transcript.trim() && !manualText.trim()) {
      setManualResult(classifyIntent(p.transcript));
      setClassifySource("speech");
    }
  }, [p.transcript]);

  const classify = () => {
    const text = manualText.trim() || p.transcript.trim();
    if (!text) return;
    const res = classifyIntent(text);
    setManualResult(res);
    setClassifySource(manualText.trim() ? "text" : "speech");
    p.addLog("ok", `Intent: ${res.intent} (${Math.round(res.confidence * 100)}%) via ${manualText.trim() ? "text input" : "speech transcript"}`);
  };

  const useTranscript = () => {
    if (!p.transcript.trim()) return;
    setManualText(p.transcript);
    const res = classifyIntent(p.transcript);
    setManualResult(res);
    setClassifySource("speech");
    p.addLog("ok", `Intent from speech: ${res.intent} (${Math.round(res.confidence * 100)}%)`);
  };

  const sc = p.sceneContext;
  // Prioritise manual result when user has typed; otherwise use speech result
  const ir = manualText.trim() ? (manualResult ?? p.intentResult) : (p.intentResult ?? manualResult);

  const behaviorRecommendation = ir && sc ? (() => {
    if (ir.intent === "emergency_help") return { behavior: "alert_safety", priority: "URGENT", params: { announce: "true" } };
    if (ir.intent === "order_item") return { behavior: "serve_item", priority: "NORMAL", params: { item: ir.slots.find((s) => s.name === "item")?.value ?? "?" } };
    if (ir.intent === "navigate_to") return { behavior: "navigate_to_goal", priority: "NORMAL", params: { destination: ir.slots.find((s) => s.name === "location")?.value ?? "?" } };
    if (ir.intent === "greeting") return { behavior: "speak_greeting", priority: "NORMAL", params: {} };
    if (sc.isCrowded) return { behavior: "slow_down", priority: "HIGH", params: { reason: "crowded_area" } };
    if (ir.intent === "cancel") return { behavior: "stop_navigation", priority: "HIGH", params: {} };
    return { behavior: "speak_response", priority: "NORMAL", params: { response: ir.fallback_response } };
  })() : null;

  return (
    <div className="tab-body">
      <div className="section-hero"><h2>🧠 Intent & Scene Understanding</h2><p>Client-side intent classifier (mirrors robot backend regex engine) + scene analysis from camera. On the robot, LangChain + Ollama can replace the regex backend.</p></div>
      <div className="grid two">
        <section className="panel intent-panel">
          <div className="section-title"><span>Intent Classification</span><small>auto-classifies as you type</small></div>

          {/* ── Result always at top ──────────────────────────────── */}
          <div className={`intent-output-box ${ir ? (ir.confidence > 0.7 ? "has-result high" : ir.confidence > 0.4 ? "has-result mid" : "has-result low") : "empty"}`}>
            {ir ? (
              <>
                <div className="intent-output-label">📊 Classification Result</div>
                <div className="intent-header">
                  <div className="intent-badge">{ir.intent}</div>
                  <div className={`conf-pill ${ir.confidence > 0.7 ? "high" : ir.confidence > 0.4 ? "mid" : "low"}`}>{Math.round(ir.confidence * 100)}% confidence</div>
                  {ir.is_ambiguous && <div className="ambig-tag">⚠ ambiguous</div>}
                </div>
                {ir.slots.length > 0 && (
                  <div className="slots-grid">
                    {ir.slots.map((s) => <div key={s.name} className="slot-chip"><span>{s.name}</span><b>{s.value}</b></div>)}
                  </div>
                )}
                <div className="fallback-response">💬 "{ir.fallback_response}"</div>
                {p.transcript && <div className="kv-row" style={{ marginTop: 6 }}><span>From transcript</span><b style={{ fontSize: "0.82rem", opacity: 0.75 }}>{p.transcript.slice(0, 60)}</b></div>}
              </>
            ) : (
              <p className="intent-output-placeholder">Type text below, press <strong>Classify</strong>, or click a <strong>Try</strong> example — result appears here</p>
            )}
          </div>

          {/* ── Input ─────────────────────────────────────────────── */}
          <label style={{ marginTop: 12 }}>
            Test text
            <textarea value={manualText} onChange={(e) => setManualText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); classify(); } }}
              placeholder='Type here and press Enter or click Classify… e.g. "Can I get a coffee?"'
              style={{ minHeight: 70 }} />
          </label>
          {p.transcript && (
            <div className="speech-feed-row">
              <span>🎙 Live transcript:</span>
              <span className="speech-feed-text">{p.transcript.slice(0, 80)}{p.transcript.length > 80 ? "…" : ""}</span>
              <button className="mini-btn" onClick={useTranscript}>Use ↑</button>
            </div>
          )}
          <div className="btn-row">
            <button className="primary" onClick={classify}>🔍 Classify Intent</button>
            <button onClick={useTranscript} disabled={!p.transcript.trim()} title="Import live speech transcript">🎙 Use Speech</button>
            <button onClick={() => { setManualText(""); setManualResult(null); setClassifySource(null); }}>Clear</button>
          </div>
          {classifySource && <p className="hint-small" style={{ marginTop: 4 }}>✓ Classified from <strong>{classifySource}</strong> input</p>}

          {/* ── Supported intents with Try examples ───────────────── */}
          <div className="intent-pattern-grid">
            <div className="section-title" style={{ marginBottom: 8 }}><span>Quick Examples</span><small>click Try to auto-fill & classify</small></div>
            {Object.keys(INTENT_PATTERNS).map((intent) => (
              <div key={intent} className={`pattern-row ${ir?.intent === intent ? "active" : ""}`}>
                <span>{intent}</span>
                <button className="mini-btn" onClick={() => { const examples: Record<string, string> = { order_item: "Can I get a coffee please?", navigate_to: "Take me to the reception", ask_question: "What can you do?", cancel: "Cancel that please", greeting: "Hey Bonbon, hello!", emergency_help: "I need help, I fell down", thanks: "Thank you so much", status_check: "Who are you?", privacy: "Stop recording me" }; const ex = examples[intent] ?? ""; setManualText(ex); if (ex) setManualResult(classifyIntent(ex)); }}>Try</button>
              </div>
            ))}
          </div>
        </section>

        <div className="side-stack">
          <section className="panel">
            <div className="section-title"><span>Scene Context</span><small>from camera + detections</small></div>
            {!sc ? <p className="muted">Start the camera on the Perception tab to populate scene context.</p> : (
              <div className="scene-grid">
                <div className="scene-cell">
                  <span>Activity</span>
                  <b>{ACTIVITY_ICONS[sc.dominantActivity] ?? "⚪"} {sc.dominantActivity}</b>
                </div>
                <div className="scene-cell">
                  <span>Spatial</span>
                  <b>{SPATIAL_ICONS[sc.spatialContext] ?? "⚪"} {sc.spatialContext}</b>
                </div>
                <div className="scene-cell">
                  <span>Persons</span>
                  <b>👤 {sc.personCount}</b>
                </div>
                <div className="scene-cell">
                  <span>Proximity</span>
                  <b>📍 {sc.proximity}</b>
                </div>
                <div className="scene-cell">
                  <span>Crowded</span>
                  <b>{sc.isCrowded ? "🔴 yes" : "🟢 no"}</b>
                </div>
                <div className="scene-cell">
                  <span>Confidence</span>
                  <b>{Math.round(sc.confidence * 100)}%</b>
                </div>
                {sc.objects.length > 0 && (
                  <div className="scene-cell full-span">
                    <span>Objects</span>
                    <b>{sc.objects.join(", ")}</b>
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="panel">
            <div className="section-title"><span>Behavior Recommendation</span><small>rule-based engine</small></div>
            {!behaviorRecommendation ? <p className="muted">Classify an intent to see behavior recommendation.</p> : (
              <div className="behavior-card">
                <div className="behavior-name">{behaviorRecommendation.behavior}</div>
                <div className={`priority-badge p-${behaviorRecommendation.priority.toLowerCase()}`}>{behaviorRecommendation.priority}</div>
                {Object.keys(behaviorRecommendation.params).length > 0 && (
                  <div className="param-list">
                    {Object.entries(behaviorRecommendation.params).map(([k, v]) => <div key={k} className="kv-row"><span>{k}</span><b>{v}</b></div>)}
                  </div>
                )}
                <p className="hint-small">On the robot, this recommendation goes to SafetyCommandGate before any action is taken.</p>
              </div>
            )}
          </section>

          <section className="panel">
            <div className="section-title"><span>Episodic Memory</span><small>last {p.sceneHistory.length} scenes</small></div>
            <p className="hint-small">Scene snapshots are stored in FAISS (32-dim vectors) for similarity search. Shown here as a table.</p>
            {p.sceneHistory.length === 0 ? <p className="muted">No scene history yet. Start the camera.</p> : (
              <div className="memory-list">
                {p.sceneHistory.map((s, i) => (
                  <div key={i} className="memory-row">
                    <span className="mem-time">{s.time}</span>
                    <span className="mem-activity">{ACTIVITY_ICONS[s.activity] ?? "⚪"} {s.activity}</span>
                    <span>👤 {s.persons}</span>
                    <span className="mem-spatial">{s.spatial}</span>
                    <span>📦 {s.objects}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 5 — LANGUAGE & RESPONSE
// ══════════════════════════════════════════════════════════════════════════════
type ProviderPresetId = "ollama" | "deepseek" | "openai" | "gemini" | "groq" | "mistral" | "together" | "anthropic" | "custom";
interface ProviderPresetDef { label: string; icon: string; provider: LlmProvider; baseUrl: string; model: string; needsKey: boolean; note?: string }
const PROVIDER_PRESETS: Record<ProviderPresetId, ProviderPresetDef> = {
  ollama:    { label: "Local Ollama",   icon: "🖥",  provider: "ollama",            baseUrl: "http://127.0.0.1:11434",                                    model: "llama3.2:3b",                         needsKey: false, note: "Run: ollama serve && ollama pull llama3.2:3b" },
  deepseek:  { label: "DeepSeek",       icon: "🔷",  provider: "openai_compatible", baseUrl: "https://api.deepseek.com",                                   model: "deepseek-chat",                       needsKey: true,  note: "Free tier at platform.deepseek.com" },
  openai:    { label: "OpenAI",         icon: "🟢",  provider: "openai_compatible", baseUrl: "https://api.openai.com/v1",                                  model: "gpt-4o-mini",                         needsKey: true,  note: "Get key at platform.openai.com" },
  gemini:    { label: "Google Gemini",  icon: "💎",  provider: "openai_compatible", baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",    model: "gemini-2.0-flash",                    needsKey: true,  note: "🚀 Direct browser mode — no backend needed! Add API key → Run LLM. Free key: aistudio.google.com" },
  groq:      { label: "Groq",           icon: "⚡",  provider: "openai_compatible", baseUrl: "https://api.groq.com/openai/v1",                             model: "llama-3.3-70b-versatile",             needsKey: true,  note: "Free tier at console.groq.com" },
  mistral:   { label: "Mistral",        icon: "🌊",  provider: "openai_compatible", baseUrl: "https://api.mistral.ai/v1",                                  model: "mistral-small-latest",                needsKey: true,  note: "Get key at console.mistral.ai" },
  together:  { label: "Together AI",    icon: "🤝",  provider: "openai_compatible", baseUrl: "https://api.together.xyz/v1",                                model: "meta-llama/Llama-3-8b-chat-hf",       needsKey: true,  note: "Get key at api.together.ai" },
  anthropic: { label: "Anthropic",      icon: "🧠",  provider: "openai_compatible", baseUrl: "https://api.anthropic.com/v1",                               model: "claude-3-5-haiku-20241022",           needsKey: true,  note: "Use anthropic-to-openai proxy or AWS Bedrock" },
  custom:    { label: "Custom",         icon: "⚙",   provider: "openai_compatible", baseUrl: "",                                                           model: "",                                    needsKey: true },
};

function LanguageTab(p: TabProps) {
  const [preset, setPreset] = useState<ProviderPresetId>("deepseek");
  const [provider, setProvider] = useState<LlmProvider>("openai_compatible");
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com");
  const [model, setModel] = useState("deepseek-chat");
  const [apiKey, setApiKey] = useState("");
  const [prompt, setPrompt] = useState("Greet a hospital visitor who just arrived and explain how BonBon can help them.");
  const [response, setResponse] = useState("");
  const [latency, setLatency] = useState<number | null>(null);
  const [grounding, setGrounding] = useState<number | null>(null);
  const [safetyFlag, setSafetyFlag] = useState("");
  const [busy, setBusy] = useState(false);
  const [catalog, setCatalog] = useState<ProviderCatalogItem[]>([]);
  const [ragDocs, setRagDocs] = useState<string[]>([]);
  const [detectedLang, setDetectedLang] = useState("en");

  const HARM_WORDS = /\b(bomb|weapon|kill|hack|password|secret|bypass\s+safety|override\s+safety)\b/i;
  const ZH_RE = /[一-鿿]/; const MS_RE = /\b(nak|tolong|terima kasih|boleh|saya)\b/i;
  const detectLang = (t: string) => ZH_RE.test(t) ? "zh" : MS_RE.test(t) ? "ms" : "en";

  // Simulate RAG context from prompt keywords
  const computeRagDocs = (text: string) => {
    const docs: string[] = [];
    if (/coffee|tea|drink|menu|food/i.test(text)) docs.push("Menu: Coffee RM5, Tea RM3, Juice RM4, Water RM1");
    if (/navigation|go|move|where/i.test(text)) docs.push("Locations: Reception (L1), Canteen (L2), Ward A–D (L3)");
    if (/bonbon|robot|what|who/i.test(text)) docs.push("BonBon is a service robot for Sunway Medical Centre. It serves F&B, gives directions, and assists patients.");
    if (/safety|estop|emergency|stop/i.test(text)) docs.push("Safety rule: All motion commands require SafetyCommandGate approval. E-stop halts immediately.");
    if (!docs.length) docs.push("(No relevant RAG documents for this query)");
    setRagDocs(docs);
  };

  // Rule-based demo response for offline / no-key mode
  const generateDemoResponse = (text: string): string => {
    if (/greet|hello|welcome|visitor|patient|arrive/i.test(text)) return "Hello! Welcome to BonBon service. I can assist you with directions, food & beverage orders, and patient support. How may I help you today?";
    if (/coffee|tea|drink|order|food|menu|eat/i.test(text)) return "I'd be happy to take your order! Our menu includes Coffee (RM5), Tea (RM3), Juice (RM4), and Water (RM1). What would you like?";
    if (/direction|go|navigate|where|find|location|room|floor/i.test(text)) return "I can guide you anywhere in the facility. Reception is on Level 1, Canteen on Level 2, and Wards A–D on Level 3. Where would you like to go?";
    if (/help|assist|support|emergency|hurt|fell/i.test(text)) return "I'm here to help! I can take orders, give directions, or contact staff. For medical emergencies, I'll immediately notify the nearest nurse station.";
    if (/bonbon|robot|what|who|introduce|capability|do you/i.test(text)) return "I'm BonBon, an AI service robot at Sunway Medical Centre. I can serve food and beverages, guide visitors, assist patients, and communicate in English, Chinese, and Malay.";
    if (/safety|stop|halt|danger|estop/i.test(text)) return "Safety is my top priority. All motion commands pass through the Safety Supervisor. In any emergency I stop immediately and notify on-duty staff.";
    return "I understand your request. As BonBon I'm here to assist with orders, navigation, and patient support. Could you provide more detail so I can help you better?";
  };

  const api = p.api;

  useEffect(() => { if (!p.disabled) { api.providerCatalog().then((d) => setCatalog(d.providers)).catch(() => {}); } }, [p.disabled, api]);

  const switchPreset = (id: ProviderPresetId) => {
    setPreset(id);
    const p = PROVIDER_PRESETS[id];
    setProvider(p.provider);
    if (p.baseUrl) setBaseUrl(p.baseUrl);
    if (p.model) setModel(p.model);
  };

  // ── Direct Gemini browser call (no backend needed) ──────────────────────────
  const callGeminiDirect = async (promptText: string, key: string, mdl: string): Promise<{ text: string; latency: number }> => {
    const geminiModel = mdl || "gemini-2.0-flash";
    // Try native generateContent endpoint first (works with CORS)
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${geminiModel}:generateContent?key=${key}`;
    const t0 = performance.now();
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: promptText }] }],
        generationConfig: { maxOutputTokens: 512, temperature: 0.7 },
        safetySettings: [
          { category: "HARM_CATEGORY_DANGEROUS_CONTENT", threshold: "BLOCK_ONLY_HIGH" },
          { category: "HARM_CATEGORY_HARASSMENT",        threshold: "BLOCK_ONLY_HIGH" },
        ],
      }),
    });
    if (!resp.ok) {
      const errBody = await resp.text().catch(() => "");
      let friendly = `Gemini API error ${resp.status}`;
      if (resp.status === 400) friendly = "Gemini: invalid request or model name";
      else if (resp.status === 403) friendly = "Gemini: API key invalid or quota exceeded";
      else if (resp.status === 429) friendly = "Gemini: rate limit — wait a moment and retry";
      throw new Error(`${friendly}. ${errBody.slice(0, 120)}`);
    }
    const data = await resp.json() as { candidates?: { content: { parts: { text: string }[] } }[] };
    const text = data.candidates?.[0]?.content?.parts?.[0]?.text ?? "(empty response)";
    return { text, latency: Math.round(performance.now() - t0) };
  };

  const runPrompt = async () => {
    setBusy(true); setResponse(""); setSafetyFlag(""); setLatency(null);
    setDetectedLang(detectLang(prompt));
    computeRagDocs(prompt);
    if (HARM_WORDS.test(prompt)) { setSafetyFlag("BLOCKED — harmful content detected in prompt"); setBusy(false); return; }
    p.updateLocalOutput("llm", "warn", { provider, model, response_text: "Thinking…", safety_filter: "pending" });

    // ── Path A: Direct Gemini (no backend needed) ─────────────────────────────
    if (preset === "gemini" && apiKey.trim()) {
      try {
        const { text, latency: lat } = await callGeminiDirect(prompt, apiKey.trim(), model);
        const g = estimateGrounding(prompt, text);
        setResponse(text); setLatency(lat); setGrounding(g);
        setSafetyFlag(HARM_WORDS.test(text) ? "WARN — response flagged" : "PASSED");
        const payload = { provider: "gemini_direct", model, response_text: text, latency_ms: lat, safety_filter: "passed", grounding_score: g };
        p.updateLocalOutput("llm", "ok", payload);
        try { await api.updateClientOutput("llm", "ok", payload); } catch { /* optional sync */ }
        p.addLog("ok", `Gemini direct (${model}) responded in ${lat} ms`);
        setBusy(false);
        return;
      } catch (geminiErr) {
        const msg = geminiErr instanceof Error ? geminiErr.message : String(geminiErr);
        // Show the Gemini error and stop — don't fall through to demo
        setResponse(""); setSafetyFlag(`Gemini error: ${msg}`);
        p.updateLocalOutput("llm", "error", { provider: "gemini_direct", model, error: msg });
        p.addLog("error", `Gemini direct failed: ${msg}`);
        setBusy(false);
        return;
      }
    }

    // ── Path B: Backend API (requires robot/server running) ───────────────────
    try {
      const result = await api.llmTest({ provider, base_url: baseUrl, model, prompt, api_key: apiKey || undefined, timeout_sec: 60 });
      const g = estimateGrounding(prompt, result.response_text);
      setResponse(result.response_text); setLatency(result.latency_ms); setGrounding(g);
      setSafetyFlag(HARM_WORDS.test(result.response_text) ? "WARN — response flagged" : "PASSED");
      const payload = { provider: result.provider, model: result.model, response_text: result.response_text, latency_ms: result.latency_ms, safety_filter: "passed", grounding_score: g };
      p.updateLocalOutput("llm", "ok", payload);
      await api.updateClientOutput("llm", "ok", payload);
      await p.refreshTestbench();
      p.addLog("ok", `LLM (${result.provider}/${result.model}) responded in ${result.latency_ms} ms`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      const isOffline = /unavailable|connection|refused|network|ECONNREFUSED|fetch/i.test(msg);
      if (isOffline) {
        const demoResp = generateDemoResponse(prompt);
        setResponse(demoResp);
        setLatency(null);
        setGrounding(estimateGrounding(prompt, demoResp));
        setSafetyFlag("⚠ LLM offline — rule-based demo response (select Gemini + add API key for live responses)");
        p.updateLocalOutput("llm", "warn", { provider, model, response_text: demoResp, safety_filter: "demo_mode" });
        p.addLog("warn", "LLM offline — showing rule-based demo response");
      } else {
        setResponse(`Error: ${msg}`); setSafetyFlag("ERROR");
        p.updateLocalOutput("llm", "error", { provider, model, error: msg });
        p.addLog("error", `LLM failed: ${msg}`);
      }
    } finally { setBusy(false); }
  };

  return (
    <div className="tab-body">
      <div className="section-hero"><h2>💬 Language & Response</h2><p>LLM inference (Ollama local / DeepSeek / OpenAI-compatible) with RAG context injection, safety filtering, hallucination guard, and personality layer.</p></div>
      <div className="grid two">
        <section className="panel">
          <div className="section-title"><span>LLM Test</span><small>Ollama · OpenAI · Gemini · DeepSeek · Groq · Mistral · more</small></div>

          {/* ── Provider preset grid ──────────────────────────────── */}
          <div className="provider-preset-grid">
            {(Object.entries(PROVIDER_PRESETS) as [ProviderPresetId, ProviderPresetDef][]).map(([id, def]) => (
              <button key={id} className={`provider-chip ${preset === id ? "selected" : ""}`} onClick={() => switchPreset(id)}>
                <span>{def.icon}</span>
                <strong>{def.label}</strong>
              </button>
            ))}
          </div>
          {PROVIDER_PRESETS[preset].note && (
            <p className="provider-note">ℹ {PROVIDER_PRESETS[preset].note}</p>
          )}

          {/* ── Editable fields (auto-filled by preset) ─────────── */}
          <div className="two-col" style={{ marginTop: 10 }}>
            <label>Model<input value={model} onChange={(e) => setModel(e.target.value)} placeholder="model name" /></label>
            <label>API key<input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={provider === "ollama" ? "not required" : "paste key (never saved)"} /></label>
          </div>
          <label>Base URL<input value={baseUrl} onChange={(e) => { setBaseUrl(e.target.value); setPreset("custom"); }} placeholder="https://api.example.com/v1" /></label>
          <label style={{ marginTop: 10 }}>Prompt
            <textarea value={prompt} onChange={(e) => { setPrompt(e.target.value); computeRagDocs(e.target.value); }} style={{ minHeight: 100 }} />
          </label>
          {preset === "gemini" && apiKey.trim() && (
            <div className="gemini-direct-badge">⚡ Gemini Direct Mode — calls Google API directly from browser (no robot/backend needed)</div>
          )}
          <div className="btn-row">
            <button className="primary" onClick={() => void runPrompt()} disabled={busy || (!p.token && preset !== "gemini") || (!apiKey.trim() && preset === "gemini")}>
              {busy ? "⌛ Thinking…" : preset === "gemini" && apiKey.trim() ? "▶ Run Gemini" : "▶ Run LLM"}
            </button>
            <button onClick={() => setApiKey("")}>Clear key</button>
          </div>
          <div className="llm-response">
            <div><strong>Response</strong><div style={{ display: "flex", gap: 8 }}>{latency !== null && <span className="latency-badge">{latency} ms</span>}{grounding !== null && <span className="grounding-badge">ground {Math.round(grounding * 100)}%</span>}</div></div>
            <p>{response || "No response yet. Click ▶ Run LLM — works offline with demo responses when no provider is configured."}</p>
          </div>
          {safetyFlag.startsWith("⚠ LLM offline") && (
            <div className="llm-offline-guide">
              <strong>💡 Select a provider above and add an API key to get live responses:</strong>
              <ul>
                <li><b>Groq</b> — fastest, free tier, select ⚡ Groq above</li>
                <li><b>Gemini</b> — free tier at aistudio.google.com, select 💎 Google Gemini</li>
                <li><b>Ollama</b> — fully local/offline, run <code>ollama serve</code> + <code>ollama pull llama3.2:3b</code></li>
                <li><b>DeepSeek / OpenAI / Mistral / Together</b> — paste API key in the field above</li>
              </ul>
              <span>Demo responses are rule-based and safe — they show how the personality layer works without any LLM.</span>
            </div>
          )}
        </section>

        <div className="side-stack">
          <section className="panel">
            <div className="section-title"><span>RAG Context</span><small>retrieved documents</small></div>
            <p className="hint-small">Documents retrieved from ChromaDB / FAISS for the current prompt (simulated in browser, real on robot).</p>
            {ragDocs.map((doc, i) => <div key={i} className="rag-doc">📄 {doc}</div>)}
          </section>

          <section className="panel">
            <div className="section-title"><span>Safety Filter</span></div>
            <div className={`safety-filter-banner ${safetyFlag.startsWith("PASS") ? "good" : safetyFlag.startsWith("BLOCK") ? "danger" : safetyFlag === "WARN — response flagged" ? "warn" : "idle"}`}>
              {safetyFlag || "Not run yet"}
            </div>
            <div className="capability-note" style={{ marginTop: 10 }}>
              <div className="cap-row"><span>Input filter</span><b className="cap-robot">Harm keyword detection</b></div>
              <div className="cap-row"><span>Output filter</span><b className="cap-robot">Safety keyword blocklist</b></div>
              <div className="cap-row"><span>Hallucination</span><b className="cap-robot">Confidence + grounding score</b></div>
              <div className="cap-row"><span>Fallback</span><b className="cap-robot">Static safe-response template</b></div>
            </div>
          </section>

          <section className="panel">
            <div className="section-title"><span>Personality Layer</span><small>bonbon_llm/personality_layer.py</small></div>
            <div className="kv-row"><span>Detected language</span><b>{detectedLang === "zh" ? "🇨🇳 Chinese" : detectedLang === "ms" ? "🇲🇾 Malay" : "🇬🇧 English"}</b></div>
            <div className="kv-row"><span>Response length cap</span><b>280 chars (TTS optimised)</b></div>
            <div className="kv-row"><span>Markdown stripping</span><b>✓ (bold/italic/bullets removed)</b></div>
            <div className="kv-row"><span>Affirmations</span><b>Random ("Of course!", "Sure!"…)</b></div>
            <div className="kv-row"><span>Robot name</span><b>BonBon (injected if missing)</b></div>
            {response && <div className="personality-output"><strong>Processed output:</strong><p>{response.slice(0, 280).replace(/[*_`#>]/g, "").replace(/^\d+\.\s*/gm, "").trim()}{response.length > 280 ? "…" : ""}</p></div>}
          </section>

          <section className="panel">
            <div className="section-title"><span>Provider Catalog</span></div>
            {catalog.length === 0 ? <p className="muted">Log in to load provider catalog.</p> : (
              <div>{catalog.map((c) => <div key={c.id} className="kv-row"><span>{c.label}</span><b>{c.default_model}</b></div>)}</div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 6 — TTS
// ══════════════════════════════════════════════════════════════════════════════
function TTSTab(p: TabProps) {
  const [ttsText, setTtsText] = useState("Hello, I am BonBon. How can I help you today?");
  const [language, setLanguage] = useState("en");
  const [priority, setPriority] = useState("normal");
  const [lastMetrics, setLastMetrics] = useState<{ latency: number; chars: number; backend: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [cmdResult, setCmdResult] = useState<{ ok: boolean; msg: string } | null>(null);

  // ── Browser-native speech synthesis ────────────────────────────────────────
  const browserSpeak = (text: string) => {
    if (!text.trim()) return;
    const synth = window.speechSynthesis;
    if (!synth) { setCmdResult({ ok: false, msg: "Web Speech API not supported in this browser" }); return; }
    synth.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = language === "zh" ? "zh-CN" : language === "ms" ? "ms-MY" : "en-US";
    const RATE: Record<string, number> = { neutral: 1.0, happy: 1.08, excited: 1.18, calm: 0.91, sad: 0.83, urgent: 1.25, friendly: 1.0, angry: 1.14, whisper: 0.87 };
    const PITCH: Record<string, number> = { neutral: 1.0, happy: 1.15, excited: 1.25, calm: 0.9, sad: 0.8, urgent: 1.0, friendly: 1.1, angry: 0.85, whisper: 0.7 };
    utter.rate = RATE[p.ttsEmotion] ?? 1.0;
    utter.pitch = PITCH[p.ttsEmotion] ?? 1.0;
    const t0 = performance.now();
    utter.onstart = () => { setSpeaking(true); setCmdResult({ ok: true, msg: `🔊 Browser TTS playing (${p.ttsEmotion}, ${language}) — Web Speech API` }); };
    utter.onend = () => {
      setSpeaking(false);
      const lat = Math.round(performance.now() - t0);
      setLastMetrics({ latency: lat, chars: text.length, backend: "browser_speech_api" });
      p.updateLocalOutput("tts", "ok", { current_text: text, emotion: p.ttsEmotion, latency_ms: lat, is_speaking: false, backend: "browser_speech_api" });
      p.addLog("ok", `Browser TTS complete (${p.ttsEmotion}) — ${lat} ms`);
    };
    utter.onerror = (e) => { setSpeaking(false); setCmdResult({ ok: false, msg: `Speech error: ${e.error}` }); };
    synth.speak(utter);
  };

  // ── Robot Piper TTS ─────────────────────────────────────────────────────────
  const speak = async () => {
    if (!ttsText.trim()) return;
    // Try browser TTS first for instant feedback
    browserSpeak(ttsText);
    if (!p.token) return;   // no robot connection — browser only
    setBusy(true);
    const t0 = performance.now();
    try {
      await p.speakWithEmotion(ttsText, p.ttsEmotion);
      const lat = Math.round(performance.now() - t0);
      setLastMetrics({ latency: lat, chars: ttsText.length, backend: "piper" });
      setCmdResult({ ok: true, msg: `✓ Piper TTS queued on robot  (emotion: ${p.ttsEmotion}, ${lat} ms)` });
      const payload = { current_text: ttsText, emotion: p.ttsEmotion, latency_ms: lat, is_speaking: true, queue_depth: 1, backend: "piper" };
      p.updateLocalOutput("tts", "ok", payload);
      if (p.sessionId) await p.api.appendSessionEvent(p.sessionId, { module: "tts", event_type: "speak_with_emotion", status: "pass", summary: `TTS (${p.ttsEmotion}) accepted`, metrics: { latency_ms: lat }, payload: { text_chars: ttsText.length, emotion: p.ttsEmotion } });
      await p.refreshTestbench();
      p.addLog("ok", `TTS sent to robot (${p.ttsEmotion}, ${language}) — ${lat} ms`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      p.addLog("warn", `Robot TTS unavailable (${msg}) — audio playing via browser`);
    } finally { setBusy(false); }
  };

  return (
    <div className="tab-body">
      <div className="section-hero"><h2>🔊 Text-to-Speech</h2><p>Piper neural TTS (offline ONNX) with emotion-aware speech rate, multilingual voice profiles, and filler sounds.</p></div>
      <div className="grid two">
        <section className="panel">
          <div className="section-title"><span>Speak Command</span><small>via SafetyCommandGate</small></div>
          <label>Text to speak
            <textarea value={ttsText} onChange={(e) => setTtsText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); browserSpeak(ttsText); } }}
              placeholder="Type text and press Enter to hear it immediately…"
              style={{ minHeight: 100 }} />
          </label>
          <div className="tts-hint">⌨ Press <kbd>Enter</kbd> to speak instantly via browser · <kbd>Shift+Enter</kbd> for new line</div>
          <div className="two-col" style={{ marginTop: 10 }}>
            <label>Language<select value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="en">English (en)</option>
              <option value="zh">Chinese (zh)</option>
              <option value="ms">Malay (ms)</option>
            </select></label>
            <label>Priority<select value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="emergency">Emergency</option>
              <option value="low">Low</option>
              <option value="background">Background</option>
            </select></label>
          </div>
          <div className="btn-row">
            <button className="primary" onClick={() => browserSpeak(ttsText)} disabled={!ttsText.trim() || speaking}>
              {speaking ? "🔊 Speaking…" : `🔊 Speak Now (${p.ttsEmotion})`}
            </button>
            {speaking && <button className="danger" onClick={() => { window.speechSynthesis?.cancel(); setSpeaking(false); }}>⏹ Stop</button>}
            <button onClick={() => void speak()} disabled={p.disabled || busy || !ttsText.trim()} title="Also queue on robot Piper TTS">{busy ? "⌛" : "🤖 + Robot"}</button>
          </div>
          {cmdResult && <div className={`cmd-result ${cmdResult.ok ? "ok" : "error"}`}>{cmdResult.msg}</div>}
          {lastMetrics && (
            <div className="tts-metrics">
              <Metric label="Latency" value={`${lastMetrics.latency} ms`} />
              <Metric label="Characters" value={String(lastMetrics.chars)} />
              <Metric label="Est. duration" value={`~${(lastMetrics.chars * 0.065).toFixed(1)} s`} />
              <Metric label="Backend" value={lastMetrics.backend} />
            </div>
          )}
          <div className="capability-note" style={{ marginTop: 14 }}>
            <div className="cap-row"><span>Engine</span><b className="cap-robot">Piper (ONNX, offline)</b></div>
            <div className="cap-row"><span>Mode</span><b className="cap-robot">subprocess or Python API</b></div>
            <div className="cap-row"><span>Latency</span><b className="cap-robot">50–150 ms</b></div>
            <div className="cap-row"><span>Filler sounds</span><b className="cap-robot">auto while LLM thinks</b></div>
          </div>
        </section>

        <div className="side-stack">
          <section className="panel">
            <div className="section-title"><span>Emotion Selector</span><small>affects Piper length_scale</small></div>
            <div className="emotion-grid">
              {EMOTIONS.map((em) => (
                <button key={em} className={`emotion-btn ${p.ttsEmotion === em ? "selected" : ""}`} onClick={() => p.setTtsEmotion(em)}>
                  <span>{EMOTION_ICON[em]}</span>
                  <strong>{em}</strong>
                  <small>{EMOTION_SPEED[em]}</small>
                </button>
              ))}
            </div>
            <p className="hint-small">Speed multiplier adjusts Piper <code>length_scale</code>. Urgent = 1.25× faster. Sad = 0.83× slower.</p>
          </section>

          <section className="panel">
            <div className="section-title"><span>Voice Profiles</span><small>multilingual Piper models</small></div>
            {[["English", "en_US-lessac-medium", "Medium quality, general use"], ["Chinese", "zh_CN-huayan-medium", "Mandarin Chinese"], ["Malay", "ms_MY-custom-medium", "Bahasa Malaysia"]].map(([lang, model, desc]) => (
              <div key={lang} className={`voice-profile ${language === model.slice(0, 2) ? "active" : ""}`}>
                <strong>{lang}</strong><span>{model}</span><small>{desc}</small>
              </div>
            ))}
          </section>

          <section className="panel">
            <div className="section-title"><span>TTS Live Status</span></div>
            {[["Speaking", asBool(p.liveStatus.tts.is_speaking) ? "yes" : "no"], ["Current text", asText(p.liveStatus.tts.current_text, "none")], ["Queue depth", asText(p.liveStatus.tts.queue_depth, "0")], ["Last latency", `${asText(p.liveStatus.tts.last_latency_ms, "—")} ms`], ["Backend", asText(p.liveStatus.tts.backend, "piper")]].map(([k, v]) => <div key={k} className="kv-row"><span>{k}</span><b>{v}</b></div>)}
          </section>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 7 — SAFETY
// ══════════════════════════════════════════════════════════════════════════════
function SafetyTab(p: TabProps) {
  const [navX, setNavX] = useState("2.0"); const [navY, setNavY] = useState("1.5");
  const [busy, setBusy] = useState(false);
  const [cmdResult, setCmdResult] = useState<{ ok: boolean; label: string } | null>(null);

  const sendCmd = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true); setCmdResult(null);
    try { await fn(); setCmdResult({ ok: true, label }); p.addLog("ok", `${label} accepted`); await p.refreshTestbench(); }
    catch (e) { setCmdResult({ ok: false, label }); p.addLog("error", `${label} failed: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  };

  const currentIdx = FSM_STATES.indexOf(p.safetyLevel);

  return (
    <div className="tab-body">
      <div className="section-hero"><h2>🛡 Safety System</h2><p>7-level Safety State Machine, E-stop, Watchdog, Velocity Gate, and Policy Actions. Every command passes through SafetyCommandGate.</p></div>
      <section className="panel" style={{ marginBottom: 18 }}>
        <div className="section-title"><span>Safety State Machine</span><small>current: <strong style={{ color: `var(--${FSM_TONES[p.safetyLevel]})` }}>{p.safetyLevel}</strong></small></div>
        <div className="fsm-flow">
          {FSM_STATES.map((state, idx) => (
            <div key={state} className="fsm-step-wrap">
              <button className={`fsm-node ${FSM_TONES[state]} ${idx === currentIdx ? "fsm-current" : ""}`} onClick={() => p.setSafetyLevel(state)}>
                <strong>{state}</strong>
                <small>{FSM_DESC[state]}</small>
              </button>
              {idx < FSM_STATES.length - 1 && <div className="fsm-arrow">›</div>}
            </div>
          ))}
        </div>
        <div className="fsm-desc-banner">
          <span className={FSM_TONES[p.safetyLevel]}>{FSM_DESC[p.safetyLevel]}</span>
          <span>Click a state to simulate (local only — does not change robot state)</span>
        </div>
      </section>

      <div className="grid two">
        <div className="side-stack">
          <section className="panel">
            <div className="section-title"><span>System Status</span></div>
            <div className="safety-gauges">
              <div className="gauge-row"><span>Battery</span><div className="gauge-bar"><div style={{ width: `${asNumber(p.liveStatus.safety.battery_pct)}%`, background: asNumber(p.liveStatus.safety.battery_pct) < 20 ? "var(--danger)" : "var(--glow)" }} /></div><b>{asNumber(p.liveStatus.safety.battery_pct)}%</b></div>
            </div>
            {[["Watchdog", asBool(p.liveStatus.safety.watchdog_ok) ? "✓ OK" : "⚠ Not reported"], ["Motors", asBool(p.liveStatus.safety.motors_enabled) ? "✓ Enabled" : "✗ Disabled"], ["Active faults", asText(p.liveStatus.safety.active_faults, "none")], ["Robot", p.robotOnline ? "✓ Online" : "⚠ Offline/sim"], ["WS link", p.wsStatus]].map(([k, v]) => <div key={k} className="kv-row"><span>{k}</span><b>{v}</b></div>)}
          </section>

          <section className="panel">
            <div className="section-title"><span>Policy Actions</span><small>triggered at each safety level</small></div>
            {[["CAUTION", "announce_audio, update_led_eyes"], ["DEGRADED", "cap_velocity, update_display"], ["FAULT", "zero_velocity, notify_operator"], ["DANGER", "trigger_estop, request_human_help"], ["SAFE_STOP", "disable_actuation, log_incident"]].map(([level, actions]) => (
              <div key={level} className={`policy-row ${p.safetyLevel === level ? "active" : ""}`}><strong>{level}</strong><span>{actions}</span></div>
            ))}
          </section>
        </div>

        <div className="side-stack">
          <section className="panel">
            <div className="section-title"><span>Safety Commands</span><small>all gated by SafetyCommandGate</small></div>
            <button className="danger full-w" disabled={busy || p.disabled} onClick={() => void sendCmd("E-STOP", () => p.api.emergencyStop("operator dashboard"))}>🛑 EMERGENCY STOP</button>
            <div className="btn-row" style={{ marginTop: 12 }}>
              <button disabled={busy || p.disabled} onClick={() => void sendCmd("Pause", () => p.api.pauseNavigation())}>⏸ Pause Nav</button>
              <button disabled={busy || p.disabled} onClick={() => void sendCmd("Resume", () => p.api.resumeNavigation())}>▶ Resume Nav</button>
              <button disabled={busy || p.disabled} onClick={() => void sendCmd("Dock", () => p.api.dock())}>⚡ Dock</button>
            </div>
            <p className="hint-small" style={{ marginTop: 12 }}>Commands go through SafetyCommandGate. If safety state is FAULT/DANGER, navigation commands are rejected.</p>
            {cmdResult && <div className={`cmd-result ${cmdResult.ok ? "ok" : "error"}`}>{cmdResult.ok ? `✓ ${cmdResult.label} accepted` : `✗ ${cmdResult.label} failed`}</div>}
          </section>

          <section className="panel">
            <div className="section-title"><span>Navigate to Pose</span><small>Nav2 / AMCL</small></div>
            <div className="two-col">
              <label>Goal X (m)<input value={navX} onChange={(e) => setNavX(e.target.value)} type="number" step="0.5" /></label>
              <label>Goal Y (m)<input value={navY} onChange={(e) => setNavY(e.target.value)} type="number" step="0.5" /></label>
            </div>
            <div className="btn-row" style={{ marginTop: 10 }}>
              <button className="primary" disabled={busy || p.disabled || !["NORMAL", "CAUTION"].includes(p.safetyLevel)} onClick={() => void sendCmd("Navigate", () => p.api.navigate(+navX, +navY))}>🗺 Send Navigation Goal</button>
              <button disabled={busy || p.disabled} onClick={() => void sendCmd("Cancel", () => p.api.cancelTask())}>✕ Cancel</button>
            </div>
            {!["NORMAL", "CAUTION"].includes(p.safetyLevel) && <p className="danger-hint">⚠ Navigation disabled — safety state is {p.safetyLevel}</p>}
            {cmdResult && cmdResult.label === "Navigate" && <div className={`cmd-result ${cmdResult.ok ? "ok" : "error"}`}>{cmdResult.ok ? `✓ Navigation goal sent to Nav2` : `✗ Navigate failed — check safety state`}</div>}
          </section>

          <section className="panel">
            <div className="section-title"><span>Navigation Status</span></div>
            {[["Nav state", asText(p.liveStatus.system.active_task, "idle")], ["Localization", "AMCL"], ["Planner", "Nav2 NavFn"], ["Human costmap", "enabled (3× inflate near persons)"]].map(([k, v]) => <div key={k} className="kv-row"><span>{k}</span><b>{v}</b></div>)}
          </section>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 8 — SYSTEM
// ══════════════════════════════════════════════════════════════════════════════
function SystemTab(p: TabProps) {
  const [sysData, setSysData] = useState<Record<string, unknown> | null>(null);
  const [title, setTitle] = useState("BonBon dashboard validation"); const [scenario, setScenario] = useState("manual_localhost_test"); const [notes, setNotes] = useState("");
  const [eventStatus, setEventStatus] = useState<SessionEventStatus>("pass"); const [moduleName, setModuleName] = useState("integration"); const [failLabel, setFailLabel] = useState("");
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);

  const load = async (kind: "status" | "diagnostics") => {
    try { const r = kind === "status" ? await p.api.robotStatus() : await p.api.diagnostics(); setSysData(r); p.addLog("ok", `Loaded ${kind}`); } catch (e) { p.addLog("error", `${kind}: ${e instanceof Error ? e.message : String(e)}`); }
  };

  // Auto-load robot status when the tab becomes accessible (user logs in)
  useEffect(() => {
    if (p.disabled) return;
    void p.api.robotStatus().then((r) => setSysData(r)).catch(() => {});
  }, [p.disabled]); // eslint-disable-line react-hooks/exhaustive-deps

  const startSession = async () => {
    try { const s = await p.api.startSession({ title, scenario, operator_notes: notes }); p.setSessionId(s.session_id); setAnalysis(s.analysis ?? {}); p.addLog("ok", `Session started: ${s.session_id.slice(0, 8)}`); }
    catch (e) { p.addLog("error", `Session: ${e instanceof Error ? e.message : String(e)}`); }
  };
  const addEvent = async () => {
    if (!p.sessionId) { p.addLog("warn", "Start a session first"); return; }
    try {
      await p.api.appendSessionEvent(p.sessionId, { module: moduleName, event_type: "manual_validation", status: eventStatus, summary: `${moduleName} marked ${eventStatus}`, metrics: { ts: Date.now() }, payload: { snapshot: p.liveStatus[moduleName as keyof TestbenchStatus] ?? {} }, failure_label: failLabel });
      const a = await p.api.analyseSession(p.sessionId); setAnalysis(a); p.addLog(eventStatus === "fail" ? "warn" : "ok", `Recorded ${moduleName} ${eventStatus}`);
    } catch (e) { p.addLog("error", String(e)); }
  };

  return (
    <div className="tab-body">
      <div className="section-hero"><h2>⚙ System & Sessions</h2><p>Robot diagnostics, WebSocket connection, and the training/testing improvement loop for recording and labelling module test events.</p></div>
      <div className="grid two">
        <div className="side-stack">
          <section className="panel">
            <div className="section-title"><span>System Vitals</span></div>
            <div className="metric-grid-4">
              <Metric label="Robot" value={p.robotOnline ? "online" : "offline"} />
              <Metric label="Backend" value={p.backendStatus} />
              <Metric label="WS" value={p.wsStatus} />
              <Metric label="Safety" value={p.safetyLevel} />
            </div>
            <div className="btn-row" style={{ marginTop: 12 }}>
              <button className="primary" onClick={() => void load("status")} disabled={p.disabled}>Robot status</button>
              <button onClick={() => void load("diagnostics")} disabled={p.disabled}>Diagnostics</button>
              <button onClick={() => void p.checkBackend()}>Ping backend</button>
              <button onClick={p.connectWs} disabled={p.wsStatus === "connected"}>Connect WS</button>
            </div>
            <pre className="json-view">{sysData ? JSON.stringify(sysData, null, 2) : "No data loaded."}</pre>
          </section>

          <section className="panel">
            <div className="section-title"><span>Live Module Status</span></div>
            {(["speech", "vision", "llm", "tts", "safety", "system"] as (keyof TestbenchStatus)[]).map((mod) => (
              <div key={mod} className="module-status-row">
                <span className="mod-name">{mod}</span>
                <span className={`mod-status-badge ${String(p.liveStatus[mod].status ?? "idle")}`}>{String(p.liveStatus[mod].status ?? "idle")}</span>
                <span className="mod-updated">{p.liveStatus[mod].updated_at ? new Date((p.liveStatus[mod].updated_at as number) * 1000).toLocaleTimeString() : "—"}</span>
              </div>
            ))}
          </section>
        </div>

        <div className="side-stack">
          <section className="panel">
            <div className="section-title"><span>Test Session</span><small>record · label · regress</small></div>
            <label>Session title<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
            <div className="two-col" style={{ marginTop: 8 }}>
              <label>Scenario<input value={scenario} onChange={(e) => setScenario(e.target.value)} /></label>
              <label>Active session<input value={p.sessionId || "none"} readOnly /></label>
            </div>
            <label>Notes<textarea value={notes} onChange={(e) => setNotes(e.target.value)} style={{ minHeight: 60 }} placeholder="What are we testing?" /></label>
            <div className="btn-row"><button className="primary" disabled={p.disabled} onClick={() => void startSession()}>Start session</button></div>
            <div className="two-col" style={{ marginTop: 12 }}>
              <label>Module<select value={moduleName} onChange={(e) => setModuleName(e.target.value)}><option>speech</option><option>vision</option><option>llm</option><option>tts</option><option>system</option><option>safety</option><option>integration</option></select></label>
              <label>Result<select value={eventStatus} onChange={(e) => setEventStatus(e.target.value as SessionEventStatus)}><option value="pass">pass</option><option value="fail">fail</option><option value="warn">warn</option><option value="info">info</option></select></label>
            </div>
            <label>Failure label<input value={failLabel} onChange={(e) => setFailLabel(e.target.value)} placeholder="e.g. low_light_false_negative" /></label>
            <div className="btn-row"><button disabled={p.disabled || !p.sessionId} onClick={() => void addEvent()}>Record event</button></div>
            <pre className="json-view compact">{analysis ? JSON.stringify(analysis, null, 2) : "Analysis appears after events."}</pre>
          </section>

          <section className="panel">
            <div className="section-title"><span>Event Console</span><small>{p.logs.length} events</small></div>
            <div className="log-list">
              {p.logs.length === 0 ? <p className="muted">No events yet.</p> : p.logs.map((e, i) => (
                <div className={`log-line ${e.level}`} key={i}><span>{e.time}</span><strong>{e.level.toUpperCase()}</strong><p>{e.text}</p></div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// SHARED COMPONENTS
// ══════════════════════════════════════════════════════════════════════════════
function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

// ══════════════════════════════════════════════════════════════════════════════
// PURE LOGIC — Text Emotion (mirrors bonbon_affective_ai/text_emotion_analyzer.py)
// ══════════════════════════════════════════════════════════════════════════════
const EMERGENCY_KEYWORDS = ["help", "emergency", "fallen", "fall", "pain", "hurt", "call nurse", "call doctor", "heart attack", "can't breathe", "fire", "danger"];
const DISTRESS_KEYWORDS = ["scared", "afraid", "worried", "anxious", "panic", "lost", "confused", "dizzy", "nausea"];
const NEGATIVE_PATTERNS: Record<string, RegExp> = {
  sadness:  /\b(sad|unhappy|depressed|lonely|miss|grief|cry|tears|sorrow)\b/i,
  anger:    /\b(angry|furious|mad|outraged|annoyed|frustrated|upset|hate|rage)\b/i,
  fear:     /\b(scared|afraid|fear|frightened|terrified|worried|anxious|nervous)\b/i,
  disgust:  /\b(disgusted|gross|horrible|awful|disgusting|nasty|repulsive)\b/i,
};
const POSITIVE_PATTERNS: Record<string, RegExp> = {
  joy:      /\b(happy|glad|excited|wonderful|great|fantastic|love|joy|amazing|excellent)\b/i,
  surprise: /\b(wow|omg|oh my|really|seriously|unbelievable|incredible|unexpected)\b/i,
};
type TextEmotion = { dominant: string; confidence: number; isEmergency: boolean; isDistress: boolean; scores: Record<string, number> };
function analyzeTextEmotion(text: string): TextEmotion {
  if (!text.trim()) return { dominant: "neutral", confidence: 0.5, isEmergency: false, isDistress: false, scores: { neutral: 1 } };
  const lower = text.toLowerCase();
  const isEmergency = EMERGENCY_KEYWORDS.some((kw) => lower.includes(kw));
  const isDistress = DISTRESS_KEYWORDS.some((kw) => lower.includes(kw));
  if (isEmergency) return { dominant: "emergency", confidence: 0.97, isEmergency: true, isDistress: true, scores: { emergency: 1 } };
  const scores: Record<string, number> = { neutral: 0.3 };
  for (const [em, pat] of Object.entries(NEGATIVE_PATTERNS)) if (pat.test(text)) scores[em] = (scores[em] ?? 0) + 0.65;
  for (const [em, pat] of Object.entries(POSITIVE_PATTERNS)) if (pat.test(text)) scores[em] = (scores[em] ?? 0) + 0.65;
  if (isDistress) scores["distress"] = (scores["distress"] ?? 0) + 0.7;
  const total = Object.values(scores).reduce((a, b) => a + b, 0) || 1;
  const norm: Record<string, number> = {}; for (const [k, v] of Object.entries(scores)) norm[k] = +(v / total).toFixed(2);
  const dominant = Object.entries(norm).sort((a, b) => b[1] - a[1])[0];
  return { dominant: dominant[0], confidence: dominant[1], isEmergency, isDistress, scores: norm };
}

// ══════════════════════════════════════════════════════════════════════════════
// PURE LOGIC — Emotion Fusion (mirrors EmotionFusionEngine)
// ══════════════════════════════════════════════════════════════════════════════
const FUSION_WEIGHTS = { face: 0.40, voice: 0.35, text: 0.15, gesture: 0.10 };
const EMOTION_VALENCE: Record<string, number> = { joy: 1, happy: 1, excited: 0.8, surprise: 0.2, neutral: 0, calm: 0.2, sad: -0.8, sadness: -0.8, anger: -0.9, angry: -0.9, fear: -0.8, fearful: -0.8, disgust: -0.7, distress: -0.9, emergency: -1 };
const EMOTION_AROUSAL: Record<string, number> = { joy: 0.7, happy: 0.6, excited: 1, surprise: 0.8, neutral: 0, calm: -0.4, sad: -0.5, sadness: -0.5, anger: 0.9, angry: 0.9, fear: 0.8, fearful: 0.8, disgust: 0.4, distress: 0.9, emergency: 1 };
type FusionResult = { dominant: string; confidence: number; valence: number; arousal: number; behaviorHint: string };
function fuseEmotions(faceEm: string, faceCon: number, voiceEm: string, voiceCon: number, textEm: string, textCon: number): FusionResult {
  const weighted: Record<string, number> = {};
  const add = (em: string, con: number, w: number) => { if (em !== "none") weighted[em] = (weighted[em] ?? 0) + con * w; };
  add(faceEm, faceCon, FUSION_WEIGHTS.face);
  add(voiceEm, voiceCon, FUSION_WEIGHTS.voice);
  add(textEm, textCon, FUSION_WEIGHTS.text);
  if (!Object.keys(weighted).length) return { dominant: "neutral", confidence: 0.5, valence: 0, arousal: 0, behaviorHint: "maintain_current" };
  const sorted = Object.entries(weighted).sort((a, b) => b[1] - a[1]);
  const [dominant, score] = sorted[0];
  const total = sorted.reduce((s, [, v]) => s + v, 0);
  const conf = +(score / total).toFixed(2);
  const valence = EMOTION_VALENCE[dominant] ?? 0;
  const arousal = EMOTION_AROUSAL[dominant] ?? 0;
  let behaviorHint = "maintain_current";
  if (dominant === "emergency") behaviorHint = "alert_immediately";
  else if (dominant === "distress" || dominant === "fear" || dominant === "fearful") behaviorHint = "calm_approach";
  else if (dominant === "anger" || dominant === "angry") behaviorHint = "de-escalate";
  else if (dominant === "joy" || dominant === "happy" || dominant === "excited") behaviorHint = "engage_positively";
  else if (dominant === "sad" || dominant === "sadness") behaviorHint = "show_empathy";
  return { dominant, confidence: conf, valence, arousal, behaviorHint };
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 9 — AFFECTIVE AI
// ══════════════════════════════════════════════════════════════════════════════
const FACE_EMOTIONS = ["neutral", "happy", "sad", "angry", "surprised", "fearful", "disgusted"];
const VOICE_EMOTIONS = ["neutral", "happy", "sad", "angry", "fearful", "excited", "calm"];
const GESTURE_HINTS = ["none", "waving", "pointing", "thumbs_up", "stop_palm", "raised_hand"];

function EmotionBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="emo-bar-row">
      <span className="emo-bar-label">{label}</span>
      <div className="emo-bar-track"><div className="emo-bar-fill" style={{ width: `${Math.round(value * 100)}%`, background: color }} /></div>
      <span className="emo-bar-pct">{Math.round(value * 100)}%</span>
    </div>
  );
}

function AffectiveAITab(p: TabProps) {
  const [textInput, setTextInput] = useState("");
  const [textResult, setTextResult] = useState<TextEmotion | null>(null);
  const [faceSliders, setFaceSliders] = useState<Record<string, number>>({ neutral: 0.7, happy: 0.1, sad: 0.05, angry: 0.05, surprised: 0.05, fearful: 0.03, disgusted: 0.02 });
  const [voiceArousal, setVoiceArousal] = useState(0.2);
  const [voiceValence, setVoiceValence] = useState(0.3);
  const [gestureHint, setGestureHint] = useState("none");
  const [privacyMode, setPrivacyMode] = useState(false);
  const [liveMode, setLiveMode] = useState(false);
  const liveRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [tick, setTick] = useState(0);
  const [emotionLog, setEmotionLog] = useState<{ time: string; emotion: string; conf: number; source: string }[]>([]);

  // Text emotion — auto on typing
  useEffect(() => {
    if (!textInput.trim()) { setTextResult(null); return; }
    const t = setTimeout(() => {
      const r = analyzeTextEmotion(textInput);
      setTextResult(r);
    }, 300);
    return () => clearTimeout(t);
  }, [textInput]);

  // Live simulation tick
  useEffect(() => {
    if (!liveMode) { if (liveRef.current) clearInterval(liveRef.current); return; }
    liveRef.current = setInterval(() => setTick((n) => n + 1), 1800);
    return () => { if (liveRef.current) clearInterval(liveRef.current); };
  }, [liveMode]);

  useEffect(() => {
    if (!liveMode) return;
    const emotions = FACE_EMOTIONS;
    const dominant = emotions[Math.floor(Math.random() * emotions.length)];
    const conf = 0.45 + Math.random() * 0.5;
    setEmotionLog((prev) => [{ time: nowStr(), emotion: dominant, conf: +conf.toFixed(2), source: "face" }, ...prev].slice(0, 10));
  }, [tick, liveMode]);

  // Derived face emotion
  const faceDominant = Object.entries(faceSliders).sort((a, b) => b[1] - a[1])[0];
  const faceCon = faceDominant[1];
  const faceEm = privacyMode ? "none" : faceDominant[0];

  // Derived voice emotion from arousal/valence
  let voiceEm = "neutral", voiceCon = 0.6;
  if (voiceArousal > 0.6 && voiceValence > 0.4) { voiceEm = "excited"; voiceCon = 0.75; }
  else if (voiceArousal > 0.6 && voiceValence < -0.3) { voiceEm = "angry"; voiceCon = 0.7; }
  else if (voiceArousal < -0.3 && voiceValence < -0.3) { voiceEm = "sad"; voiceCon = 0.7; }
  else if (voiceArousal < -0.3 && voiceValence > 0.3) { voiceEm = "calm"; voiceCon = 0.65; }
  else if (voiceArousal > 0.4 && voiceValence < -0.5) { voiceEm = "fearful"; voiceCon = 0.65; }
  else if (voiceValence > 0.5) { voiceEm = "happy"; voiceCon = 0.68; }

  const textEm = textResult?.dominant ?? "neutral";
  const textCon = textResult?.confidence ?? 0.5;
  const fusion = fuseEmotions(faceEm, faceCon, voiceEm, voiceCon, textEm, textCon);

  const fusionColors: Record<string, string> = { joy: "#44f2a1", happy: "#44f2a1", excited: "#f2e44f", neutral: "#a0c4ff", sad: "#8090b0", sadness: "#8090b0", angry: "#f06060", anger: "#f06060", fearful: "#c080f0", fear: "#c080f0", distress: "#f0a060", disgust: "#80c080", emergency: "#ff4444", surprise: "#f0d060", calm: "#60d0c0" };
  const fColor = (em: string) => fusionColors[em] ?? "#a0c4ff";

  return (
    <div className="tab-body">
      <div className="section-hero">
        <h2>😊 Affective AI — Multi-Modal Emotion Recognition</h2>
        <p>Live testbench for <strong>bonbon_affective_ai</strong>. Combines face, voice, and text emotion signals into a fused state using weighted fusion (face 40 % · voice 35 % · text 15 % · gesture 10 %). All logic mirrors the Python package running on the robot.</p>
      </div>

      <div className="affective-grid">
        {/* ── Text Emotion ───────────────────────────────────── */}
        <section className="panel">
          <div className="section-title"><span>📝 Text Emotion Analyzer</span><small>TextEmotionAnalyzer.py</small></div>
          <label>Input text (speech transcript or typed)
            <textarea value={textInput} onChange={(e) => setTextInput(e.target.value)} placeholder="Type something… e.g. 'I'm feeling really scared and don't know what to do'" style={{ minHeight: 72 }} />
          </label>
          {textResult && (
            <div className={`emotion-result-card ${textResult.isEmergency ? "emergency" : textResult.dominant}`}>
              <div className="emotion-result-header">
                <span className="emotion-badge" style={{ background: fColor(textResult.dominant) }}>{textResult.dominant}</span>
                <span className="conf-pill">{Math.round(textResult.confidence * 100)}%</span>
                {textResult.isEmergency && <span className="emergency-tag">🚨 EMERGENCY</span>}
                {textResult.isDistress && !textResult.isEmergency && <span className="distress-tag">⚠ Distress</span>}
              </div>
              <div className="emo-bars">
                {Object.entries(textResult.scores).sort((a, b) => b[1] - a[1]).map(([em, val]) => (
                  <EmotionBar key={em} label={em} value={val} color={fColor(em)} />
                ))}
              </div>
            </div>
          )}
          <div className="try-examples">
            {["I'm so happy to see you!", "Help! I've fallen and I can't get up!", "I feel a bit sad today.", "I'm absolutely furious!", "Wow that was unexpected!"].map((ex) => (
              <button key={ex} className="example-chip" onClick={() => setTextInput(ex)}>{ex.slice(0, 28)}…</button>
            ))}
          </div>
        </section>

        {/* ── Face Emotion ───────────────────────────────────── */}
        <section className="panel">
          <div className="section-title">
            <span>😐 Face Emotion Simulator</span>
            <small>DeepFace backend mock</small>
            <label className="privacy-toggle" style={{ marginLeft: "auto" }}>
              <input type="checkbox" checked={privacyMode} onChange={(e) => setPrivacyMode(e.target.checked)} />
              Privacy mode
            </label>
          </div>
          {privacyMode ? (
            <div className="privacy-banner">🔒 Privacy mode ON — face analysis suppressed. No emotion data will be published.</div>
          ) : (
            <>
              <div className="emo-bars" style={{ marginBottom: 10 }}>
                {FACE_EMOTIONS.map((em) => (
                  <div key={em} className="emo-slider-row">
                    <span className="emo-bar-label">{em}</span>
                    <input type="range" min={0} max={100} value={Math.round((faceSliders[em] ?? 0) * 100)}
                      onChange={(e) => { const v = parseInt(e.target.value) / 100; setFaceSliders((prev) => ({ ...prev, [em]: v })); }}
                      style={{ flex: 1, margin: "0 8px" }} />
                    <span className="emo-bar-pct">{Math.round((faceSliders[em] ?? 0) * 100)}%</span>
                  </div>
                ))}
              </div>
              <div className="emotion-result-card">
                <div className="emotion-result-header">
                  <span className="emotion-badge" style={{ background: fColor(faceEm) }}>{faceEm}</span>
                  <span className="conf-pill">{Math.round(faceCon * 100)}%</span>
                  <small>FaceEmotion msg</small>
                </div>
              </div>
            </>
          )}
        </section>

        {/* ── Voice Emotion ──────────────────────────────────── */}
        <section className="panel">
          <div className="section-title"><span>🎙 Voice Emotion (Arousal/Valence)</span><small>SpeechBrain backend mock</small></div>
          <p className="hint-small">Russell's circumplex model: arousal (energy) × valence (positive/negative).</p>
          <div className="av-sliders">
            <label>Arousal (low energy ← → high energy)
              <input type="range" min={-100} max={100} value={Math.round(voiceArousal * 100)} onChange={(e) => setVoiceArousal(parseInt(e.target.value) / 100)} />
              <span>{voiceArousal > 0 ? "+" : ""}{(voiceArousal * 100).toFixed(0)}</span>
            </label>
            <label>Valence (negative ← → positive)
              <input type="range" min={-100} max={100} value={Math.round(voiceValence * 100)} onChange={(e) => setVoiceValence(parseInt(e.target.value) / 100)} />
              <span>{voiceValence > 0 ? "+" : ""}{(voiceValence * 100).toFixed(0)}</span>
            </label>
          </div>
          <div className="av-grid">
            <div className="av-cell" style={{ opacity: voiceArousal > 0.4 && voiceValence > 0.4 ? 1 : 0.25 }}>⚡ Excited</div>
            <div className="av-cell" style={{ opacity: voiceArousal > 0.4 && voiceValence < -0.3 ? 1 : 0.25 }}>😠 Angry</div>
            <div className="av-cell" style={{ opacity: voiceArousal < -0.3 && voiceValence > 0.3 ? 1 : 0.25 }}>😌 Calm</div>
            <div className="av-cell" style={{ opacity: voiceArousal < -0.3 && voiceValence < -0.3 ? 1 : 0.25 }}>😢 Sad</div>
          </div>
          <div className="emotion-result-card" style={{ marginTop: 10 }}>
            <div className="emotion-result-header">
              <span className="emotion-badge" style={{ background: fColor(voiceEm) }}>{voiceEm}</span>
              <span className="conf-pill">{Math.round(voiceCon * 100)}%</span>
              <small>VoiceEmotion msg</small>
            </div>
          </div>
        </section>

        {/* ── Fusion Engine ──────────────────────────────────── */}
        <section className="panel fusion-panel">
          <div className="section-title"><span>🔀 Emotion Fusion Engine</span><small>EmotionFusionEngine.py · 40/35/15/10</small></div>
          <div className="fusion-inputs">
            {[
              { label: "Face", em: privacyMode ? "suppressed" : faceEm, conf: privacyMode ? 0 : faceCon, weight: 0.40, color: "#44f2a1" },
              { label: "Voice", em: voiceEm, conf: voiceCon, weight: 0.35, color: "#a0c4ff" },
              { label: "Text", em: textEm, conf: textCon, weight: 0.15, color: "#f2e44f" },
              { label: "Gesture", em: gestureHint === "none" ? "none" : gestureHint, conf: gestureHint === "none" ? 0 : 0.8, weight: 0.10, color: "#f0a060" },
            ].map((inp) => (
              <div key={inp.label} className="fusion-input-row">
                <span className="fusion-modal-label" style={{ color: inp.color }}>{inp.label}</span>
                <span className="fusion-modal-em">{inp.em}</span>
                <div className="fusion-modal-bar"><div style={{ width: `${Math.round(inp.conf * 100)}%`, background: inp.color, height: "100%", borderRadius: 4 }} /></div>
                <span className="fusion-modal-weight">{Math.round(inp.weight * 100)}%</span>
              </div>
            ))}
          </div>
          <div className="fusion-gesture-row">
            <span>Gesture hint:</span>
            {GESTURE_HINTS.map((g) => <button key={g} className={`gesture-chip ${gestureHint === g ? "selected" : ""}`} onClick={() => setGestureHint(g)}>{g}</button>)}
          </div>
          <div className="fusion-result" style={{ borderColor: fColor(fusion.dominant) }}>
            <div className="fusion-result-header">
              <span className="emotion-badge" style={{ background: fColor(fusion.dominant), fontSize: "1rem" }}>{fusion.dominant}</span>
              <span className="conf-pill high">{Math.round(fusion.confidence * 100)}%</span>
              <span className="behavior-hint">→ {fusion.behaviorHint}</span>
            </div>
            <div className="fusion-av-row">
              <span>Valence: <b>{fusion.valence > 0 ? "+" : ""}{fusion.valence.toFixed(2)}</b></span>
              <span>Arousal: <b>{fusion.arousal > 0 ? "+" : ""}{fusion.arousal.toFixed(2)}</b></span>
            </div>
            <div className="fusion-msg-preview">
              <span className="msg-type">HumanEmotionState</span>
              <pre>{JSON.stringify({ dominant_emotion: fusion.dominant, confidence: fusion.confidence, behavior_hint: fusion.behaviorHint, privacy_mode: privacyMode }, null, 2)}</pre>
            </div>
          </div>
        </section>

        {/* ── Live Stream ────────────────────────────────────── */}
        <section className="panel">
          <div className="section-title">
            <span>📡 Live Emotion Stream</span>
            <button className={`live-toggle ${liveMode ? "active" : ""}`} onClick={() => setLiveMode((v) => !v)}>{liveMode ? "⏹ Stop" : "▶ Start"}</button>
          </div>
          <p className="hint-small">Simulates the affective AI node publishing HumanEmotionState at ~1 Hz.</p>
          {emotionLog.length === 0 ? <p className="muted">Press Start to begin streaming.</p> : (
            <div className="emotion-stream">
              {emotionLog.map((e, i) => (
                <div key={i} className="emotion-stream-row" style={{ opacity: 1 - i * 0.08 }}>
                  <span className="stream-time">{e.time}</span>
                  <span className="emotion-badge sm" style={{ background: fColor(e.emotion) }}>{e.emotion}</span>
                  <div className="emo-bar-track sm"><div className="emo-bar-fill" style={{ width: `${Math.round(e.conf * 100)}%`, background: fColor(e.emotion) }} /></div>
                  <span className="emo-bar-pct">{Math.round(e.conf * 100)}%</span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── Module Info ─────────────────────────────────────── */}
        <section className="panel">
          <div className="section-title"><span>📦 Module Architecture</span></div>
          {[
            { name: "FaceEmotionAnalyzer", backend: "DeepFace (optional)", note: "Analyzes face crops per PersonState" },
            { name: "VoiceEmotionAnalyzer", backend: "SpeechBrain wav2vec2", note: "Processes AudioChunk messages" },
            { name: "TextEmotionAnalyzer", backend: "Rules-based (no LLM)", note: "Emergency keyword detection" },
            { name: "EmotionFusionEngine", backend: "Weighted avg", note: "face 40% · voice 35% · text 15% · gesture 10%" },
            { name: "TemporalSmoother", backend: "Sliding window", note: "Reduces flicker in emotion stream" },
            { name: "PrivacyGate", backend: "Policy check", note: "Suppresses face analysis in privacy mode" },
          ].map((mod) => (
            <div key={mod.name} className="module-info-row">
              <div><strong>{mod.name}</strong><small>{mod.note}</small></div>
              <span className="mod-backend-badge">{mod.backend}</span>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// PURE LOGIC — Gesture Classifier (mirrors bonbon_gesture classifiers)
// ══════════════════════════════════════════════════════════════════════════════
type GestureResult = { gesture: string; confidence: number; isSafetyRelevant: boolean; intent: string; source: string };

const HAND_GESTURES = ["none", "stop_palm", "thumbs_up", "thumbs_down", "pointing", "wave", "fist", "open_palm", "victory", "ok_sign"];
const BODY_GESTURES = ["none", "raised_hand", "arms_crossed", "pointing_left", "pointing_right", "fallen_posture", "standing", "sitting", "walking"];
const HEAD_GESTURES = ["none", "nod_yes", "shake_no", "tilt_right", "tilt_left", "look_up"];
const SAFETY_GESTURES = new Set(["stop_palm", "raised_hand", "fallen_posture"]);

const GESTURE_INTENT: Record<string, string> = {
  stop_palm: "stop_robot", thumbs_up: "approve_action", thumbs_down: "reject_action",
  pointing: "indicate_direction", wave: "greeting_gesture", fist: "attention",
  open_palm: "halt_request", victory: "positive_feedback", ok_sign: "confirm",
  raised_hand: "request_attention", arms_crossed: "discomfort_signal",
  pointing_left: "navigate_left", pointing_right: "navigate_right",
  fallen_posture: "emergency_fallen", nod_yes: "affirmative", shake_no: "negative",
  tilt_right: "uncertain", look_up: "searching", none: "no_gesture",
};

function classifyGestureResult(gesture: string, source: string): GestureResult {
  return {
    gesture,
    confidence: gesture === "none" ? 0 : 0.55 + Math.random() * 0.4,
    isSafetyRelevant: SAFETY_GESTURES.has(gesture),
    intent: GESTURE_INTENT[gesture] ?? "unknown",
    source,
  };
}

// ══════════════════════════════════════════════════════════════════════════════
// GESTURE: 21-keypoint classifier (mirrors MediaPipe Hands landmark indices)
// ══════════════════════════════════════════════════════════════════════════════
type HandKP = { x: number; y: number; z?: number; name?: string };

function classifyFromKP(kp: HandKP[]): string {
  if (!kp || kp.length < 21) return "none";
  // Finger extension: tip.y < pip.y means finger is raised (lower y = higher on screen)
  const thumbExt  = kp[4].x < kp[3].x;               // rough for mirrored (front) camera
  const indexExt  = kp[8].y  < kp[6].y;
  const middleExt = kp[12].y < kp[10].y;
  const ringExt   = kp[16].y < kp[14].y;
  const pinkyExt  = kp[20].y < kp[18].y;
  const extCount  = [indexExt, middleExt, ringExt, pinkyExt].filter(Boolean).length;

  // Wrist vs fingertips height — used for thumbs up/down
  const wristY = kp[0].y;
  const thumbTipY = kp[4].y;

  if (extCount === 0 && !thumbExt)                             return "fist";
  if (extCount === 4 && thumbExt)                              return "stop_palm";
  if (extCount === 4 && !thumbExt)                             return "open_palm";
  if (extCount === 1 && indexExt)                              return "pointing";
  if (extCount === 2 && indexExt && middleExt && !ringExt && !pinkyExt) return "victory_v";
  if (extCount === 0 && thumbExt && thumbTipY < wristY - 30)  return "thumbs_up";
  if (extCount === 0 && thumbExt && thumbTipY > wristY + 30)  return "thumbs_down";
  if (extCount === 3 && indexExt && middleExt && ringExt)      return "three_fingers";
  if (extCount === 0 && thumbExt)                              return "thumbs_up";
  return extCount >= 2 ? "open_palm" : "pointing";
}

function drawHandLandmarks(ctx: CanvasRenderingContext2D, kp: HandKP[], scX: number, scY: number, color: string) {
  // Connections: wrist→thumb, finger chains
  const connections = [
    [0,1],[1,2],[2,3],[3,4],       // thumb
    [0,5],[5,6],[6,7],[7,8],       // index
    [0,9],[9,10],[10,11],[11,12],  // middle
    [0,13],[13,14],[14,15],[15,16],// ring
    [0,17],[17,18],[18,19],[19,20],// pinky
    [5,9],[9,13],[13,17],          // palm cross
  ];
  ctx.strokeStyle = color; ctx.lineWidth = 2;
  connections.forEach(([a, b]) => {
    if (!kp[a] || !kp[b]) return;
    ctx.beginPath();
    ctx.moveTo(kp[a].x * scX, kp[a].y * scY);
    ctx.lineTo(kp[b].x * scX, kp[b].y * scY);
    ctx.stroke();
  });
  kp.forEach((p, i) => {
    ctx.fillStyle = i === 0 ? "#ff5c7a" : i % 4 === 0 ? "#f2e44f" : color;
    ctx.beginPath();
    ctx.arc(p.x * scX, p.y * scY, i === 0 ? 5 : 3, 0, Math.PI * 2);
    ctx.fill();
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 10 — GESTURE
// ══════════════════════════════════════════════════════════════════════════════
function GestureTab(p: TabProps) {
  // Camera state
  const gestureVideoRef   = useRef<HTMLVideoElement | null>(null);
  const gestureCanvasRef  = useRef<HTMLCanvasElement | null>(null);
  const gestureAnimRef    = useRef<number | null>(null);
  const handDetectorRef   = useRef<{ estimateHands: (v: HTMLVideoElement) => Promise<{ keypoints: HandKP[]; handedness: string }[]> } | null>(null);
  const lastHandDetectRef = useRef(0);
  const prevWristXRef     = useRef<number[]>([]);
  const [camActive, setCamActive] = useState(false);
  const [modelStatus, setModelStatus] = useState("Model not loaded");
  const [loadingModel, setLoadingModel] = useState(false);
  const [detectedGesture, setDetectedGesture] = useState("none");
  const [handCount, setHandCount] = useState(0);
  const [fps, setFps] = useState(0);
  const lastFpsRef = useRef(performance.now());

  // Simulation state (manual override)
  const [handGesture, setHandGesture] = useState("none");
  const [bodyGesture, setBodyGesture] = useState("none");
  const [headGesture, setHeadGesture] = useState("none");
  const [handResult, setHandResult] = useState<GestureResult | null>(null);
  const [bodyResult, setBodyResult] = useState<GestureResult | null>(null);
  const [headResult, setHeadResult] = useState<GestureResult | null>(null);
  const [gestureHistory, setGestureHistory] = useState<GestureResult[]>([]);
  const [smoothed, setSmoothed] = useState("none");
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.5);
  const [streamGesture, setStreamGesture] = useState(false);
  const streamRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Camera + hand detection ─────────────────────────────────────────────────
  const loadHandModel = async () => {
    if (handDetectorRef.current) return;
    setLoadingModel(true);
    setModelStatus("Loading MediaPipe Hands (TFJS lite)…");
    try {
      const tf = await import("@tensorflow/tfjs");
      await tf.ready();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const hpd = await import("@tensorflow-models/hand-pose-detection") as any;
      const model = hpd.SupportedModels.MediaPipeHands;
      const detector = await hpd.createDetector(model, { runtime: "tfjs", modelType: "lite", maxHands: 2 });
      handDetectorRef.current = detector;
      setModelStatus("✓ MediaPipe Hands ready (21 landmarks, live)");
      p.addLog("ok", "Hand pose detection model loaded");
    } catch (err) {
      setModelStatus(`Model unavailable: ${err instanceof Error ? err.message.slice(0, 60) : err}`);
      p.addLog("warn", "Hand model failed — use manual simulation below");
    } finally { setLoadingModel(false); }
  };

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: "user" }, audio: false });
      const video = gestureVideoRef.current;
      if (!video) return;
      video.srcObject = stream;
      await video.play();
      setCamActive(true);
      p.addLog("ok", "Gesture camera started");
      void loadHandModel();
      runGestureLoop();
    } catch (e) { p.addLog("error", `Gesture camera: ${e instanceof Error ? e.message : e}`); }
  };

  const stopCamera = () => {
    if (gestureAnimRef.current) cancelAnimationFrame(gestureAnimRef.current);
    const video = gestureVideoRef.current;
    if (video) { (video.srcObject as MediaStream | null)?.getTracks().forEach((t) => t.stop()); video.srcObject = null; }
    setCamActive(false); setDetectedGesture("none"); setHandCount(0);
    p.addLog("info", "Gesture camera stopped");
  };

  const runGestureLoop = () => {
    const video  = gestureVideoRef.current;
    const canvas = gestureCanvasRef.current;
    if (!video || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    canvas.width = 640; canvas.height = 480;

    const loop = () => {
      if (!video.videoWidth) { gestureAnimRef.current = requestAnimationFrame(loop); return; }
      // Mirror the feed for natural interaction
      ctx.save();
      ctx.scale(-1, 1);
      ctx.drawImage(video, -canvas.width, 0, canvas.width, canvas.height);
      ctx.restore();

      // FPS
      const now = performance.now();
      setFps(Math.round(1000 / Math.max(now - lastFpsRef.current, 1)));
      lastFpsRef.current = now;

      // Hand detection throttled to ~15 Hz
      if (now - lastHandDetectRef.current > 67 && handDetectorRef.current) {
        lastHandDetectRef.current = now;
        handDetectorRef.current.estimateHands(video).then((hands) => {
          setHandCount(hands.length);
          ctx.save(); ctx.scale(-1,1); ctx.drawImage(video, -canvas.width, 0, canvas.width, canvas.height); ctx.restore();
          if (hands.length === 0) { setDetectedGesture("none"); return; }

          const scX = canvas.width  / video.videoWidth;
          const scY = canvas.height / video.videoHeight;

          // Wave detection: track wrist X movement
          const wristXs = hands.map((h) => {
            const mirroredX = video.videoWidth - h.keypoints[0].x;  // mirror
            return mirroredX;
          });
          prevWristXRef.current.push(...wristXs);
          if (prevWristXRef.current.length > 20) prevWristXRef.current = prevWristXRef.current.slice(-20);
          const wristRange = Math.max(...prevWristXRef.current) - Math.min(...prevWristXRef.current);

          hands.forEach((hand, idx) => {
            const color = idx === 0 ? "#44f2a1" : "#a0c4ff";
            // Mirror keypoints for display
            const mirroredKP = hand.keypoints.map((kp) => ({ ...kp, x: video.videoWidth - kp.x }));
            drawHandLandmarks(ctx, mirroredKP, scX, scY, color);
            const gesture = wristRange > 80 ? "wave" : classifyFromKP(mirroredKP);

            // Overlay gesture label
            ctx.fillStyle = SAFETY_GESTURES.has(gesture) ? "#ff5c7a" : "#44f2a1";
            ctx.font = "bold 18px sans-serif";
            ctx.fillText(`${hand.handedness}: ${gesture}`, mirroredKP[0].x * scX - 40, mirroredKP[0].y * scY - 14);

            if (idx === 0) {
              setDetectedGesture(gesture);
              const gr = classifyGestureResult(gesture, "camera");
              setGestureHistory((prev) => [gr, ...prev].slice(0, 8));
            }
          });

          // Reset wave accumulator gradually
          if (prevWristXRef.current.length > 10) prevWristXRef.current = prevWristXRef.current.slice(-5);
        }).catch(() => {});
      }
      gestureAnimRef.current = requestAnimationFrame(loop);
    };
    loop();
  };

  // Cleanup on unmount
  useEffect(() => () => {
    if (gestureAnimRef.current) cancelAnimationFrame(gestureAnimRef.current);
  }, []);

  const classify = (g: string, source: string, setter: (r: GestureResult) => void) => {
    const r = classifyGestureResult(g, source);
    setter(r);
    if (g !== "none") {
      setGestureHistory((prev) => [r, ...prev].slice(0, 8));
    }
  };

  // Temporal smoother majority vote
  useEffect(() => {
    if (gestureHistory.length < 2) { setSmoothed(gestureHistory[0]?.gesture ?? "none"); return; }
    const counts: Record<string, number> = {};
    gestureHistory.slice(0, 5).forEach((gr) => { counts[gr.gesture] = (counts[gr.gesture] ?? 0) + 1; });
    setSmoothed(Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0]);
  }, [gestureHistory]);

  // Simulation stream
  useEffect(() => {
    if (!streamGesture) { if (streamRef.current) clearInterval(streamRef.current); return; }
    const allGestures = [...HAND_GESTURES.filter((g) => g !== "none")];
    streamRef.current = setInterval(() => {
      const g = allGestures[Math.floor(Math.random() * allGestures.length)];
      const r = classifyGestureResult(g, "hand");
      setHandGesture(g);
      setHandResult(r);
      setGestureHistory((prev) => [r, ...prev].slice(0, 8));
    }, 1200);
    return () => { if (streamRef.current) clearInterval(streamRef.current); };
  }, [streamGesture]);



  const activeResult = camActive
    ? (detectedGesture !== "none" ? classifyGestureResult(detectedGesture, "camera") : null)
    : (handResult ?? bodyResult ?? headResult);
  const safetyAlert = activeResult?.isSafetyRelevant && activeResult.gesture !== "none";

  return (
    <div className="tab-body">
      <div className="section-hero">
        <h2>🤚 Gesture Recognition — bonbon_gesture</h2>
        <p>Live camera-based gesture recognition using MediaPipe Hands (21 landmarks per hand). Shows the full pipeline: camera → landmark detection → gesture classification → temporal smoothing → safety tagging → intent mapping. Manual simulation available when camera is off.</p>
      </div>

      {safetyAlert && (
        <div className="safety-gesture-alert">
          🚨 <strong>Safety gesture detected:</strong> <span>{activeResult?.gesture}</span> → intent: <strong>{activeResult?.intent}</strong>
        </div>
      )}

      {/* ── LIVE CAMERA SECTION ──────────────────────────────────────── */}
      <section className="panel gesture-camera-panel">
        <div className="section-title">
          <span>📹 Live Camera Gesture Detection</span>
          <small>{modelStatus}</small>
          <div className="gesture-cam-controls">
            {!camActive
              ? <button className="primary" onClick={() => void startCamera()}>▶ Start Camera</button>
              : <button className="danger" onClick={stopCamera}>⏹ Stop</button>}
            {!camActive && !handDetectorRef.current && !loadingModel && (
              <button onClick={() => void loadHandModel()} disabled={loadingModel}>
                {loadingModel ? "Loading…" : "⚡ Pre-load Model"}
              </button>
            )}
          </div>
        </div>

        <div className="gesture-cam-layout">
          <div className="gesture-cam-video">
            <video ref={gestureVideoRef} muted playsInline style={{ display: "none" }} />
            <canvas ref={gestureCanvasRef}
              style={{ width: "100%", maxWidth: 480, borderRadius: 12, background: "#000",
                       display: camActive ? "block" : "none" }} />
            {!camActive && (
              <div className="gesture-cam-placeholder">
                <span>🤚</span>
                <p>Start camera to see live hand landmark detection</p>
                <small>Uses MediaPipe Hands TFJS model — detects 21 landmarks per hand</small>
              </div>
            )}
          </div>

          <div className="gesture-live-info">
            <div className="gesture-live-stat"><span>Hands detected</span><b>{handCount}</b></div>
            <div className="gesture-live-stat"><span>Camera FPS</span><b>{fps}</b></div>
            <div className="gesture-live-stat"><span>Detected gesture</span>
              <b className={SAFETY_GESTURES.has(detectedGesture) ? "warn-text" : "ok-text"} style={{ textTransform: "capitalize" }}>{detectedGesture || "none"}</b>
            </div>
            {detectedGesture !== "none" && (
              <>
                <div className="gesture-live-stat"><span>Intent</span><b>{GESTURE_INTENT[detectedGesture] ?? "unknown"}</b></div>
                <div className="gesture-live-stat"><span>Safety flag</span><b className={SAFETY_GESTURES.has(detectedGesture) ? "warn-text" : "ok-text"}>{SAFETY_GESTURES.has(detectedGesture) ? "🚨 Safety-relevant" : "✓ Normal"}</b></div>
              </>
            )}
            <div className="gesture-supported-list">
              <small>Recognized gestures:</small>
              {["fist","stop_palm","open_palm","pointing","victory_v","thumbs_up","thumbs_down","wave","three_fingers"].map((g) => (
                <span key={g} className={`gesture-badge sm ${g === detectedGesture ? "active-gesture" : ""} ${SAFETY_GESTURES.has(g) ? "safety-bg" : ""}`}>{g.replace(/_/g," ")}</span>
              ))}
            </div>
          </div>
        </div>
      </section>

      <div className="gesture-grid">
        {/* ── Manual Simulation ────────────────────── */}
        <section className="panel">
          <div className="section-title"><span>🖐 Manual Simulation</span><small>21-landmark mock · for testing without camera</small></div>
          <p className="hint-small">Click any gesture to simulate MediaPipe classification. Camera mode (above) overrides these when active.</p>
          <div className="gesture-btn-grid">
            {HAND_GESTURES.map((g) => (
              <button key={g} className={`gesture-select-btn ${handGesture === g ? "selected" : ""} ${SAFETY_GESTURES.has(g) ? "safety" : ""}`}
                onClick={() => { setHandGesture(g); classify(g, "hand", setHandResult); }}>
                {SAFETY_GESTURES.has(g) ? "⚠ " : ""}{g.replace(/_/g, " ")}
              </button>
            ))}
          </div>
          {handResult && handResult.gesture !== "none" && (
            <div className="gesture-result-card">
              <div className="gesture-result-row"><span>Gesture</span><b>{handResult.gesture}</b></div>
              <div className="gesture-result-row"><span>Confidence</span>
                <div className="emo-bar-track"><div className="emo-bar-fill" style={{ width: `${Math.round(handResult.confidence * 100)}%`, background: "#44f2a1" }} /></div>
                <b>{Math.round(handResult.confidence * 100)}%</b>
              </div>
              <div className="gesture-result-row"><span>Intent</span><b>{handResult.intent}</b></div>
              <div className="gesture-result-row"><span>Safety</span><b className={handResult.isSafetyRelevant ? "warn-text" : "ok-text"}>{handResult.isSafetyRelevant ? "🚨 YES" : "✓ No"}</b></div>
            </div>
          )}
        </section>

        {/* ── Body Gesture ─────────────────────────── */}
        <section className="panel">
          <div className="section-title"><span>🧍 Body Gesture Classifier</span><small>33 pose landmarks · MediaPipe Pose</small></div>
          <div className="gesture-btn-grid">
            {BODY_GESTURES.map((g) => (
              <button key={g} className={`gesture-select-btn ${bodyGesture === g ? "selected" : ""} ${SAFETY_GESTURES.has(g) ? "safety" : ""}`}
                onClick={() => { setBodyGesture(g); classify(g, "body", setBodyResult); }}>
                {SAFETY_GESTURES.has(g) ? "⚠ " : ""}{g.replace(/_/g, " ")}
              </button>
            ))}
          </div>
          {bodyResult && bodyResult.gesture !== "none" && (
            <div className="gesture-result-card">
              <div className="gesture-result-row"><span>Gesture</span><b>{bodyResult.gesture}</b></div>
              <div className="gesture-result-row"><span>Confidence</span>
                <div className="emo-bar-track"><div className="emo-bar-fill" style={{ width: `${Math.round(bodyResult.confidence * 100)}%`, background: "#a0c4ff" }} /></div>
                <b>{Math.round(bodyResult.confidence * 100)}%</b>
              </div>
              <div className="gesture-result-row"><span>Intent</span><b>{bodyResult.intent}</b></div>
              <div className="gesture-result-row"><span>Safety</span><b className={bodyResult.isSafetyRelevant ? "warn-text" : "ok-text"}>{bodyResult.isSafetyRelevant ? "🚨 YES" : "✓ No"}</b></div>
            </div>
          )}
        </section>

        {/* ── Head Gesture ─────────────────────────── */}
        <section className="panel">
          <div className="section-title"><span>🗣 Head Gesture Classifier</span><small>Temporal nose tracking · nod/shake</small></div>
          <div className="gesture-btn-grid">
            {HEAD_GESTURES.map((g) => (
              <button key={g} className={`gesture-select-btn ${headGesture === g ? "selected" : ""}`}
                onClick={() => { setHeadGesture(g); classify(g, "head", setHeadResult); }}>
                {g.replace(/_/g, " ")}
              </button>
            ))}
          </div>
          {headResult && headResult.gesture !== "none" && (
            <div className="gesture-result-card">
              <div className="gesture-result-row"><span>Gesture</span><b>{headResult.gesture}</b></div>
              <div className="gesture-result-row"><span>Intent</span><b>{headResult.intent}</b></div>
            </div>
          )}
        </section>

        {/* ── Temporal Smoother + Pipeline ─────────── */}
        <section className="panel">
          <div className="section-title">
            <span>⏱ Temporal Smoother</span>
            <button className={`live-toggle ${streamGesture ? "active" : ""}`} onClick={() => setStreamGesture((v) => !v)}>{streamGesture ? "⏹ Stop" : "▶ Simulate"}</button>
          </div>
          <p className="hint-small">Majority vote over last 5 frames. Confidence threshold: {confidenceThreshold.toFixed(2)}</p>
          <label>Confidence threshold
            <input type="range" min={0} max={100} value={Math.round(confidenceThreshold * 100)} onChange={(e) => setConfidenceThreshold(parseInt(e.target.value) / 100)} />
          </label>
          <div className="smoother-display">
            <div className="smoother-result">
              <span>Smoothed output:</span>
              <span className="gesture-badge">{smoothed}</span>
            </div>
            <div className="gesture-history">
              {gestureHistory.slice(0, 5).map((gr, i) => (
                <div key={i} className={`gesture-history-row ${gr.confidence >= confidenceThreshold ? "above-threshold" : "below-threshold"}`}>
                  <span>{gr.source}</span>
                  <span className="gesture-badge sm">{gr.gesture}</span>
                  <span>{Math.round(gr.confidence * 100)}%</span>
                  <span className={gr.confidence >= confidenceThreshold ? "ok-text" : "muted"}>
                    {gr.confidence >= confidenceThreshold ? "✓" : "✗"}
                  </span>
                </div>
              ))}
              {gestureHistory.length === 0 && <p className="muted">No gestures detected yet.</p>}
            </div>
          </div>

          <div className="section-title" style={{ marginTop: 16 }}><span>🔗 GestureEvent Message</span></div>
          <pre className="json-view compact">{JSON.stringify({
            gesture_name: smoothed,
            confidence: (activeResult?.confidence ?? 0).toFixed(2),
            is_safety_relevant: SAFETY_GESTURES.has(smoothed),
            intent: GESTURE_INTENT[smoothed] ?? "unknown",
            source_module: "bonbon_gesture",
          }, null, 2)}</pre>
        </section>

        {/* ── Module Info ──────────────────────────── */}
        <section className="panel">
          <div className="section-title"><span>📦 Module Architecture</span></div>
          {[
            { name: "MediaPipeBackend", note: "Holistic model: pose + hands + face mesh" },
            { name: "HandGestureClassifier", note: "21-point landmark rules (stop_palm, wave…)" },
            { name: "BodyGestureClassifier", note: "33-point pose rules (raised_hand, fallen…)" },
            { name: "HeadGestureClassifier", note: "Temporal nose tracking for nod/shake" },
            { name: "GestureTemporalSmoother", note: "Majority vote with cooldown (5-frame window)" },
            { name: "GestureIntentMapper", note: "Maps gesture → robot behavior intent" },
            { name: "GestureSafetyClassifier", note: "Flags stop_palm, raised_hand, fallen_posture" },
          ].map((mod) => (
            <div key={mod.name} className="module-info-row">
              <div><strong>{mod.name}</strong><small>{mod.note}</small></div>
            </div>
          ))}
          <div className="section-title" style={{ marginTop: 14 }}><span>Safety-Relevant Gestures</span></div>
          <div className="safety-gesture-list">
            {[...SAFETY_GESTURES].map((g) => <span key={g} className="safety-gesture-chip">{g}</span>)}
          </div>
        </section>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// PURE LOGIC — Behavior Engine (mirrors bonbon_behavior_engine core)
// ══════════════════════════════════════════════════════════════════════════════
type RiskLevel = "none" | "low" | "medium" | "high" | "critical";
type BehaviorStateId = "IDLE" | "GREETING" | "INTERACTING" | "NAVIGATING" | "SERVING" | "ALERTING" | "RETURNING";

const CRITICAL_PATTERNS = [/\bcmd_vel\b/i, /\bservo\s*(command|angle|position)\b/i, /\boverride\s+(safety|gate)\b/i, /\bignore\s+(safety|obstacle|person)\b/i, /\bkill\s+(node|process|robot)\b/i, /\braw\s+servo\b/i, /\bpublish\s+to\b/i, /\bjoint\s*(state|command)\b/i, /\bdeactivate\s+safety\b/i, /\bhardware\s+reset\b/i];
const HIGH_PATTERNS = [/\b(extend|raise|lower)\s+(arm|hand|limb)\b/i, /\bpick\s+up\b/i, /\bphysical\s+contact\b/i, /\bgrab\s+the\b/i, /\bapply\s+force\b/i];
const MEDIUM_PATTERNS = [/\b(go|move|navigate|drive)\s+(to|toward)\b/i, /\bapproach\s+(the\s+)?(person|visitor)\b/i, /\bfollow\b/i, /\bdock(ing)?\b/i, /\bdeliver\b/i];
const LOW_PATTERNS = [/\b(wave|nod|bow|gesture|point)\b/i, /\b(say|speak|announce|greet)\b/i, /\bsmile\b/i];

function classifyRisk(text: string, source = "unknown"): { level: RiskLevel; reasons: string[]; recommended: string } {
  if (!text.trim()) return { level: "none", reasons: [], recommended: "approve" };
  let level: RiskLevel = "none";
  const reasons: string[] = [];
  const check = (pats: RegExp[], lv: RiskLevel) => {
    const order: Record<RiskLevel, number> = { none: 0, low: 1, medium: 2, high: 3, critical: 4 };
    for (const p of pats) { const m = p.exec(text); if (m) { reasons.push(`Pattern matched: "${m[0]}"`); if (order[lv] > order[level]) level = lv; } }
  };
  check(CRITICAL_PATTERNS, "critical");
  check(HIGH_PATTERNS, "high");
  check(MEDIUM_PATTERNS, "medium");
  check(LOW_PATTERNS, "low");
  if (source === "llm" && level === "none") { level = "low"; reasons.push("LLM source: minimum risk is low"); }
  const recs: Record<RiskLevel, string> = { none: "approve", low: "approve", medium: "approve", high: "escalate", critical: "reject" };
  return { level, reasons, recommended: recs[level] };
}

const FSM_TRANSITIONS: Record<BehaviorStateId, BehaviorStateId[]> = {
  IDLE:        ["GREETING", "NAVIGATING", "SERVING", "ALERTING", "RETURNING"],
  GREETING:    ["IDLE", "INTERACTING", "ALERTING"],
  INTERACTING: ["IDLE", "NAVIGATING", "SERVING", "ALERTING"],
  NAVIGATING:  ["IDLE", "INTERACTING", "SERVING", "ALERTING", "RETURNING"],
  SERVING:     ["IDLE", "INTERACTING", "NAVIGATING", "ALERTING", "RETURNING"],
  ALERTING:    ["IDLE", "RETURNING"],
  RETURNING:   ["IDLE", "ALERTING"],
};
const FSM_STATE_COLORS: Record<BehaviorStateId, string> = {
  IDLE: "#a0c4ff", GREETING: "#44f2a1", INTERACTING: "#f2e44f", NAVIGATING: "#f0a060",
  SERVING: "#c080f0", ALERTING: "#f06060", RETURNING: "#80c080",
};
const FSM_STATE_DESC: Record<BehaviorStateId, string> = {
  IDLE: "Robot is idle — ambient scanning", GREETING: "Greeting a newly detected person",
  INTERACTING: "In conversation or task interaction", NAVIGATING: "Moving to a navigation goal",
  SERVING: "Performing a service task", ALERTING: "Handling emergency/operator alert",
  RETURNING: "Returning to home / dock",
};

const EMOTION_PLANS: Record<string, { gesture: string; ttsEmotion: string; speed: number; ack: string }> = {
  happy:     { gesture: "wave",           ttsEmotion: "warm",     speed: 1.0,  ack: "" },
  neutral:   { gesture: "listening_pose", ttsEmotion: "neutral",  speed: 1.0,  ack: "" },
  sad:       { gesture: "listening_pose", ttsEmotion: "warm",     speed: 0.9,  ack: "I'm here to help." },
  angry:     { gesture: "listening_pose", ttsEmotion: "calm",     speed: 0.85, ack: "I understand. Let me help you." },
  fearful:   { gesture: "rest_pose",      ttsEmotion: "calm",     speed: 0.8,  ack: "You're safe. I'm here." },
  surprised: { gesture: "thinking_pose",  ttsEmotion: "neutral",  speed: 0.9,  ack: "" },
  distress:  { gesture: "listening_pose", ttsEmotion: "concerned",speed: 0.85, ack: "Are you alright? Do you need help?" },
  emergency: { gesture: "emergency_attention_pose", ttsEmotion: "urgent", speed: 1.2, ack: "Emergency detected! Alerting staff now." },
};

// ══════════════════════════════════════════════════════════════════════════════
// TAB 11 — BEHAVIOR ENGINE
// ══════════════════════════════════════════════════════════════════════════════
function BehaviorEngineTab(_p: TabProps) {
  const [fsmState, setFsmState] = useState<BehaviorStateId>("IDLE");
  const [fsmHistory, setFsmHistory] = useState<{ from: BehaviorStateId; to: BehaviorStateId; time: string; reason: string }[]>([]);
  const [commandText, setCommandText] = useState("");
  const [commandSource, setCommandSource] = useState<"llm" | "operator" | "speech">("llm");
  const [riskResult, setRiskResult] = useState<{ level: RiskLevel; reasons: string[]; recommended: string } | null>(null);
  const [gateResult, setGateResult] = useState<{ allowed: boolean; proposalType: string; content: string } | null>(null);
  const [selectedEmotion, setSelectedEmotion] = useState("neutral");
  const [operatingMode, setOperatingMode] = useState("normal");
  const [decisionLog, setDecisionLog] = useState<{ time: string; action: string; decision: string; reason: string }[]>([]);
  const [rateLimitCounters, setRateLimitCounters] = useState<Record<string, number>>({});

  const OPERATING_MODES = ["normal", "child_safe", "elderly", "degraded", "demo", "emergency"];
  const allEmotions = Object.keys(EMOTION_PLANS);
  const RISK_COLORS: Record<RiskLevel, string> = { none: "#a0c4ff", low: "#44f2a1", medium: "#f2e44f", high: "#f0a060", critical: "#f06060" };

  // Auto-classify on typing
  useEffect(() => {
    if (!commandText.trim()) { setRiskResult(null); setGateResult(null); return; }
    const t = setTimeout(() => {
      const risk = classifyRisk(commandText, commandSource);
      setRiskResult(risk);
      // Gate logic
      if (risk.level === "critical") {
        setGateResult({ allowed: false, proposalType: "alert_operator", content: "BLOCKED: forbidden command pattern detected" });
      } else if (risk.level === "high") {
        setGateResult({ allowed: false, proposalType: "ask_clarification", content: "BLOCKED: high-risk command requires operator approval" });
      } else {
        // Extract intent
        let proposalType = "speak", content = commandText;
        if (/\b(go|navigate|move)\s+to\b/i.test(commandText)) { proposalType = "navigate"; content = commandText.match(/to\s+(.+?)(?:\.|,|$)/i)?.[1] ?? commandText; }
        else if (/\b(wave|nod|bow|gesture)\b/i.test(commandText)) { proposalType = "gesture"; content = commandText.match(/\b(wave|nod_yes|shake_no|greeting_pose|apology_pose)\b/i)?.[0] ?? "nod_yes"; }
        else if (/\b(say|speak|tell|announce)\b/i.test(commandText)) { const m = commandText.match(/(?:say|speak|tell|announce)[:\s]+["']?(.+?)["']?$/i); content = m?.[1] ?? commandText; }
        setGateResult({ allowed: true, proposalType, content: content.slice(0, 80) });
      }
    }, 300);
    return () => clearTimeout(t);
  }, [commandText, commandSource]);

  const doTransition = (to: BehaviorStateId, reason = "") => {
    const allowed = FSM_TRANSITIONS[fsmState].includes(to);
    if (!allowed) return;
    setFsmHistory((h) => [{ from: fsmState, to, time: nowStr(), reason }, ...h].slice(0, 10));
    setFsmState(to);
    setDecisionLog((d) => [{ time: nowStr(), action: `FSM: ${fsmState}→${to}`, decision: "approved", reason }, ...d].slice(0, 15));
  };

  const executeGateCommand = () => {
    if (!gateResult) return;
    const entry = { time: nowStr(), action: gateResult.proposalType, decision: gateResult.allowed ? "approved" : "rejected", reason: riskResult?.level ?? "" };
    setDecisionLog((d) => [entry, ...d].slice(0, 15));
    if (gateResult.allowed) {
      setRateLimitCounters((c) => ({ ...c, [gateResult.proposalType]: Date.now() }));
    }
  };

  const emPlan = EMOTION_PLANS[selectedEmotion] ?? EMOTION_PLANS.neutral;
  const modeEmPlan = { ...emPlan };
  if (operatingMode === "child_safe") { modeEmPlan.gesture = "greeting_pose"; modeEmPlan.speed = 0.85; }
  if (operatingMode === "elderly") { modeEmPlan.speed = 0.8; }

  return (
    <div className="tab-body">
      <div className="section-hero">
        <h2>🤖 Behavior Engine — bonbon_behavior_engine</h2>
        <p>Central decision hub. Fuses emotion, gesture, spatial, speech and LLM signals into safe validated decisions. <strong>The LLM never directly controls navigation or actuation</strong> — all outputs are risk-classified and safety-gated first.</p>
      </div>

      <div className="behavior-grid">
        {/* ── Behavior State Machine ─────────────────── */}
        <section className="panel">
          <div className="section-title"><span>🔀 Behavior State Machine</span><small>7-state FSM · legal transitions enforced</small></div>
          <div className="fsm-display">
            {(Object.keys(FSM_TRANSITIONS) as BehaviorStateId[]).map((s) => (
              <div key={s} className={`fsm-state-node ${fsmState === s ? "active" : ""}`}
                style={{ borderColor: FSM_STATE_COLORS[s], background: fsmState === s ? FSM_STATE_COLORS[s] + "22" : "" }}>
                <span className="fsm-state-name" style={{ color: FSM_STATE_COLORS[s] }}>{s}</span>
                <small>{FSM_STATE_DESC[s]}</small>
              </div>
            ))}
          </div>
          <div className="section-title" style={{ marginTop: 12 }}><span>Transition buttons</span><small>Legal transitions from {fsmState}</small></div>
          <div className="fsm-btn-row">
            {(Object.keys(FSM_TRANSITIONS) as BehaviorStateId[]).map((to) => {
              const legal = FSM_TRANSITIONS[fsmState].includes(to);
              return (
                <button key={to} className={`fsm-btn ${fsmState === to ? "current" : ""} ${legal ? "" : "illegal"}`}
                  onClick={() => doTransition(to)} disabled={!legal || fsmState === to}
                  style={{ borderColor: FSM_STATE_COLORS[to] }}>
                  → {to}
                </button>
              );
            })}
          </div>
          <div className="section-title" style={{ marginTop: 10 }}><span>State history</span></div>
          <div className="fsm-history">
            {fsmHistory.length === 0 ? <p className="muted">No transitions yet.</p> : fsmHistory.map((e, i) => (
              <div key={i} className="fsm-history-row">
                <span>{e.time}</span>
                <span style={{ color: FSM_STATE_COLORS[e.from] }}>{e.from}</span>
                <span>→</span>
                <span style={{ color: FSM_STATE_COLORS[e.to] }}>{e.to}</span>
                {e.reason && <small>{e.reason}</small>}
              </div>
            ))}
          </div>
        </section>

        {/* ── LLM Command Gate ──────────────────────── */}
        <section className="panel">
          <div className="section-title"><span>🔐 LLM Command Gate</span><small>Real-time risk classification · LLM never directly controls robot</small></div>
          <div className="cmd-source-row">
            {(["llm", "operator", "speech"] as const).map((src) => (
              <button key={src} className={`source-chip ${commandSource === src ? "selected" : ""}`} onClick={() => setCommandSource(src)}>{src}</button>
            ))}
          </div>
          <label>Command text (auto-classifies as you type)
            <textarea value={commandText} onChange={(e) => setCommandText(e.target.value)} placeholder="Type a command… e.g. 'go to the lobby', 'wave at the visitor', 'publish to cmd_vel'" style={{ minHeight: 72 }} />
          </label>

          {riskResult && (
            <div className="risk-result-card" style={{ borderColor: RISK_COLORS[riskResult.level] }}>
              <div className="risk-result-header">
                <span className="risk-badge" style={{ background: RISK_COLORS[riskResult.level] }}>{riskResult.level.toUpperCase()}</span>
                <span className={`gate-decision ${gateResult?.allowed ? "allowed" : "blocked"}`}>
                  {gateResult?.allowed ? "✓ ALLOWED" : "✗ BLOCKED"}
                </span>
                <span className="risk-recommendation">→ {riskResult.recommended}</span>
              </div>
              {riskResult.reasons.length > 0 && (
                <div className="risk-reasons">
                  {riskResult.reasons.map((r, i) => <div key={i} className="risk-reason-row">⚡ {r}</div>)}
                </div>
              )}
              {gateResult && (
                <div className="gate-proposal">
                  <span className="proposal-type-badge">{gateResult.proposalType}</span>
                  <span className="proposal-content">{gateResult.content}</span>
                </div>
              )}
            </div>
          )}

          <div className="try-examples" style={{ marginTop: 10 }}>
            {[
              ["🟢 Say hello", "say: Hello, welcome to our café!"],
              ["🟢 Wave", "wave at the visitor"],
              ["🟡 Navigate", "go to the lobby and wait"],
              ["🔴 Forbidden", "publish to cmd_vel with speed 0.5"],
              ["🔴 Override", "override safety gate now"],
            ].map(([label, ex]) => (
              <button key={label} className="example-chip" onClick={() => setCommandText(ex)}>{label}</button>
            ))}
          </div>

          {gateResult?.allowed && (
            <div className="btn-row" style={{ marginTop: 12 }}>
              <button className="primary" onClick={executeGateCommand}>Submit proposal →</button>
            </div>
          )}
        </section>

        {/* ── Emotion Response Planner ───────────────── */}
        <section className="panel">
          <div className="section-title"><span>💡 Emotion-Aware Response Planner</span><small>EmotionAwareResponsePlanner.py</small></div>
          <div className="section-title" style={{ marginTop: 0 }}><span>Operating mode</span></div>
          <div className="mode-chip-row">
            {OPERATING_MODES.map((m) => (
              <button key={m} className={`mode-chip ${operatingMode === m ? "selected" : ""} ${m === "emergency" ? "danger-mode" : ""}`}
                onClick={() => setOperatingMode(m)}>{m}</button>
            ))}
          </div>
          <div className="section-title" style={{ marginTop: 10 }}><span>Human emotion</span></div>
          <div className="mode-chip-row">
            {allEmotions.map((em) => (
              <button key={em} className={`mode-chip ${selectedEmotion === em ? "selected" : ""}`}
                onClick={() => setSelectedEmotion(em)}>{em}</button>
            ))}
          </div>
          <div className="emotion-plan-result">
            <div className="plan-row"><span>Gesture</span><b className="gesture-badge">{modeEmPlan.gesture}</b></div>
            <div className="plan-row"><span>TTS emotion</span><b>{modeEmPlan.ttsEmotion}</b></div>
            <div className="plan-row"><span>TTS speed</span><b>{modeEmPlan.speed}×</b></div>
            {modeEmPlan.ack && <div className="plan-row ack"><span>Acknowledgment text</span><b>"{modeEmPlan.ack}"</b></div>}
            {operatingMode !== "normal" && (
              <div className="plan-mode-override">ℹ Mode override active: <b>{operatingMode}</b></div>
            )}
          </div>
          <div className="section-title" style={{ marginTop: 14 }}><span>BehaviorDecision message preview</span></div>
          <pre className="json-view compact">{JSON.stringify({
            decision: "approved",
            approved_action: modeEmPlan.gesture !== "none" ? "gesture" : "speak",
            approved_content: modeEmPlan.ack || modeEmPlan.gesture,
            safety_approved: true,
            operating_mode: operatingMode,
          }, null, 2)}</pre>
        </section>

        {/* ── Decision Log ──────────────────────────── */}
        <section className="panel">
          <div className="section-title"><span>📋 Decision Log</span><small>{decisionLog.length} entries</small></div>
          {decisionLog.length === 0 ? <p className="muted">No decisions logged yet. Use the FSM or LLM Gate above.</p> : (
            <div className="decision-log">
              {decisionLog.map((d, i) => (
                <div key={i} className={`decision-row ${d.decision}`}>
                  <span className="decision-time">{d.time}</span>
                  <span className={`decision-badge ${d.decision}`}>{d.decision}</span>
                  <span className="decision-action">{d.action}</span>
                  {d.reason && <span className="decision-reason">{d.reason}</span>}
                </div>
              ))}
            </div>
          )}
          <div className="section-title" style={{ marginTop: 14 }}><span>📦 Core Components</span></div>
          {[
            { name: "BehaviorStateMachine", note: "7-state FSM, legal transitions enforced" },
            { name: "CommandRiskClassifier", note: "Pattern-based, LLM-free, <1 ms, O(n) patterns" },
            { name: "LLMCommandGate", note: "LLM output → safe BehaviorProposal only" },
            { name: "EmotionAwareResponsePlanner", note: "Emotion → gesture + TTS plan (no LLM)" },
            { name: "ProposalEvaluator", note: "Rate limiting + safety gating + content sanitize" },
            { name: "BehaviorEngineNode", note: "LifecycleNode: fuses all signals → decisions" },
          ].map((mod) => (
            <div key={mod.name} className="module-info-row">
              <div><strong>{mod.name}</strong><small>{mod.note}</small></div>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
