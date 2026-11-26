import type { RoleKey, Winner } from "./types";

export const ALL_TYPES = [
  "INTJ", "INTP", "ENTJ", "ENTP",
  "INFJ", "INFP", "ENFJ", "ENFP",
  "ISTJ", "ISFJ", "ESTJ", "ESFJ",
  "ISTP", "ISFP", "ESTP", "ESFP",
];

export const TYPE_NAMES: Record<string, string> = {
  INTJ: "策划者", INTP: "思想家", ENTJ: "指挥官", ENTP: "发明家",
  INFJ: "提倡者", INFP: "治愈者", ENFJ: "教导者", ENFP: "奋斗者",
  ISTJ: "检查者", ISFJ: "保护者", ESTJ: "监督者", ESFJ: "供应者",
  ISTP: "鉴赏家", ISFP: "创作者", ESTP: "创业者", ESFP: "表演者",
};

export type TypeGroup = "NT" | "NF" | "SJ" | "SP";

export function groupOf(type: string): TypeGroup {
  if (type.includes("N") && type.includes("T")) return "NT";
  if (type.includes("N") && type.includes("F")) return "NF";
  if (type.includes("S") && type.includes("J")) return "SJ";
  return "SP";
}

export const GROUP_LABEL: Record<TypeGroup, string> = {
  NT: "分析家",
  NF: "外交家",
  SJ: "守护者",
  SP: "探险家",
};

export const GROUP_DESC: Record<TypeGroup, string> = {
  NT: "理性 · 战略",
  NF: "理想 · 共情",
  SJ: "秩序 · 责任",
  SP: "灵活 · 行动",
};

export const ROLES: Record<RoleKey, { name: string; camp: "wolf" | "good"; max: number }> = {
  wolf: { name: "狼人", camp: "wolf", max: 3 },
  villager: { name: "平民", camp: "good", max: 4 },
  seer: { name: "预言家", camp: "good", max: 1 },
  witch: { name: "女巫", camp: "good", max: 1 },
  hunter: { name: "猎人", camp: "good", max: 1 },
};

export const ROLE_ORDER: RoleKey[] = ["wolf", "villager", "seer", "witch", "hunter"];

export function roleTotal(role: RoleKey, playerCount: number): number {
  if (role === "villager") return Math.max(0, playerCount - 6);
  return ROLES[role].max;
}

export const ROLE_DESC: Record<RoleKey, string> = {
  wolf: "每晚共同刀人，白天伪装",
  villager: "无技能，靠发言和投票",
  seer: "每晚查验一人阵营",
  witch: "解药与毒药各一瓶",
  hunter: "被刀或被投出可开枪",
};

export const PARAM_LABELS: Record<string, string> = {
  verbosity: "话量",
  challenge: "质疑",
  evidence: "证据",
  ally_speed: "结盟",
  conformity: "跟票",
  jump_threshold: "跳身份",
  risk: "风险",
};

export const WINNER_LABEL: Record<Winner, string> = {
  wolf: "狼人胜",
  good: "好人胜",
  draw: "未决",
};

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatFullDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatDuration(ms?: number | null): string {
  if (!ms || ms < 0) return "—";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes} 分 ${rest} 秒`;
}

export function pct(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function compactNumber(value?: number | null): string {
  if (!value) return "0";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(1)}万`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

export function roleSummary(roles: Record<RoleKey, number>): string {
  return ROLE_ORDER.filter((role) => (roles?.[role] || 0) > 0)
    .map((role) => `${ROLES[role].name}×${roles[role]}`)
    .join(" · ") || "无变量角色";
}

export function typeBadgeClass(type: string): string {
  return `type-${groupOf(type).toLowerCase()}`;
}
