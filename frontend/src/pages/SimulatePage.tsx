import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import type {
  Catalog,
  GameSummary,
  Player,
  RoleKey,
  Simulation,
  Snapshot,
  Winner,
} from "../lib/types";
import {
  ALL_TYPES,
  ROLES,
  ROLE_DESC,
  ROLE_ORDER,
  WINNER_LABEL,
  formatDate,
  formatDuration,
  roleSummary,
  roleTotal,
} from "../lib/format";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Modal,
  ProgressBar,
  RoleBadge,
  SectionHead,
  Segmented,
  Spinner,
  StatTile,
  StatusBadge,
  TypeBadge,
  WinnerBadge,
  useToast,
} from "../components/Ui";
import { Icon, RoleIcon } from "../components/Icons";
import { PlayerAvatar, PlayerPicker } from "../components/PlayerBits";
import { StatsPanel } from "../components/StatsPanel";
import { GameDrawer } from "../components/GameDrawer";

const EMPTY_ROLES: Record<RoleKey, number> = { wolf: 1, villager: 0, seer: 0, witch: 0, hunter: 0 };

export function SimulatePage({
  simId,
  onNavigate,
}: {
  simId?: string;
  onNavigate: (path: string) => void;
}) {
  return simId ? (
    <RunView simId={simId} onNavigate={onNavigate} />
  ) : (
    <SetupView onNavigate={onNavigate} />
  );
}

