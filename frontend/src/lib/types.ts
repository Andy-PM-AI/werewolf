export interface AuthUser {
  id: string;
  email: string;
  created_at: string;
  last_login_at: string | null;
}

export type RoleKey = "wolf" | "villager" | "seer" | "witch" | "hunter";
export type Winner = "wolf" | "good" | "draw";
export type SimStatus =
  | "created"
  | "running"
  | "paused"
  | "stopping"
  | "stopped"
  | "completed"
  | "error";

export interface Dims {
  E: number;
  I: number;
  S: number;
  N: number;
  T: number;
  F: number;
  J: number;
  P: number;
  E_pct: number;
  I_pct: number;
  S_pct: number;
  N_pct: number;
  T_pct: number;
  F_pct: number;
  J_pct: number;
  P_pct: number;
}

export interface Params {
  verbosity: number;
  challenge: number;
  evidence: number;
  ally_speed: number;
  conformity: number;
  jump_threshold: number;
  risk: number;
}

export interface Player {
  id: string;
  person_id: string;
  name: string;
  age: number | null;
  gender: string;
  country: string;
  province: string;
  city: string;
  urbanicity: string;
  education: string;
  occupation: string;
  occupation_group: string;
  income: number | null;
  marital: string;
  interests: string[];
  mbti: string;
  type_name?: string;
  questionnaire_id?: string;
  has_result?: boolean;
  result_created_at?: string | null;
  dims: Dims;
  params: Params;
  test_fallback: number;
  persona: string;
  profile_json?: {
    big_five?: Record<string, number | string>;
    risk_preference?: number | string;
    speech?: string;
    beliefs?: string[];
    life_story?: string;
  };
  source: string;
  created_at: string;
  answer_count?: number;
}

export interface PlayerStats {
  total: number;
  tested?: number;
  coverage?: number;
  types: Record<string, number>;
  type_count: number;
  dimensions: Record<string, Record<string, number>>;
  fallback: number;
  last_created: string | null;
  questionnaire_id?: string;
  questionnaire?: { id: string; name: string; kind?: string };
}

export interface Questionnaire {
  id: string;
  name: string;
  version: string;
  description: string;
  question_count: number;
  response_type?: "binary" | "likert5";
  scoring_mode?: "pole_majority" | "dimension_bands" | "total_bands" | "highest_dimension";
  is_builtin: number;
  created_at: string;
  created_by: string;
  tested: number;
  total: number;
  coverage: number;
  is_active: boolean;
}

export interface QuestionnaireJob {
  id: string;
  questionnaire_id: string;
  status: "running" | "done" | "error";
  phase: string;
  total: number;
  tested: number;
  skipped: number;
  failed: number;
  remaining: number;
  message: string;
  errors: { name?: string; error: string }[];
  started_at: string;
  finished_at: string | null;
}

export interface QuestionnaireComparison {
  left: { id: string; name: string };
  right: { id: string; name: string };
  total: number;
  same: number;
  different: number;
  same_rate: number;
  different_rate: number;
  same_players: { id: string; name: string; age: number | null; gender: string; left_result: string; right_result: string }[];
  distribution: {
    left_result: string;
    right_result: string;
    count: number;
    players: { id: string; name: string; age: number | null; gender: string; province: string; occupation: string }[];
  }[];
}

export interface CatalogCountry {
  code: string;
  name: string;
  default_release_id: string;
  sampling_quota: {
    limit: number;
    used: number;
    remaining: number;
    unit?: string;
  } | null;
  limits?: { max_people?: number; page_size?: number };
  items: {
    id: string;
    name: string;
    count: number;
    country_code: string;
    facets: Record<string, string[]>;
  }[];
}

export interface Catalog {
  countries: Record<string, CatalogCountry>;
  errors: { country: string; error: string }[];
  fetched_at: string;
}

export interface SampleJobPerson {
  name: string;
  age: number | null;
  gender: string;
  province: string;
  occupation: string;
  status: "pending" | "done" | "failed";
  mbti: string | null;
}

