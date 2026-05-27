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

export type LlmTestResponse = {
  provider: LlmProvider;
  model: string;
  response_text: string;
  latency_ms: number;
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