// --------------------------------------------------------------------------
// setup
// --------------------------------------------------------------------------
function SetupView({ onNavigate }: { onNavigate: (path: string) => void }) {
  const toast = useToast();
  const [players, setPlayers] = useState<Player[]>([]);
  const [allTotal, setAllTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [playerCount, setPlayerCount] = useState(9);
  const [variableRoles, setVariableRoles] = useState<Record<RoleKey, number>>(EMPTY_ROLES);
  const [fixed, setFixed] = useState<Record<RoleKey, (Player | null)[]>>(() =>
    buildFixed(EMPTY_ROLES, {} as Record<RoleKey, (Player | null)[]>, 9),
  );
  const [games, setGames] = useState(10);
  const [concurrency, setConcurrency] = useState(2);
  const [picker, setPicker] = useState<{ role: RoleKey; index: number } | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  const loadPlayers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.players({ limit: 500, tested: true });
      setPlayers(data.players);
      setAllTotal(data.total);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "读取玩家库失败", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadPlayers();
  }, [loadPlayers]);

  useEffect(() => {
    setVariableRoles((current) => {
      const next = { ...current };
      ROLE_ORDER.forEach((role) => {
        next[role] = Math.min(next[role] || 0, roleTotal(role, playerCount));
      });
      return next;
    });
  }, [playerCount]);

  useEffect(() => {
    setFixed((current) => buildFixed(variableRoles, current, playerCount));
  }, [variableRoles, playerCount]);

  const variableSlots = useMemo(
    () => ROLE_ORDER.reduce((sum, role) => sum + (variableRoles[role] || 0), 0),
    [variableRoles],
  );

  const selectedIds = useMemo(() => {
    const ids = new Set<string>();
    ROLE_ORDER.forEach((role) => {
      (fixed[role] || []).forEach((player) => {
        if (player) ids.add(player.id);
      });
    });
    return ids;
  }, [fixed]);

  const typeAvailability = useMemo(() => {
    const counts: Record<string, number> = {};
    players.forEach((player) => {
      if (!selectedIds.has(player.id)) counts[player.mbti] = (counts[player.mbti] || 0) + 1;
    });
    return Object.entries(counts)
      .filter(([, count]) => count >= variableSlots)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [players, selectedIds, variableSlots]);

  const maxTypeCount = useMemo(() => {
    const counts: Record<string, number> = {};
    players.forEach((player) => {
      if (!selectedIds.has(player.id)) counts[player.mbti] = (counts[player.mbti] || 0) + 1;
    });
    return Math.max(0, ...Object.values(counts));
  }, [players, selectedIds]);

  const fixedSlots = useMemo(
    () => ROLE_ORDER.reduce((sum, role) => sum + roleTotal(role, playerCount) - (variableRoles[role] || 0), 0),
    [variableRoles, playerCount],
  );
  const filledSlots = useMemo(
    () => ROLE_ORDER.reduce((sum, role) => sum + (fixed[role] || []).filter(Boolean).length, 0),
    [fixed],
  );
  const missingSlots = fixedSlots - filledSlots;
  const validGames = Number.isInteger(games) && games >= 1 && games <= 2000;
  const canStart = variableSlots >= 1 && missingSlots === 0 && typeAvailability.length > 0 && validGames && !starting;
  const callsLow = Math.round(games * 65);
  const callsHigh = Math.round(games * 140);
  const minutesLow = Math.max(1, Math.round((games * 0.7) / concurrency));
  const minutesHigh = Math.max(2, Math.round((games * 2.2) / concurrency));

  const setRoleCount = (role: RoleKey, next: number) => {
    setVariableRoles((current) => ({
      ...current,
      [role]: Math.max(0, Math.min(roleTotal(role, playerCount), next)),
    }));
  };

  const pickerSelected = useMemo(() => {
    const ids = new Set(selectedIds);
    if (picker) {
      const current = fixed[picker.role]?.[picker.index];
      if (current) ids.delete(current.id);
    }
    return ids;
  }, [selectedIds, picker, fixed]);

  const handlePick = (player: Player) => {
    if (!picker) return;
    setFixed((current) => {
      const list = [...(current[picker.role] || [])];
      list[picker.index] = player;
      return { ...current, [picker.role]: list };
    });
    setPicker(null);
  };

  const clearSlot = (role: RoleKey, index: number) => {
    setFixed((current) => {
      const list = [...(current[role] || [])];
      list[index] = null;
      return { ...current, [role]: list };
    });
  };

  const start = async () => {
    if (!canStart) return;
    setStarting(true);
    setError("");
    try {
      const assignments: { role: string; player_id: string }[] = [];
      ROLE_ORDER.forEach((role) => {
        (fixed[role] || []).forEach((player) => {
          if (player) assignments.push({ role, player_id: player.id });
        });
      });
      const created = await api.createSimulation({
        player_count: playerCount,
        variable_roles: variableRoles,
        fixed_assignments: assignments,
        games,
        concurrency,
      });
      try {
        await api.start(created.simulation.id);
      } catch (err) {
        toast.push(err instanceof Error ? err.message : "启动失败，请在模拟页重试", "error");
      }
      onNavigate(`/simulate/${created.simulation.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建模拟失败");
    } finally {
      setStarting(false);
    }
  };

  const preset = (roles: Record<RoleKey, number>) => {
    setVariableRoles(roles);
    setFixed({} as Record<RoleKey, (Player | null)[]>);
  };

  const fullVariable = (): Record<RoleKey, number> => ({
    wolf: 3,
    villager: roleTotal("villager", playerCount),
    seer: 1,
    witch: 1,
    hunter: 1,
  });

  return (
    <div className="page simulate-page">
      <div className="page-head">
        <div>
          <div className="eyebrow">SIMULATION LAB · 变量实验台</div>
          <h1 className="page-title">新建模拟</h1>
          <p className="page-desc">
            先指定哪些角色是变量，其余角色由你从玩家库手动挑选。变量角色每局共享同一性格标签，逐局轮换，用来观察“人格 → 行为 → 胜率”。
          </p>
        </div>
        <div className="page-actions">
          <div className="library-pill"><Icon name="users" size={15} /> 玩家库 {allTotal} 人</div>
        </div>
      </div>

      <div className="sim-layout">
        <div className="sim-config">
          <section className="setup-card">
            <SectionHead
              eyebrow="STEP 01"
              title="哪些角色是变量？"
              desc="变量角色的玩家由系统每局自动从同性格样本中抽取；所有变量角色共享同一性格标签。"
              actions={
                <div className="preset-row">
                  <button type="button" className="preset-btn" onClick={() => preset({ wolf: 1, villager: 0, seer: 0, witch: 0, hunter: 0 })}>1 狼</button>
                  <button type="button" className="preset-btn" onClick={() => preset({ wolf: 3, villager: 0, seer: 0, witch: 0, hunter: 0 })}>3 狼同性格</button>
                  <button type="button" className="preset-btn" onClick={() => preset({ wolf: 3, villager: 0, seer: 1, witch: 0, hunter: 0 })}>3 狼 + 预言家</button>
                  <button type="button" className="preset-btn" onClick={() => preset(fullVariable())}>全变量</button>
                </div>
              }
            />
            <div className="board-config">
              <div>
                <b>玩家人数</b>
                <span>9 人局 3 民；10 人局增加 1 个可选平民位，其他规则不变。</span>
              </div>
              <Segmented
                value={String(playerCount)}
                onChange={(value) => setPlayerCount(Number(value))}
                options={[9, 10].map((value) => ({ value: String(value), label: `${value} 人` }))}
              />
            </div>
            <div className="role-config-grid">
              {ROLE_ORDER.map((role) => {
                const value = variableRoles[role] || 0;
                const meta = ROLES[role];
                return (
                  <div className={`role-config role-config--${role} ${value > 0 ? "is-variable" : ""}`} key={role}>
                    <div className="role-config__top">
                      <span className="role-config__icon"><RoleIcon role={role} size={19} /></span>
                      <span className="role-config__name">{meta.name}</span>
                      <span className="role-config__max">最多 {roleTotal(role, playerCount)}</span>
                    </div>
                    <p>{ROLE_DESC[role]}</p>
                    <div className="stepper">
                      <button type="button" onClick={() => setRoleCount(role, value - 1)} disabled={value <= 0} aria-label={`减少${meta.name}变量`}>
                        <Icon name="minus" size={15} />
                      </button>
                      <b>{value}</b>
                      <button type="button" onClick={() => setRoleCount(role, value + 1)} disabled={value >= roleTotal(role, playerCount)} aria-label={`增加${meta.name}变量`}>
                        <Icon name="plus" size={15} />
                      </button>
                      <span>{value > 0 ? "变量" : "固定"}</span>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="variable-rule">
              <Icon name="info" size={16} />
              <div>
                <b>共 {variableSlots} 个变量角色 · 每局需要 {variableSlots} 名同性格的不同玩家</b>
                <span>
                  {typeAvailability.length
                    ? <>当前可轮换：{typeAvailability.slice(0, 6).map(([code, count]) => `${code}（${count}）`).join(" · ")}{typeAvailability.length > 6 ? ` 等 ${typeAvailability.length} 种` : ""}</>
                    : `当前没有一种性格能提供 ${variableSlots} 名可用玩家（已扣除固定角色），请减少变量角色或补充玩家。`}
                </span>
              </div>
            </div>
          </section>

          <section className="setup-card">
            <SectionHead
              eyebrow="STEP 02"
              title="固定角色由谁上场？"
              desc="其他角色从玩家库手动挑选，选定后本次模拟内不可更换。同一玩家不能占两个位置。"
              actions={<span className="section-progress">{filledSlots} / {fixedSlots} 已选</span>}
            />
            {loading ? (
              <div className="panel-loading"><Spinner size={22} /><span>读取玩家库…</span></div>
            ) : (
              <div className="fixed-groups">
                {ROLE_ORDER.filter((role) => roleTotal(role, playerCount) - (variableRoles[role] || 0) > 0).map((role) => (
                  <div className="fixed-group" key={role}>
                    <div className="fixed-group__head">
                      <RoleBadge role={role} />
                      <span>{roleTotal(role, playerCount) - (variableRoles[role] || 0)} 个固定位</span>
                    </div>
                    <div className="fixed-slots">
                      {(fixed[role] || []).map((player, index) => (
                        <div className={`fixed-slot ${player ? "is-filled" : ""}`} key={`${role}-${index}`}>
                          {player ? (
                            <>
                              <PlayerAvatar player={player} size={38} />
                              <div className="fixed-slot__main">
                                <b>{player.name}</b>
                                <span>{player.occupation || "职业未知"} · {player.gender || "性别未知"} · {player.age ? `${player.age}岁` : "年龄未知"}</span>
                              </div>
                              <TypeBadge type={player.mbti} size="sm" />
                              <div className="fixed-slot__actions">
                                <button type="button" className="icon-btn icon-btn--sm" onClick={() => setPicker({ role, index })} aria-label="更换玩家">
                                  <Icon name="refresh" size={14} />
                                </button>
                                <button type="button" className="icon-btn icon-btn--sm" onClick={() => clearSlot(role, index)} aria-label="移除玩家">
                                  <Icon name="close" size={14} />
                                </button>
                              </div>
                            </>
                          ) : (
                            <button type="button" className="fixed-slot__empty" onClick={() => setPicker({ role, index })}>
                              <span className="fixed-slot__plus"><Icon name="plus" size={17} /></span>
                              <span>
                                <b>选择{ROLES[role].name}</b>
                                <em>从玩家库挑选</em>
                              </span>
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="setup-card">
            <SectionHead
              eyebrow="STEP 03"
              title="跑多少局？"
              desc="局数上限 2000。模拟是长任务，可随时暂停或停止；停止后已完成的对局会保留。并发会把多局同时跑，明显缩短墙钟时间，但总 token 不变、API 峰值更高。"
            />
            <div className="games-config">
              <Field label="模拟局数" hint={validGames ? `预计 ${callsLow.toLocaleString()}–${callsHigh.toLocaleString()} 次模型调用 · 并发 ${concurrency} 局，墙钟约 ${minutesLow}–${minutesHigh} 分钟` : "请输入 1–2000 的整数"}>
                <div className="games-input">
                  <input
                    type="number"
                    min={1}
                    max={2000}
                    value={games}
                    onChange={(event) => setGames(Number(event.target.value) || 0)}
                  />
                  <span>局</span>
                </div>
              </Field>
              <div className="game-presets">
                {[10, 50, 100, 500, 1000, 2000].map((value) => (
                  <button type="button" key={value} className={`preset-btn ${games === value ? "is-active" : ""}`} onClick={() => setGames(value)}>
                    {value} 局
                  </button>
                ))}
              </div>
            </div>
            <div className="concurrency-config">
              <div>
                <span className="concurrency-config__label">并发局数</span>
                <p>同时跑几局。2–3 局通常能明显缩短墙钟时间；总 token 不变，但 API 峰值会按并发数放大。</p>
              </div>
              <Segmented
                value={String(concurrency)}
                onChange={(value) => setConcurrency(Number(value))}
                options={[1, 2, 3, 4].map((value) => ({ value: String(value), label: `${value} 局` }))}
              />
            </div>
            {games > 200 ? (
              <div className="inline-warn">
                <Icon name="alert" size={16} />
                <span>局数较大，DeepSeek 调用量与耗时都会线性增长。建议先跑 10–50 局确认配置，再放大样本。</span>
              </div>
            ) : null}
          </section>
        </div>

        <aside className="sim-aside">
          <div className="setup-summary">
            <div className="setup-summary__head">
              <span className="eyebrow">RUN PREVIEW</span>
              <h3>本局配置</h3>
            </div>
            <RoleBoard variableRoles={variableRoles} fixed={fixed} />
            <div className="summary-list">
              <div><span>板子人数</span><b>{playerCount} 人 · {roleTotal("villager", playerCount)} 民</b></div>
              <div><span>变量角色</span><b>{roleSummary(variableRoles)}</b></div>
              <div><span>固定玩家</span><b>{filledSlots} / {fixedSlots}</b></div>
              <div><span>可轮换性格</span><b>{typeAvailability.length ? `${typeAvailability.length} 种` : "不足"}</b></div>
              <div><span>模拟局数</span><b>{validGames ? `${games} 局` : "—"}</b></div>
              <div><span>并发局数</span><b>{concurrency} 局</b></div>
              <div><span>每局模型调用</span><b>约 65–140 次</b></div>
            </div>
            <div className="summary-checks">
              <CheckItem ok={variableSlots >= 1} text={variableSlots >= 1 ? `变量角色 ${variableSlots} 个` : "至少设置 1 个变量角色"} />
              <CheckItem ok={missingSlots === 0} text={missingSlots === 0 ? "固定角色已选齐" : `还差 ${missingSlots} 个固定角色`} />
              <CheckItem
                ok={typeAvailability.length > 0}
                text={typeAvailability.length ? `有 ${typeAvailability.length} 种性格可填满变量位` : `没有性格能提供 ${variableSlots} 名同类型玩家`}
              />
              <CheckItem ok={validGames} text={validGames ? `计划跑 ${games} 局` : "局数需在 1–2000 之间"} />
            </div>
            {error ? <div className="inline-error"><Icon name="alert" size={15} /> {error}</div> : null}
            <Button variant="primary" size="lg" icon="play" className="start-btn" disabled={!canStart} loading={starting} onClick={start}>
              开始模拟
            </Button>
            <p className="summary-note">
              模拟启动后固定角色锁定。每局只改变变量角色的性格，其余配置完全一致。
            </p>
          </div>
        </aside>
      </div>

      <PlayerPicker
        open={Boolean(picker)}
        onClose={() => setPicker(null)}
        players={players}
        selectedIds={pickerSelected}
        title={picker ? `选择${ROLES[picker.role].name}` : "选择玩家"}
        subtitle="只能选择玩家库中已有 MBTI 结果的样本"
        onPick={handlePick}
      />
    </div>
  );
}

function buildFixed(
  roles: Record<RoleKey, number>,
  current: Record<RoleKey, (Player | null)[]>,
  playerCount: number,
): Record<RoleKey, (Player | null)[]> {
  const next = {} as Record<RoleKey, (Player | null)[]>;
  ROLE_ORDER.forEach((role) => {
    const count = roleTotal(role, playerCount) - (roles[role] || 0);
    const existing = current[role] || [];
    next[role] = Array.from({ length: Math.max(0, count) }, (_, index) => existing[index] || null);
  });
  return next;
}

function RoleBoard({
  variableRoles,
  fixed,
}: {
  variableRoles: Record<RoleKey, number>;
  fixed: Record<RoleKey, (Player | null)[]>;
}) {
  const tiles: { role: RoleKey; variable: boolean; player?: Player | null; index: number }[] = [];
  ROLE_ORDER.forEach((role) => {
    for (let i = 0; i < variableRoles[role]; i += 1) {
      tiles.push({ role, variable: true, index: i });
    }
    (fixed[role] || []).forEach((player, index) => {
      tiles.push({ role, variable: false, player, index });
    });
  });
  return (
    <div className="role-board" aria-label="席位预览">
      {tiles.map((tile, index) => (
        <div className={`role-board__tile role-board__tile--${tile.role} ${tile.variable ? "is-variable" : ""}`} key={`${tile.role}-${tile.variable}-${tile.index}-${index}`}>
          <span className="role-board__icon"><RoleIcon role={tile.role} size={16} /></span>
          <span className="role-board__role">{ROLES[tile.role].name}</span>
          {tile.variable ? (
            <span className="role-board__value">同性格轮换</span>
          ) : tile.player ? (
            <span className="role-board__value">{tile.player.name}</span>
          ) : (
            <span className="role-board__value role-board__value--empty">待选择</span>
          )}
          {tile.variable ? <span className="role-board__ping" /> : null}
        </div>
      ))}
    </div>
  );
}

function CheckItem({ ok, text }: { ok: boolean; text: string }) {
  return (
    <div className={`check-item ${ok ? "is-ok" : ""}`}>
      <span className="check-item__icon">{ok ? <Icon name="check" size={12} /> : <Icon name="close" size={12} />}</span>
      <span>{text}</span>
    </div>
  );
}

// --------------------------------------------------------------------------
// run
// --------------------------------------------------------------------------
function RunView({ simId, onNavigate }: { simId: string; onNavigate: (path: string) => void }) {
  const toast = useToast();
  const [sim, setSim] = useState<Simulation | null>(null);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [games, setGames] = useState<GameSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [stopConfirm, setStopConfirm] = useState(false);
  const [statsOpen, setStatsOpen] = useState(false);
  const [detailNo, setDetailNo] = useState<number | null>(null);
  const [winnerFilter, setWinnerFilter] = useState<Winner | "">("");
  const [now, setNow] = useState(Date.now());
  const feedRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [detail, gamePage] = await Promise.all([
        api.simulation(simId),
        api.games(simId, { limit: 200, order: "desc" }),
      ]);
      setSim(detail.simulation);
      setSnap(detail.snapshot);
      setGames(gamePage.games);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "读取模拟失败", "error");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [simId, toast]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const status = snap?.status || sim?.status || "created";
  const active = status === "running" || status === "paused" || status === "stopping";

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => load(true), 1500);
    return () => window.clearInterval(timer);
  }, [active, load]);

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [snap?.live?.length]);

  const action = async (kind: "start" | "pause" | "resume" | "stop") => {
    setBusy(true);
    try {
      const result = kind === "start"
        ? await api.start(simId)
        : kind === "pause"
          ? await api.pause(simId)
          : kind === "resume"
            ? await api.resume(simId)
            : await api.stop(simId);
      setSnap(result.snapshot);
      setStopConfirm(false);
      await load(true);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "操作失败", "error");
    } finally {
      setBusy(false);
    }
  };

  const filteredGames = winnerFilter ? games.filter((game) => game.winner === winnerFilter) : games;
  const elapsed = snap?.started_at
    ? Math.max(0, (snap.finished_at ? new Date(snap.finished_at).getTime() : now) - new Date(snap.started_at).getTime())
    : 0;
  const progress = snap ? (snap.completed_games / Math.max(1, snap.total_games)) * 100 : 0;
  const statusLabel = status === "running" ? "运行中" : status === "paused" ? "已暂停" : status === "completed" ? "已完成" : status === "stopped" ? "已停止" : status === "error" ? "出错" : status === "stopping" ? "正在停止" : "待启动";

  if (loading && !sim) {
    return <div className="page"><div className="panel-loading page-loading"><Spinner size={28} /><span>正在读取模拟…</span></div></div>;
  }
  if (!sim || !snap) {
    return (
      <div className="page">
        <EmptyState icon="alert" title="模拟不存在" desc="它可能已被删除。" action={<Button variant="primary" onClick={() => onNavigate("/simulate")}>新建模拟</Button>} />
      </div>
    );
  }

  return (
    <div className="page run-page">
      <div className="page-head page-head--run">
        <div>
          <div className="eyebrow">SIMULATION #{String(sim.no).padStart(4, "0")} · {formatDate(sim.created_at)}</div>
          <h1 className="page-title page-title--run">
            {sim.name || "人格狼人杀模拟"}
            <StatusBadge status={status} />
          </h1>
          <p className="page-desc">
            {roleSummary(sim.variable_roles)} 为变量 · 每局共享同一性格标签 · 固定玩家 {sim.fixed_assignments.length} 名
          </p>
        </div>
        <div className="page-actions">
          <Button variant="ghost" icon="history" onClick={() => onNavigate("/history")}>历史记录</Button>
          {!active ? (
            <Button variant="secondary" icon="plus" onClick={() => onNavigate("/simulate")}>新建模拟</Button>
          ) : null}
        </div>
      </div>

      <div className="console">
        <div className="console__top">
          <div className="console__status">
            <span className={`console__pulse console__pulse--${status}`} />
            <span>{statusLabel}</span>
            {status === "running" ? <span className="console__live-tag">LIVE</span> : null}
          </div>
          <div className="console__meta">
            <span><Icon name="clock" size={14} /> {formatDuration(elapsed)}</span>
            <span><Icon name="tokens" size={14} /> {snap.total_tokens.toLocaleString()}</span>
            <span><Icon name="seed" size={14} /> Seed {sim.seed}</span>
            <span><Icon name="layers" size={14} /> 并发 {snap.concurrency || sim.config.concurrency || 1}</span>
          </div>
        </div>

        <div className="console__main">
          <div className="console__progress">
            <div className="console__progress-head">
              <div>
                <span className="console__small">PROGRESS</span>
                <b>{snap.completed_games}<em>/ {snap.total_games}</em></b>
              </div>
              <div className="console__progress-meta">
                <span>当前第 <b>{Math.max(1, snap.current_game)}</b> 局</span>
                <span>第 <b>{snap.current_round || 1}</b> / 8 轮</span>
              </div>
            </div>
            <ProgressBar value={progress} height={10} tone="ochre" shimmer={status === "running"} />
            <div className="console__progress-foot">
              <span>{progress.toFixed(1)}% 完成</span>
              <span>{snap.completed_games ? `平均 ${(snap.total_tokens / snap.completed_games).toLocaleString(undefined, { maximumFractionDigits: 0 })} tokens / 局` : "正在准备第一局"}</span>
            </div>
            <div className="console__controls">
              {status === "created" ? (
                <Button variant="ochre" icon="play" loading={busy} onClick={() => action("start")}>启动模拟</Button>
              ) : null}
              {status === "running" ? (
                <Button variant="dark" icon="pause" loading={busy} onClick={() => action("pause")}>暂停</Button>
              ) : null}
              {status === "paused" ? (
                <Button variant="ochre" icon="play" loading={busy} onClick={() => action("resume")}>继续</Button>
              ) : null}
              {status === "stopped" ? (
                <Button variant="ochre" icon="play" loading={busy} onClick={() => action("resume")}>继续跑完</Button>
              ) : null}
              {status === "running" || status === "paused" ? (
                <Button variant="danger" icon="stop" onClick={() => setStopConfirm(true)}>停止</Button>
              ) : null}
              {snap.completed_games > 0 ? (
                <Button variant="dark" icon="chart" onClick={() => setStatsOpen(true)}>查看统计</Button>
              ) : null}
              {status === "completed" ? (
                <Button variant="ochre" icon="plus" onClick={() => onNavigate("/simulate")}>开始新的模拟</Button>
              ) : null}
              {status === "error" && snap.completed_games < snap.total_games ? (
                <Button variant="ochre" icon="refresh" loading={busy} onClick={() => action("start")}>继续补跑</Button>
              ) : null}
              {status === "error" ? (
                <Button variant="ochre" icon="plus" onClick={() => onNavigate("/simulate")}>新建模拟</Button>
              ) : null}
            </div>
            {snap.error ? <div className="console__error"><Icon name="alert" size={15} /> {snap.error}</div> : null}
            {status === "stopped" ? <div className="console__notice">已停止。继续会从第 {snap.completed_games + 1} 局接着跑。</div> : null}
            {status === "completed" ? <div className="console__notice console__notice--done">全部 {snap.total_games} 局已完成，可以查看统计或新建模拟。</div> : null}
          </div>

          <div className="console__feed-wrap">
            <div className="console__feed-head">
              <span><Icon name="wave" size={14} /> 实时进程</span>
              <span className="console__feed-hint">{snap.live.length ? `最近 ${snap.live.length} 条` : "等待事件"}</span>
            </div>
            <div className="console__feed" ref={feedRef}>
              {snap.live.length === 0 ? (
                <div className="console__feed-empty">
                  {status === "running"
                    ? "模型正在入座，第一条事件马上出现…"
                    : status === "paused"
                      ? "已暂停。继续后会从下一行动接着跑。"
                      : status === "completed"
                        ? "本批次已结束。打开下方任意一局查看完整复盘。"
                        : status === "stopped"
                          ? "本批次已停止。已完成的对局保留在下方。"
                          : status === "error"
                            ? "本批次出错，详见上方错误信息。"
                            : "还没有进程事件。"}
                </div>
              ) : (
                snap.live.slice(-30).map((entry) => (
                  <div className={`feed-line feed-line--${entry.type || "run"}`} key={`${entry.seq}-${entry.at}`}>
                    <span className="feed-line__time">{entry.at.slice(11, 19)}</span>
                    <span className="feed-line__dot" />
                    <span className="feed-line__text">{entry.text}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      <section className="run-config-strip">
        <div className="run-config-strip__item">
          <span>变量角色</span>
          <div>{ROLE_ORDER.filter((role) => sim.variable_roles[role]).map((role) => (
            <span className="mini-chip" key={role}><RoleBadge role={role} size="sm" /> ×{sim.variable_roles[role]}</span>
          ))}</div>
        </div>
        <div className="run-config-strip__item">
          <span>固定角色</span>
          <div className="fixed-chip-list">
            {sim.fixed_assignments.map((item) => (
              <span className="fixed-chip" key={`${item.role}-${item.player_id}`}>
                <b>{item.role_name}</b> {item.name} <TypeBadge type={item.mbti} size="sm" />
              </span>
            ))}
          </div>
        </div>
        <div className="run-config-strip__item">
          <span>可轮换性格</span>
          <div className="type-chip-row type-chip-row--small">
            {(sim.config.eligible_types || []).map((type) => (
              <span className="mini-type" key={type}>{type} <b>{sim.config.eligible_counts?.[type] || 0}</b></span>
            ))}
          </div>
        </div>
      </section>

      <section className="results-card">
        <div className="results-head">
          <div>
            <h2>对局结果</h2>
            <p>{snap.completed_games} / {snap.total_games} 局完成 · 列表按最新优先</p>
          </div>
          <div className="results-filters">
            {([["", "全部"], ["wolf", "狼人胜"], ["good", "好人胜"], ["draw", "未决"]] as [Winner | "", string][]).map(([value, label]) => (
              <button type="button" key={value || "all"} className={`filter-pill ${winnerFilter === value ? "is-active" : ""}`} onClick={() => setWinnerFilter(value)}>
                {label}
              </button>
            ))}
          </div>
        </div>
        {filteredGames.length === 0 ? (
          <EmptyState
            icon="play"
            title={games.length ? "该筛选下暂无对局" : status === "running" ? "第一局正在生成" : "还没有完成的对局"}
            desc={status === "running" ? "一局通常需要 1–3 分钟，实时进程会先显示夜间行动。" : "启动模拟后，结果会逐局出现在这里。"}
          />
        ) : (
          <GameTable games={filteredGames} onOpen={setDetailNo} />
        )}
        {games.length >= 200 ? <div className="results-footnote">仅显示最近 200 局；统计与历史记录使用全部已完成对局。</div> : null}
      </section>

      <StatsPanel simId={simId} open={statsOpen} onClose={() => setStatsOpen(false)} onOpenGame={(no) => { setStatsOpen(false); setDetailNo(no); }} />
      <GameDrawer open={detailNo !== null} simId={simId} gameNo={detailNo} onClose={() => setDetailNo(null)} />
      <ConfirmDialog
        open={stopConfirm}
        title="停止本次模拟"
        message={<>将在当前行动结束后停止。已完成的对局会保留，未完成的对局不会计入统计。确定停止吗？</>}
        confirmText="停止模拟"
        danger
        onCancel={() => setStopConfirm(false)}
        onConfirm={() => action("stop")}
      />
    </div>
  );
}

export function GameTable({ games, onOpen }: { games: GameSummary[]; onOpen: (no: number) => void }) {
  return (
    <div className="game-table-wrap">
      <table className="game-table">
        <thead>
          <tr>
            <th>局数</th>
            <th>变量性格</th>
            <th>获胜方</th>
            <th>轮次</th>
            <th>耗时</th>
            <th>Token</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {games.map((game) => (
            <tr key={game.game_no} onClick={() => onOpen(game.game_no)}>
              <td><b className="game-no">#{String(game.game_no).padStart(4, "0")}</b></td>
              <td><TypeBadge type={game.variable_type} size="sm" /></td>
              <td><WinnerBadge winner={game.winner} size="sm" /></td>
              <td>{game.rounds} 轮</td>
              <td>{formatDuration(game.duration_ms)}</td>
              <td className="game-token">{game.tokens.toLocaleString()}</td>
              <td className="game-open">查看详情 <Icon name="chevronRight" size={14} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