export interface SampleJob {
  id: string;
  status: "queued" | "running" | "done" | "error";
  phase: string;
  requested: number;
  tested: number;
  sampled: number;
  failed: number;
  added: {
    id: string;
    name: string;
    age: number | null;
    gender: string;
    mbti: string;
    type_name: string;
    fallback: boolean;
  }[];
  people: SampleJobPerson[];
  people_total?: number;
  added_count?: number;
  added_counts?: Record<string, number>;
  errors: { name?: string; error: string }[];
  errors_total?: number;
  message: string;
  request: {
    country: string;
    age_min: number | null;
    age_max: number | null;
    gender: string;
    count: number;
    education?: string[];
    occupation_group?: string[];
    urbanicity?: string;
    consumption_style?: string[];
  };
  started_at: string;
  finished_at: string | null;
}

export interface FixedAssignment {
  role: RoleKey;
  role_name: string;
  player_id: string;
  name: string;
  mbti: string;
  type_name: string;
  age: number | null;
  gender: string;
  occupation: string;
  province: string;
}

export interface Simulation {
  id: string;
  no: number;
  name: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  status: SimStatus;
  total_games: number;
  completed_games: number;
  variable_roles: Record<RoleKey, number>;
  fixed_assignments: FixedAssignment[];
  seed: number;
  total_tokens: number;
  config: {
    player_count?: number;
    variable_slots?: number;
    eligible_types?: string[];
    eligible_counts?: Record<string, number>;
    concurrency?: number;
  };
  error: string | null;
}

export interface LiveEntry {
  seq: number;
  round: number;
  type: string;
  text: string;
  at: string;
}

export interface Snapshot {
  id: string;
  no: number;
  status: SimStatus;
  total_games: number;
  completed_games: number;
  current_game: number;
  current_round: number;
  max_rounds: number;
  concurrency?: number;
  total_tokens: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  live: LiveEntry[];
}

export interface GameSummary {
  simulation_id: string;
  game_no: number;
  seed: number;
  variable_type: string;
  winner: Winner;
  win_reason: string;
  rounds: number;
  variable_roles: Record<RoleKey, number>;
  variable_camp_wins: {
    wolf: { players: number; wins: number };
    good: { players: number; wins: number };
  };
  variable_player_wins: number;
  variable_player_count: number;
  duration_ms: number;
  tokens: number;
  degenerate: number;
  created_at: string;
}

export interface GamePlayer {
  seat: number;
  name: string;
  role: RoleKey;
  role_name: string;
  camp: "wolf" | "good";
  mbti: string;
  type_name: string;
  is_variable: boolean;
  age: number | null;
  gender: string;
  province: string;
  occupation: string;
  params: Params;
  alive: boolean;
  death_cause: string | null;
  death_round: number | null;
  checks: { round: number; seat: number; name: string; result: string }[];
  claims: { round: number; role: string }[];
}

export interface GameEvent {
  type: string;
  round: number;
  public?: string;
  [key: string]: unknown;
}

export interface GameDetail extends GameSummary {
  detail: {
    seed: number;
    variable_type: string;
    variable_roles: Record<RoleKey, number>;
    winner: Winner;
    win_reason: string;
    rounds: number;
    players: GamePlayer[];
    events: GameEvent[];
    public_log: string[];
    round_summaries: string[];
    tokens: number;
    degenerate: number;
    errors: { seat?: number; error: string }[];
    duration_ms: number;
  };
}

export interface TypeStat {
  type: string;
  type_name: string;
  games: number;
  wolf_games: number;
  wolf_wins: number;
  good_games: number;
  good_wins: number;
  appearances: number;
  player_wins: number;
  rounds: number;
  tokens: number;
  wolf_rate: number;
  good_rate: number;
  player_rate: number;
  avg_rounds: number;
}

export interface TimelinePoint {
  no: number;
  games: number;
  wolf_wins: number;
  good_wins: number;
  draws: number;
  wolf_rate: number;
  good_rate: number;
  draw_rate: number;
}

export interface Analysis {
  simulation: Simulation;
  games: GameSummary[];
  stats: {
    games: number;
    camps: {
      wolf: { wins: number; rate: number };
      good: { wins: number; rate: number };
      draw: { wins: number; rate: number };
    };
    by_type: TypeStat[];
    timeline: TimelinePoint[];
    avg_rounds: number;
    tokens: number;
  };
  snapshot: Snapshot;
}
