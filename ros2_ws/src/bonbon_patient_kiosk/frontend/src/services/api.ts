export type ApiEnvelope<T> = { success: boolean; data?: T; error?: string; timestamp: number };

export type SessionInfo = {
  session_id: string;
  language: string;
  kiosk_id: string;
  created_at: number;
  last_activity_at: number;
  consent_given: boolean;
  privacy_mode_active: boolean;
};

export type Department = { department_id: string; name: string; floor: string; named_location: string; description: string };
export type Doctor = { doctor_id: string; display_name: string; department_id: string; named_location: string; languages: string[] };
export type AvailabilitySlot = { slot_id: string; doctor_id: string; start_ts: number; end_ts: number; is_available: boolean };
export type Appointment = { appointment_id: string; session_id: string; doctor_id: string; slot_id: string; reason: string; status: string; created_at: number };

export type QueueToken = {
  token_id: string; token_code: string; session_id: string; department_id: string;
  priority: string; position: number; estimated_wait_min: number; status: string; created_at: number;
};
export type QueueStatus = { token: QueueToken; ahead_count: number; department_name: string };

export type IntakeForm = {
  session_id: string; full_name: string; date_of_birth: string; contact_phone: string;
  contact_email?: string; visit_reason: string; symptoms: string[]; allergies: string[];
  current_medications: string[]; preferred_language: string; emergency_contact_name?: string;
  emergency_contact_phone?: string; insurance_provider?: string; insurance_id?: string; is_red_flag: boolean;
};

export type ChatQueryResponse = {
  response_text: string; status: string; confidence: number;
  suggested_department_id: string | null; is_emergency_escalation: boolean;
};

export type WayfindingResponse = { mode: string; named_location: string; accepted: boolean; message: string; directions_summary?: string };

export type NamedLocationLabel = {
  label_id: string; name: string; display_label: string; category: string;
  map_x: number; map_y: number; map_yaw: number; notes: string; created_at: number; updated_at: number;
};

export type LoginResponse = { access_token: string; token_type: string; expires_in: number; role: string };

export type QueueTokenView = { token_id: string; token_code: string; priority: string; position: number; estimated_wait_min: number; created_at: number };
export type QueueDepartmentView = { department_id: string; department_name: string; tokens: QueueTokenView[] };
export type AppointmentView = { appointment_id: string; doctor_name: string; department_name: string; start_ts: number | null; status: string };
export type IntakeAlertView = { intake_id: string; full_name: string; visit_reason: string; is_red_flag: boolean; submitted_at: number };
export type EscalationView = { action: string; detail: string; outcome: string; timestamp: number };
export type FeedbackItemView = { rating: number; comment: string; submitted_at: number };
export type FeedbackSummaryView = { average_rating: number; count: number; recent: FeedbackItemView[] };
export type DashboardOverview = {
  queue: QueueDepartmentView[];
  appointments_today: AppointmentView[];
  recent_intake: IntakeAlertView[];
  recent_escalations: EscalationView[];
  feedback: FeedbackSummaryView;
};

export class ApiClient {
  private baseUrl: string;
  private staffToken: string;

