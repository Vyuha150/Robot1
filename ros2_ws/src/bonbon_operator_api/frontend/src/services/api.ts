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

  setBaseUrl(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  setToken(token: string) {
    this.token = token;
  }

  async health() {
    return this.request<{ status: string; robot_online: boolean; timestamp: number }>("/health", {
      auth: false
    });
  }

  async login(username: string, password: string) {
    const result = await this.request<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: { username, password },
      auth: false
    });
    if (result.access_token) {
      this.setToken(result.access_token);
    }
    return result;
  }

  async robotStatus() {
    return this.request<Record<string, unknown>>("/api/v1/robot/status");
  }

  async diagnostics() {
    return this.request<Record<string, unknown>>("/api/v1/diagnostics/modules");
  }

  async speak(text: string) {
    return this.request<Record<string, unknown>>("/api/v1/robot/commands/speak", {
      method: "POST",
      body: { text, language: "en", priority: "normal" }
    });
  }

  async emergencyStop(reason: string) {
    return this.request<Record<string, unknown>>("/api/v1/robot/commands/emergency_stop", {
      method: "POST",
      body: { reason }
    });
  }

  async llmTest(body: {
    provider: LlmProvider;
    prompt: string;
    model: string;
    base_url: string;
    api_key?: string;
    timeout_sec?: number;
  }) {
    return this.request<LlmTestResponse>("/api/v1/llm/test-query", {
      method: "POST",
      body
    });
  }

  async testbenchStatus() {
    return this.request<TestbenchStatus>("/api/v1/testbench/status");
  }

  async updateClientOutput(module: string, status: "idle" | "ok" | "warn" | "error", payload: Record<string, unknown>) {
    return this.request<Record<string, unknown>>("/api/v1/testbench/client-output", {
      method: "POST",
      body: { module, status, payload }
    });
  }

  async providerCatalog() {
    return this.request<{ providers: ProviderCatalogItem[]; secret_policy: string }>("/api/v1/testbench/providers");
  }

  async checkProvider(body: {
    provider: ProviderName;
    base_url: string;
    api_key?: string;
    model?: string;
    timeout_sec?: number;
  }) {
    return this.request<ProviderCheckResponse>("/api/v1/testbench/providers/check", {
      method: "POST",
      body
    });
  }

  async startSession(body: { title: string; scenario: string; operator_notes: string }) {
    return this.request<TestSession>("/api/v1/testbench/sessions", {
      method: "POST",
      body
    });
  }

  async listSessions() {
    return this.request<{ sessions: TestSessionSummary[] }>("/api/v1/testbench/sessions");
  }

  async appendSessionEvent(sessionId: string, body: {
    module: string;
    event_type: string;
    status: "pass" | "fail" | "warn" | "info";
    summary: string;
    metrics?: Record<string, unknown>;
    payload?: Record<string, unknown>;
    failure_label?: string;
  }) {
    return this.request<TestSessionEvent>(`/api/v1/testbench/sessions/${sessionId}/events`, {
      method: "POST",
      body
    });
  }

  async analyseSession(sessionId: string) {
    return this.request<Record<string, unknown>>(`/api/v1/testbench/sessions/${sessionId}/analysis`, {
      method: "POST"
    });
  }

  private async request<T>(
    path: string,
    options: {
      method?: "GET" | "POST" | "PUT" | "DELETE";
      body?: unknown;
      auth?: boolean;
    } = {}
  ): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json"
    };
    if (options.auth !== false && this.token) {
      headers.Authorization = `Bearer ${this.token}`;
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body)
    });
    const contentType = response.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();

    if (!response.ok) {
      const detail = typeof payload === "object" && payload !== null ? payload.detail ?? payload.error : payload;
      throw new Error(String(detail || `HTTP ${response.status}`));
    }
    if (typeof payload === "object" && payload !== null && "success" in payload) {
      const envelope = payload as ApiEnvelope<T>;
      if (!envelope.success) {
        throw new Error(envelope.error || "Request failed");
      }
      return envelope.data as T;
    }
    return payload as T;
  }
}
