import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { ApiClient, LlmProvider } from "./services/api";

type LogEntry = {
  time: string;
  level: "ok" | "warn" | "error" | "info";
  text: string;
};

type VideoMetrics = {
  fps: number;
  brightness: number;
  contrast: number;
  edgeScore: number;
  motion: number;
};

const now = () => new Date().toLocaleTimeString();

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

export default function App() {
  const [apiBaseUrl, setApiBaseUrl] = useState(localStorage.getItem("bonbon.apiBaseUrl") || "http://127.0.0.1:8080");
  const [token, setToken] = useState(localStorage.getItem("bonbon.token") || "");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [backendStatus, setBackendStatus] = useState<"unknown" | "online" | "offline">("unknown");
  const [robotOnline, setRobotOnline] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);

  const api = useMemo(() => new ApiClient(apiBaseUrl, token), [apiBaseUrl, token]);

  const addLog = (level: LogEntry["level"], text: string) => {
    setLogs((items) => [{ time: now(), level, text }, ...items].slice(0, 12));
  };

  useEffect(() => {
    localStorage.setItem("bonbon.apiBaseUrl", apiBaseUrl);
  }, [apiBaseUrl]);

  useEffect(() => {
    if (token) {
      localStorage.setItem("bonbon.token", token);
    } else {
      localStorage.removeItem("bonbon.token");
    }
  }, [token]);

  const checkBackend = async () => {
    try {
      const health = await api.health();
      setBackendStatus("online");
      setRobotOnline(Boolean(health.robot_online));
      addLog("ok", `Backend online. Robot online=${Boolean(health.robot_online)}`);
    } catch (error) {
      setBackendStatus("offline");
      setRobotOnline(false);
      addLog("error", `Backend health check failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const login = async () => {
    try {
      const result = await api.login(username, password);
      setToken(result.access_token);
      addLog("ok", `Authenticated as ${username} (${result.role})`);
    } catch (error) {
      addLog("error", `Login failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  useEffect(() => {
    void checkBackend();
    const id = window.setInterval(() => void checkBackend(), 15000);
    return () => window.clearInterval(id);
  }, [apiBaseUrl]);

  return (
    <main className="app-shell">
      <section className="hero panel">
        <div>
          <p className="eyebrow">BonBon local robot laboratory</p>
          <h1>Operator Test Cockpit</h1>
          <p className="subtitle">
            Visual checks for camera, microphone, image processing, LLM responses, TTS commands, safety status, and
            dashboard API connectivity from one localhost web instance.
          </p>
        </div>
        <div className="status-stack">
          <StatusPill label="Backend" value={backendStatus} tone={backendStatus === "online" ? "good" : backendStatus === "offline" ? "bad" : "idle"} />
          <StatusPill label="Robot bridge" value={robotOnline ? "online" : "offline/sim"} tone={robotOnline ? "good" : "warn"} />
          <StatusPill label="Session" value={token ? "authenticated" : "guest"} tone={token ? "good" : "idle"} />
        </div>
      </section>

      <section className="grid two">
        <ConnectionPanel
          apiBaseUrl={apiBaseUrl}
          setApiBaseUrl={setApiBaseUrl}
          username={username}
          setUsername={setUsername}
          password={password}
          setPassword={setPassword}
          login={login}
          checkBackend={checkBackend}
          clearToken={() => {
            setToken("");
            addLog("info", "Cleared dashboard token");
          }}
        />
        <CommandPanel api={api} addLog={addLog} disabled={!token} />
      </section>

      <section className="grid media-grid">
        <CameraPanel addLog={addLog} />
        <AudioPanel addLog={addLog} />
      </section>

      <section className="grid two">
        <LlmPanel api={api} addLog={addLog} disabled={!token} />
        <SystemPanel api={api} addLog={addLog} disabled={!token} />
      </section>

      <section className="panel">
        <div className="section-title">
          <span>Event Console</span>
          <small>latest local browser/API actions</small>
        </div>
        <div className="log-list">
          {logs.length === 0 ? <p className="muted">No events yet. Run a camera, audio, backend, or LLM check.</p> : null}
          {logs.map((item, index) => (
            <div className={`log-line ${item.level}`} key={`${item.time}-${index}`}>
              <span>{item.time}</span>
              <strong>{item.level.toUpperCase()}</strong>
              <p>{item.text}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function StatusPill({ label, value, tone }: { label: string; value: string; tone: "good" | "warn" | "bad" | "idle" }) {
  return (
    <div className={`status-pill ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ConnectionPanel(props: {
  apiBaseUrl: string;
  setApiBaseUrl: (value: string) => void;
  username: string;
  setUsername: (value: string) => void;
  password: string;
  setPassword: (value: string) => void;
  login: () => Promise<void>;
  checkBackend: () => Promise<void>;
  clearToken: () => void;
}) {
  return (
    <section className="panel">
      <div className="section-title">
        <span>Backend Connection</span>
        <small>FastAPI + safety-gated robot API</small>
      </div>
      <label>
        API base URL
        <input value={props.apiBaseUrl} onChange={(event) => props.setApiBaseUrl(event.target.value)} />
      </label>
      <div className="inline">
        <label>
          Username
          <input value={props.username} onChange={(event) => props.setUsername(event.target.value)} />
        </label>
        <label>
          Password
          <input
            type="password"
            value={props.password}
            onChange={(event) => props.setPassword(event.target.value)}
            placeholder="runtime only"
          />
        </label>
      </div>
      <div className="button-row">
        <button onClick={() => void props.checkBackend()}>Check backend</button>
        <button onClick={() => void props.login()} className="primary">Login</button>
        <button onClick={props.clearToken} className="ghost">Clear token</button>
      </div>
      <p className="hint">Secrets stay in browser memory/local storage only for this local test session. Never commit `.env`.</p>
    </section>
  );
}

function CameraPanel({ addLog }: { addLog: (level: LogEntry["level"], text: string) => void }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const previousFrameRef = useRef<Uint8ClampedArray | null>(null);
  const animationRef = useRef<number | null>(null);
  const [running, setRunning] = useState(false);
  const [metrics, setMetrics] = useState<VideoMetrics>({ fps: 0, brightness: 0, contrast: 0, edgeScore: 0, motion: 0 });
  const [snapshot, setSnapshot] = useState("");

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: false });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setRunning(true);
      addLog("ok", "Camera stream started");
      processFrames();
    } catch (error) {
      addLog("error", `Camera unavailable: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const stop = () => {
    if (animationRef.current) window.cancelAnimationFrame(animationRef.current);
    const stream = videoRef.current?.srcObject as MediaStream | null;
    stream?.getTracks().forEach((track) => track.stop());
    if (videoRef.current) videoRef.current.srcObject = null;
    setRunning(false);
    addLog("info", "Camera stream stopped");
  };

  const processFrames = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return;
    canvas.width = 320;
    canvas.height = 180;
    let last = performance.now();
    const loop = () => {
      if (!video.videoWidth) {
        animationRef.current = window.requestAnimationFrame(loop);
        return;
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const frame = context.getImageData(0, 0, canvas.width, canvas.height);
      const stats = analyseFrame(frame.data, previousFrameRef.current, canvas.width, canvas.height);
      previousFrameRef.current = new Uint8ClampedArray(frame.data);
      const current = performance.now();
      const fps = 1000 / Math.max(current - last, 1);
      last = current;
      setMetrics({ ...stats, fps: Number(fps.toFixed(1)) });
      animationRef.current = window.requestAnimationFrame(loop);
    };
    loop();
  };

  const capture = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    setSnapshot(canvas.toDataURL("image/png"));
    addLog("ok", "Captured processed camera frame");
  };

  useEffect(() => () => stop(), []);

  return (
    <section className="panel camera-panel">
      <div className="section-title">
        <span>Live Camera + Video Processing</span>
        <small>browser camera, frame quality, motion, edges</small>
      </div>
      <div className="video-stage">
        <video ref={videoRef} playsInline muted />
        <div className="scanline" />
        <canvas ref={canvasRef} />
      </div>
      <div className="button-row">
        <button onClick={() => void start()} disabled={running} className="primary">Start camera</button>
        <button onClick={stop} disabled={!running}>Stop</button>
        <button onClick={capture} disabled={!running}>Capture processed frame</button>
      </div>
      <MetricGrid metrics={metrics} />
      {snapshot ? <img className="snapshot" src={snapshot} alt="Captured processed frame" /> : null}
    </section>
  );
}

function analyseFrame(data: Uint8ClampedArray, previous: Uint8ClampedArray | null, width: number, height: number) {
  let sum = 0;
  let sumSq = 0;
  let motion = 0;
  let edges = 0;
  const pixels = width * height;
  for (let index = 0; index < data.length; index += 4) {
    const y = 0.2126 * data[index] + 0.7152 * data[index + 1] + 0.0722 * data[index + 2];
    sum += y;
    sumSq += y * y;
    if (previous) {
      motion += Math.abs(data[index] - previous[index]);
    }
    const next = index + 4;
    if (next < data.length) {
      edges += Math.abs(y - (0.2126 * data[next] + 0.7152 * data[next + 1] + 0.0722 * data[next + 2]));
    }
  }
  const mean = sum / pixels;
  const variance = Math.max(sumSq / pixels - mean * mean, 0);
  return {
    brightness: Number(((mean / 255) * 100).toFixed(1)),
    contrast: Number((Math.sqrt(variance) / 2.55).toFixed(1)),
    edgeScore: Number(clamp(edges / pixels / 2.55, 0, 100).toFixed(1)),
    motion: Number(clamp(motion / pixels / 2.55, 0, 100).toFixed(1))
  };
}

function MetricGrid({ metrics }: { metrics: VideoMetrics }) {
  return (
    <div className="metric-grid">
      <Metric label="FPS" value={metrics.fps.toFixed(1)} />
      <Metric label="Brightness" value={`${metrics.brightness}%`} />
      <Metric label="Contrast" value={`${metrics.contrast}%`} />
      <Metric label="Edges" value={`${metrics.edgeScore}%`} />
      <Metric label="Motion" value={`${metrics.motion}%`} />
    </div>
  );
}

function AudioPanel({ addLog }: { addLog: (level: LogEntry["level"], text: string) => void }) {
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationRef = useRef<number | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [level, setLevel] = useState(0);
  const [peak, setPeak] = useState(0);
  const [heard, setHeard] = useState(false);

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      const context = new AudioContext();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      audioContextRef.current = context;
      analyserRef.current = analyser;
      streamRef.current = stream;
      addLog("ok", "Microphone monitor started");
      meterLoop();
    } catch (error) {
      addLog("error", `Microphone unavailable: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const stop = () => {
    if (animationRef.current) window.cancelAnimationFrame(animationRef.current);
    streamRef.current?.getTracks().forEach((track) => track.stop());
    void audioContextRef.current?.close();
    setLevel(0);
    addLog("info", "Microphone monitor stopped");
  };

  const meterLoop = () => {
    const analyser = analyserRef.current;
    if (!analyser) return;
    const samples = new Uint8Array(analyser.fftSize);
    const loop = () => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const sample of samples) {
        const normal = (sample - 128) / 128;
        sum += normal * normal;
      }
      const rms = Math.sqrt(sum / samples.length);
      const value = clamp(rms * 220, 0, 100);
      setLevel(value);
      setPeak((current) => Math.max(current * 0.96, value));
      if (value > 7) setHeard(true);
      animationRef.current = window.requestAnimationFrame(loop);
    };
    loop();
  };

  useEffect(() => () => stop(), []);

  return (
    <section className="panel">
      <div className="section-title">
        <span>Microphone + Speech Readiness</span>
        <small>visual audio-heard confirmation</small>
      </div>
      <div className="audio-orb" style={{ "--audio": `${level}%` } as CSSProperties}>
        <strong>{Math.round(level)}%</strong>
        <span>{heard ? "audio heard" : "waiting for sound"}</span>
      </div>
      <div className="meter">
        <div style={{ width: `${level}%` }} />
      </div>
      <div className="meter peak">
        <div style={{ width: `${peak}%` }} />
      </div>
      <div className="button-row">
        <button onClick={() => void start()} className="primary">Start microphone</button>
        <button onClick={stop}>Stop</button>
        <button onClick={() => { setHeard(false); setPeak(0); }}>Reset meter</button>
      </div>
      <p className="hint">This verifies browser microphone capture. ROS2 STT is tested separately through `/speech/command` and the speech node.</p>
    </section>
  );
}

function LlmPanel({ api, addLog, disabled }: { api: ApiClient; addLog: (level: LogEntry["level"], text: string) => void; disabled: boolean }) {
  const [provider, setProvider] = useState<LlmProvider>("ollama");
  const [baseUrl, setBaseUrl] = useState("http://localhost:11434");
  const [model, setModel] = useState("llama3.2:3b");
  const [apiKey, setApiKey] = useState("");
  const [prompt, setPrompt] = useState("Greet a hospital visitor and explain what BonBon can help with.");
  const [response, setResponse] = useState("");
  const [latency, setLatency] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const switchProvider = (next: LlmProvider) => {
    setProvider(next);
    if (next === "ollama") {
      setBaseUrl("http://localhost:11434");
      setModel("llama3.2:3b");
    } else {
      setBaseUrl("https://api.openai.com/v1");
      setModel("gpt-4o-mini");
    }
  };

  const runPrompt = async () => {
    setBusy(true);
    setResponse("");
    try {
      const result = await api.llmTest({
        provider,
        base_url: baseUrl,
        model,
        prompt,
        api_key: apiKey || undefined,
        timeout_sec: 60
      });
      setResponse(result.response_text);
      setLatency(result.latency_ms);
      addLog("ok", `LLM responded via ${result.provider}/${result.model} in ${result.latency_ms} ms`);
    } catch (error) {
      addLog("error", `LLM test failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="section-title">
        <span>Text + LLM Integration</span>
        <small>Ollama or OpenAI-compatible runtime test</small>
      </div>
      <div className="inline">
        <label>
          Provider
          <select value={provider} onChange={(event) => switchProvider(event.target.value as LlmProvider)}>
            <option value="ollama">Local Ollama</option>
            <option value="openai_compatible">OpenAI-compatible API</option>
          </select>
        </label>
        <label>
          Model
          <input value={model} onChange={(event) => setModel(event.target.value)} />
        </label>
      </div>
      <label>
        Base URL
        <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
      </label>
      <label>
        API key
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          placeholder={provider === "ollama" ? "not required for local Ollama" : "paste runtime key"}
        />
      </label>
      <label>
        Prompt
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
      </label>
      <div className="button-row">
        <button onClick={() => void runPrompt()} disabled={disabled || busy} className="primary">
          {busy ? "Thinking..." : "Run LLM test"}
        </button>
      </div>
      <div className="llm-response">
        <div>
          <strong>Response</strong>
          {latency !== null ? <span>{latency} ms</span> : null}
        </div>
        <p>{response || "No response yet."}</p>
      </div>
    </section>
  );
}

function CommandPanel({ api, addLog, disabled }: { api: ApiClient; addLog: (level: LogEntry["level"], text: string) => void; disabled: boolean }) {
  const [text, setText] = useState("Hello, I am BonBon. This is a local dashboard TTS test.");

  const speak = async () => {
    try {
      await api.speak(text);
      addLog("ok", "Speak command accepted by safety-gated API");
    } catch (error) {
      addLog("error", `Speak command failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const emergencyStop = async () => {
    try {
      await api.emergencyStop("operator dashboard local test");
      addLog("warn", "Emergency stop command accepted");
    } catch (error) {
      addLog("error", `Emergency stop failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <section className="panel command-panel">
      <div className="section-title">
        <span>Robot Command Tests</span>
        <small>safety-gated dashboard workflows</small>
      </div>
      <label>
        TTS phrase
        <textarea value={text} onChange={(event) => setText(event.target.value)} />
      </label>
      <div className="button-row">
        <button onClick={() => void speak()} disabled={disabled} className="primary">Send TTS</button>
        <button onClick={() => void emergencyStop()} disabled={disabled} className="danger">Emergency stop</button>
      </div>
      <p className="hint">Commands go through `SafetyCommandGate`; this dashboard does not bypass robot safety logic.</p>
    </section>
  );
}

function SystemPanel({ api, addLog, disabled }: { api: ApiClient; addLog: (level: LogEntry["level"], text: string) => void; disabled: boolean }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);

  const load = async (kind: "status" | "diagnostics") => {
    try {
      const result = kind === "status" ? await api.robotStatus() : await api.diagnostics();
      setData(result);
      addLog("ok", `Loaded ${kind}`);
    } catch (error) {
      addLog("error", `${kind} failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <section className="panel">
      <div className="section-title">
        <span>System + Module Health</span>
        <small>dashboard API snapshots</small>
      </div>
      <div className="button-row">
        <button onClick={() => void load("status")} disabled={disabled} className="primary">Robot status</button>
        <button onClick={() => void load("diagnostics")} disabled={disabled}>Diagnostics</button>
      </div>
      <pre className="json-view">{data ? JSON.stringify(data, null, 2) : "No system data loaded yet."}</pre>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