  constructor(baseUrl: string, staffToken = "") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.staffToken = staffToken;
  }

  setStaffToken(token: string) { this.staffToken = token; }

  async health() {
    return this.request<{ status: string; timestamp: number }>("/health", { auth: false });
  }

  // ── Session ────────────────────────────────────────────────────────────────
  async createSession(language: string, kioskId = "kiosk-1") {
    return this.request<SessionInfo>("/api/v1/session", { method: "POST", body: { language, kiosk_id: kioskId }, auth: false });
  }
  async heartbeat(sessionId: string) {
    return this.request<SessionInfo>(`/api/v1/session/${sessionId}/heartbeat`, { method: "POST", auth: false });
  }
  async endSession(sessionId: string) {
    return this.request<{ ended: boolean }>(`/api/v1/session/${sessionId}/end`, { method: "POST", auth: false });
  }

  // ── Consent ─────────────────────────────────────────────────────────────────
  async getDisclosure() {
    return this.request<{ text: string; policy_version: string }>("/api/v1/consent/disclosure", { auth: false });
  }
  async recordConsent(sessionId: string, given: boolean) {
    return this.request<SessionInfo>("/api/v1/consent", {
      method: "POST", auth: false,
      body: { session_id: sessionId, consent_given: given, jurisdiction: "default", policy_version: "1.0" },
    });
  }

  // ── Patient lookup ───────────────────────────────────────────────────────────
  async lookupPatient(identifier: string, identifierType = "phone") {
    return this.request<{ patient_id: string; display_name: string }>("/api/v1/patients/lookup", {
      method: "POST", auth: false, body: { identifier, identifier_type: identifierType },
    });
  }

  // ── Intake ────────────────────────────────────────────────────────────────
  async saveDraft(form: IntakeForm) {
    return this.request<{ saved: boolean; is_red_flag: boolean }>(`/api/v1/intake/${form.session_id}/draft`, {
      method: "PUT", auth: false, body: form,
    });
  }
  async getDraft(sessionId: string) {
    return this.request<IntakeForm>(`/api/v1/intake/${sessionId}/draft`, { auth: false });
  }
  async submitIntake(sessionId: string) {
    return this.request<{ intake_id: string; is_red_flag: boolean }>(`/api/v1/intake/${sessionId}/submit`, {
      method: "POST", auth: false,
    });
  }

  // ── Appointments ──────────────────────────────────────────────────────────
  async listDepartments() {
    return this.request<Department[]>("/api/v1/appointments/departments", { auth: false });
  }
  async listDoctors(departmentId?: string) {
    const q = departmentId ? `?department_id=${encodeURIComponent(departmentId)}` : "";
    return this.request<Doctor[]>(`/api/v1/appointments/doctors${q}`, { auth: false });
  }
  async listSlots(doctorId: string) {
    return this.request<AvailabilitySlot[]>(`/api/v1/appointments/doctors/${doctorId}/slots`, { auth: false });
  }
  async bookAppointment(sessionId: string, doctorId: string, slotId: string, reason: string) {
    return this.request<Appointment>("/api/v1/appointments", {
      method: "POST", auth: false, body: { session_id: sessionId, doctor_id: doctorId, slot_id: slotId, reason },
    });
  }
  async cancelAppointment(appointmentId: string, reason = "") {
    return this.request<Appointment>("/api/v1/appointments/cancel", { method: "POST", auth: false, body: { appointment_id: appointmentId, reason } });
  }

  // ── Queue ─────────────────────────────────────────────────────────────────
  async checkIn(sessionId: string, departmentId: string, reason: string, priority = "normal") {
    return this.request<QueueStatus>("/api/v1/queue/check-in", {
      method: "POST", auth: false, body: { session_id: sessionId, department_id: departmentId, reason, priority },
    });
  }
  async getTokenStatus(tokenId: string) {
    return this.request<QueueStatus>(`/api/v1/queue/tokens/${tokenId}`, { auth: false });
  }

  // ── Chat / wayfinding ─────────────────────────────────────────────────────
  async chatQuery(sessionId: string, queryText: string) {
    return this.request<ChatQueryResponse>("/api/v1/chat/query", { method: "POST", auth: false, body: { session_id: sessionId, query_text: queryText } });
  }
  async wayfind(sessionId: string, namedLocation: string, mode: "directions" | "escort") {
    return this.request<WayfindingResponse>("/api/v1/navigation/wayfind", {
      method: "POST", auth: false, body: { session_id: sessionId, named_location: namedLocation, mode },
    });
  }
  async panic(sessionId: string, reason: string) {
    return this.request<{ acknowledged: boolean }>(`/api/v1/panic?session_id=${encodeURIComponent(sessionId)}&reason=${encodeURIComponent(reason)}`, {
      method: "POST", auth: false,
    });
  }

  // ── Feedback ──────────────────────────────────────────────────────────────
  async submitFeedback(sessionId: string, rating: number, comment: string) {
    return this.request<{ feedback_id: string }>("/api/v1/feedback", { method: "POST", auth: false, body: { session_id: sessionId, rating, comment } });
  }

  // ── Staff auth + dashboard + facility map ────────────────────────────────
  async staffLogin(username: string, password: string) {
    const result = await this.request<LoginResponse>("/api/v1/auth/login", { method: "POST", auth: false, body: { username, password } });
    this.setStaffToken(result.access_token);
    return result;
  }
  async getDashboardOverview() {
    return this.request<DashboardOverview>("/api/v1/staff/dashboard/overview");
  }
  async markTokenServed(tokenId: string) {
    return this.request<Record<string, unknown>>(`/api/v1/queue/tokens/${tokenId}/serve`, { method: "POST" });
  }
  async listFacilityLabels() {
    return this.request<NamedLocationLabel[]>("/api/v1/facility-map/labels");
  }
  async createFacilityLabel(payload: Omit<NamedLocationLabel, "label_id" | "created_at" | "updated_at">) {
    return this.request<NamedLocationLabel>("/api/v1/facility-map/labels", { method: "POST", body: payload });
  }
  async updateFacilityLabel(labelId: string, payload: Omit<NamedLocationLabel, "label_id" | "created_at" | "updated_at">) {
    return this.request<NamedLocationLabel>(`/api/v1/facility-map/labels/${labelId}`, { method: "PUT", body: payload });
  }
  async deleteFacilityLabel(labelId: string) {
    return this.request<{ deleted: boolean }>(`/api/v1/facility-map/labels/${labelId}`, { method: "DELETE" });
  }
  async exportFacilityMap() {
    return this.request<{ yaml_text: string; label_count: number }>("/api/v1/facility-map/export");
  }

  // ── Internal ──────────────────────────────────────────────────────────────
  private async request<T>(path: string, options: { method?: "GET" | "POST" | "PUT" | "DELETE"; body?: unknown; auth?: boolean } = {}): Promise<T> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (options.auth !== false && this.staffToken) headers.Authorization = `Bearer ${this.staffToken}`;
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
