import type {
  Analysis,
  AuthUser,
  Catalog,
  GameDetail,
  GameSummary,
  Player,
  PlayerStats,
  Questionnaire,
  QuestionnaireComparison,
  QuestionnaireJob,
  SampleJob,
  Simulation,
  Snapshot,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  const text = await response.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (response.status === 401 && !path.startsWith("/api/auth/")) {
    window.dispatchEvent(new Event("werewolf:unauthorized"));
  }
  if (!response.ok) {
    const message =
      data && typeof data === "object" && "error" in data
        ? String((data as { error: unknown }).error)
        : `请求失败（${response.status}）`;
    throw new Error(message);
  }
  return data as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  me: () => request<{ user: AuthUser }>("/api/auth/me"),

  lookup: (email: string) =>
    post<{ registered: boolean }>("/api/auth/lookup", { email }),

  requestCode: (email: string, invite_code = "") =>
    post<{
      ok: boolean;
      registered: boolean;
      expires_in: number;
      resend_after: number;
      debug_code?: string;
    }>("/api/auth/request-code", { email, invite_code }),

  verify: (email: string, code: string, invite_code = "") =>
    post<{ ok: boolean; user: AuthUser; registered: boolean }>("/api/auth/verify", {
      email,
      code,
      invite_code,
    }),

  logout: () => post<{ ok: boolean }>("/api/auth/logout", {}),

  health: () =>
    request<{
      ok: boolean;
      capabilities: {
        deepseek_configured: boolean;
        audiencelib_configured: boolean;
        model: string;
        db: string;
      };
      players: number;
    }>("/api/health"),

  catalog: (country?: string) =>
    request<Catalog>(`/api/catalog${country ? `?country=${country}` : ""}`),

  playerStats: () => request<PlayerStats>("/api/players/stats"),

  players: (params: {
    type?: string;
    q?: string;
    EI?: string;
    SN?: string;
    TF?: string;
    JP?: string;
    limit?: number;
    offset?: number;
    tested?: boolean;
    questionnaire_id?: string;
  }) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") search.set(key, String(value));
    });
    return request<{ players: Player[]; total: number; types: Record<string, number> }>(
      `/api/players?${search.toString()}`,
    );
  },

  sample: (body: {
    country: string;
    age_min: number | null;
    age_max: number | null;
    gender: string;
    count: number;
    education?: string[];
    occupation_group?: string[];
    urbanicity?: string;
    consumption_style?: string[];
  }) => post<{ job_id: string }>("/api/players/sample", body),

  sampleJob: (jobId: string) => request<SampleJob>(`/api/players/sample/${jobId}`),

  questionnaires: () =>
    request<{ items: Questionnaire[]; active_id: string }>("/api/questionnaires"),

  questionnaireTemplate: () =>
    request<{ definition: Record<string, unknown> }>("/api/questionnaires/template"),

  questionnaireConversionPrompt: () =>
    request<{ filename: string; content: string }>("/api/questionnaires/conversion-prompt"),

  activateQuestionnaire: (id: string) =>
    post<{ ok: boolean; active_id: string }>(`/api/questionnaires/${id}/activate`, {}),

  uploadQuestionnaire: (definition: Record<string, unknown>, name?: string) =>
    post<{ questionnaire: Questionnaire }>("/api/questionnaires", { definition, name }),

  deleteQuestionnaire: (id: string) =>
    request<{ deleted: boolean }>(`/api/questionnaires/${id}`, { method: "DELETE" }),

  testQuestionnaire: (id: string) =>
    post<{ job_id: string }>(`/api/questionnaires/${id}/test-all`, {}),

  questionnaireJob: (id: string) =>
    request<QuestionnaireJob>(`/api/questionnaires/jobs/${id}`),

  compareQuestionnaires: (left: string, right: string) =>
    request<QuestionnaireComparison>(`/api/questionnaires/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`),

  deletePlayers: (ids: string[]) =>
    post<{ removed: number }>("/api/players/delete", { ids }),

  retestPlayer: (id: string) =>
    post<{ player: Player }>(`/api/players/${id}/retest`, {}),

  createSimulation: (body: {
    player_count?: number;
    variable_roles: Record<string, number>;
    fixed_assignments: { role: string; player_id: string }[];
    games: number;
    concurrency?: number;
    seed?: number;
  }) => post<{ simulation: Simulation }>("/api/simulations", body),

  start: (id: string) =>
    post<{ snapshot: Snapshot }>(`/api/simulations/${id}/start`, {}),
  pause: (id: string) =>
    post<{ snapshot: Snapshot }>(`/api/simulations/${id}/pause`, {}),
  resume: (id: string) =>
    post<{ snapshot: Snapshot }>(`/api/simulations/${id}/resume`, {}),
  stop: (id: string) =>
    post<{ snapshot: Snapshot }>(`/api/simulations/${id}/stop`, {}),

  simulation: (id: string) =>
    request<{ simulation: Simulation; snapshot: Snapshot }>(`/api/simulations/${id}`),

  live: (id: string) => request<Snapshot>(`/api/simulations/${id}/live`),

  games: (id: string, params?: { limit?: number; offset?: number; order?: string }) => {
    const search = new URLSearchParams();
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.offset) search.set("offset", String(params.offset));
    if (params?.order) search.set("order", params.order);
    return request<{ games: GameSummary[]; total: number }>(
      `/api/simulations/${id}/games?${search.toString()}`,
    );
  },

  game: (id: string, no: number) =>
    request<GameDetail>(`/api/simulations/${id}/games/${no}`),

  analysis: (id: string) => request<Analysis>(`/api/simulations/${id}/analysis`),

  history: () => request<{ items: Simulation[] }>("/api/history"),

  deleteSimulation: (id: string) =>
    request<{ deleted: boolean }>(`/api/simulations/${id}`, { method: "DELETE" }),
};
