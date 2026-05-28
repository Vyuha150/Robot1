export type ApiEnvelope<T> = {
  success: boolean;
  data?: T;
  error?: string;
  timestamp: number;
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  role: string;
};

export type LlmProvider = "ollama" | "openai_compatible";
export type ProviderName = "ollama" | "openai_compatible" | "deepgram" | "elevenlabs" | "roboflow";

export type LlmTestResponse = {
  provider: LlmProvider;
  model: string;
  response_text: string;
  latency_ms: number;
};

export type ProviderCatalogItem = {
  id: ProviderName;
  label: string;
  required_secret: boolean;
  default_base_url: string;
  default_model: string;
  tests: string[];
};

export type ProviderCheckResponse = {
  provider: ProviderName;
  ok: boolean;
  latency_ms: number;
  base_url?: string;
  models?: string[];
  voices?: string[];
};

export type TestbenchStatus = {
  speech: Record<string, unknown>;
  vision: Record<string, unknown>;
  llm: Record<string, unknown>;
  tts: Record<string, unknown>;
  system: Record<string, unknown>;
  safety: Record<string, unknown>;
};

export type TestSession = {
  session_id: string;
  title: string;
  scenario: string;
  started_at: number;
  updated_at: number;
  events: TestSessionEvent[];
  analysis?: Record<string, unknown>;
};

export type TestSessionSummary = Omit<TestSession, "events"> & {
  event_count: number;
};

export type TestSessionEvent = {
  event_id: string;
  timestamp: number;
  module: string;
  event_type: string;
  status: "pass" | "fail" | "warn" | "info";
  summary: string;
  metrics: Record<string, unknown>;
  payload: Record<string, unknown>;
  failure_label: string;
};

export class ApiClient {
  private baseUrl: string;
  private token: string;

  constructor(baseUrl: string, token = "") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
  }

  setBaseUrl(url: string) { this.baseUrl = url.replace(/\/$/, ""); }
  setToken(token: string) { this.token = token; }

  // ── Health & auth ──────────────────────────────────────────────────────────
  async health() {
    return this.request<{ status: string; robot_online: boolean; timestamp: number }>("/health", { auth: false });
  }

  async login(username: string, password: string) {
    const result = await this.request<LoginResponse>("/api/v1/auth/login", {
      method: "POST", body: { username, password }, auth: false,
    });
    if (result.access_token) this.setToken(result.access_token);
    return result;
  }

  // ── Robot status ───────────────────────────────────────────────────────────
  async robotStatus() {
    return this.request<Record<string, unknown>>("/api/v1/robot/status");
  }

  async getSafetyState() {
    return this.request<Record<string, unknown>>("/api/v1/robot/safety-state");
  }

  async getBatteryStatus() {
    return this.request<Record<string, unknown>>("/api/v1/robot/battery");
  }

  async getNavigationStatus() {
    return this.request<Record<string, unknown>>("/api/v1/robot/navigation-status");
  }

  // ── Diagnostics ────────────────────────────────────────────────────────────
  async diagnostics() {
    return this.request<Record<string, unknown>>("/api/v1/diagnostics/modules");
  }

  async getHealthSummary() {
    return this.request<Record<string, unknown>>("/api/v1/diagnostics/health");
  }

  // ── Commands ───────────────────────────────────────────────────────────────
  async speak(text: string, emotion = "neutral", language = "en", priority = "normal") {
    return this.request<Record<string, unknown>>("/api/v1/robot/commands/speak", {
      method: "POST", body: { text, language, priority, emotion },
    });
  }

  async emergencyStop(reason: string) {
    return this.request<Record<string, unknown>>("/api/v1/robot/commands/emergency_stop", {
      method: "POST", body: { reason },
    });
  }

  async navigate(goal_x: number, goal_y: number, goal_yaw = 0.0, speed_limit_mps?: number) {
    return this.request<Record<string, unknown>>("/api/v1/robot/commands/navigate", {
      method: "POST", body: { goal_x, goal_y, goal_yaw, speed_limit_mps, allow_replanning: true },
    });
  }

  async pauseNavigation(reason = "operator_pause") {
    return this.request<Record<string, unknown>>("/api/v1/robot/commands/pause", {
      method: "POST", body: { reason },
    });
  }

  async resumeNavigation() {
    return this.request<Record<string, unknown>>("/api/v1/robot/commands/resume", {
      method: "POST", body: {},
    });
  }

  async dock() {
    return this.request<Record<string, unknown>>("/api/v1/robot/commands/dock", {
      method: "POST", body: {},
    });
  }

  async cancelTask() {
    return this.request<Record<string, unknown>>("/api/v1/robot/commands/cancel", {
      method: "POST", body: {},
    });
  }

  // ── LLM ───────────────────────────────────────────────────────────────────
  async llmTest(body: {
    provider: LlmProvider; prompt: string; model: string;
    base_url: string; api_key?: string; timeout_sec?: number;
  }) {
    return this.request<LlmTestResponse>("/api/v1/llm/test-query", { method: "POST", body });
  }

  // ── Testbench ─────────────────────────────────────────────────────────────
  async testbenchStatus() {
    return this.request<TestbenchStatus>("/api/v1/testbench/status");
  }

  async updateClientOutput(module: string, status: "idle" | "ok" | "warn" | "error", payload: Record<string, unknown>) {
    return this.request<Record<string, unknown>>("/api/v1/testbench/client-output", {
      method: "POST", body: { module, status, payload },
    });
  }

  async providerCatalog() {
    return this.request<{ providers: ProviderCatalogItem[]; secret_policy: string }>("/api/v1/testbench/providers");
  }

  async checkProvider(body: { provider: ProviderName; base_url: string; api_key?: string; model?: string; timeout_sec?: number }) {
    return this.request<ProviderCheckResponse>("/api/v1/testbench/providers/check", { method: "POST", body });
  }

  // ── Sessions ──────────────────────────────────────────────────────────────
  async startSession(body: { title: string; scenario: string; operator_notes: string }) {
    return this.request<TestSession>("/api/v1/testbench/sessions", { method: "POST", body });
  }

  async listSessions() {
    return this.request<{ sessions: TestSessionSummary[] }>("/api/v1/testbench/sessions");
  }

  async appendSessionEvent(sessionId: string, body: {
    module: string; event_type: string; status: "pass" | "fail" | "warn" | "info";
    summary: string; metrics?: Record<string, unknown>; payload?: Record<string, unknown>; failure_label?: string;
  }) {
    return this.request<TestSessionEvent>(`/api/v1/testbench/sessions/${sessionId}/events`, { method: "POST", body });
  }

  async analyseSession(sessionId: string) {
    return this.request<Record<string, unknown>>(`/api/v1/testbench/sessions/${sessionId}/analysis`, { method: "POST" });
  }

  // ── WebSocket ─────────────────────────────────────────────────────────────
  openWebSocket(channel: "robot-status" | "safety-events" | "diagnostics", onMessage: (data: unknown) => void, onClose?: () => void): WebSocket {
    const wsUrl = `${this.baseUrl.replace(/^http/, "ws")}/ws/${channel}?token=${this.token}`;
    const ws = new WebSocket(wsUrl);
    ws.onmessage = (ev) => {
      try { onMessage(JSON.parse(ev.data as string)); } catch { /* ignore malformed */ }
    };
    if (onClose) ws.onclose = onClose;
    return ws;
  }

  // ── Internal request ──────────────────────────────────────────────────────
  private async request<T>(path: string, options: { method?: "GET" | "POST" | "PUT" | "DELETE"; body?: unknown; auth?: boolean } = {}): Promise<T> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (options.auth !== false && this.token) headers.Authorization = `Bearer ${this.token}`;
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const ct = response.headers.get("content-type") ?? "";
    const payload = ct.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>).detail ?? (payload as Record<string, unknown>).error : payload;
      throw new Error(String(detail || `HTTP ${response.status}`));
    }
    if (typeof payload === "object" && payload !== null && "success" in payload) {
      const envelope = payload as ApiEnvelope<T>;
      if (!envelope.success) throw new Error(envelope.error || "Request failed");
      return envelope.data as T;
    }
    return payload as T;
  }
}
