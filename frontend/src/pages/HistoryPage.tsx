import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { Analysis, Simulation } from "../lib/types";
import { ROLES, ROLE_ORDER, formatDate, formatFullDate, roleSummary } from "../lib/format";
import {
  Button,
  EmptyState,
  ProgressBar,
  SectionHead,
  Spinner,
  StatTile,
  StatusBadge,
  TypeBadge,
  useToast,
} from "../components/Ui";
import { Icon } from "../components/Icons";
import { StatsPanel } from "../components/StatsPanel";
import { GameDrawer } from "../components/GameDrawer";
import { GameTable } from "./SimulatePage";

export function HistoryPage({ onNavigate }: { onNavigate: (path: string) => void }) {
  const toast = useToast();
  const [items, setItems] = useState<Simulation[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.history();
      setItems(data.items);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "读取历史记录失败", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    if (!items) return [];
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((sim) =>
      `${sim.no} ${sim.name} ${sim.status} ${Object.keys(sim.variable_roles || {}).join(" ")}`.toLowerCase().includes(needle),
    );
  }, [items, query]);

  const totals = useMemo(() => {
    const list = items || [];
    return {
      count: list.length,
      games: list.reduce((sum, sim) => sum + (sim.completed_games || 0), 0),
      tokens: list.reduce((sum, sim) => sum + (sim.total_tokens || 0), 0),
      completed: list.filter((sim) => sim.status === "completed").length,
    };
  }, [items]);

  return (
    <div className="page history-page">
      <div className="page-head">
        <div>
          <div className="eyebrow">ARCHIVE · 实验档案</div>
          <h1 className="page-title">历史记录</h1>
          <p className="page-desc">
            每次模拟的配置、固定角色、变量性格和逐局结果都留在这里。打开任意一次记录，可查看与模拟区一致的完整统计和复盘。
          </p>
        </div>
        <div className="page-actions">
          <Button variant="ghost" icon="refresh" onClick={load}>刷新</Button>
          <Button variant="primary" icon="plus" onClick={() => onNavigate("/simulate")}>新建模拟</Button>
        </div>
      </div>

      <div className="stat-row">
        <StatTile label="模拟批次" value={totals.count} hint={`${totals.completed} 批已完成`} icon="layers" tone="ochre" />
        <StatTile label="累计完成对局" value={totals.games.toLocaleString()} hint="跨全部模拟批次" icon="flag" />
        <StatTile label="累计 Token" value={totals.tokens.toLocaleString()} hint="DeepSeek 调用消耗" icon="tokens" />
        <StatTile label="最近批次" value={items?.[0] ? `#${String(items[0].no).padStart(4, "0")}` : "—"} hint={items?.[0] ? formatDate(items[0].created_at) : "尚无记录"} icon="clock" tone="violet" />
      </div>

      <section className="history-card">
        <div className="history-toolbar">
          <div className="search-box search-box--history">
            <Icon name="search" size={17} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索批次编号、名称或状态" />
          </div>
          <span className="history-count">{loading ? "读取中…" : `${filtered.length} 条记录`}</span>
        </div>
        {loading && !items ? (
          <div className="panel-loading"><Spinner size={24} /><span>正在读取历史记录…</span></div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon="history"
            title={items?.length ? "没有匹配的记录" : "还没有模拟记录"}
            desc={items?.length ? "换一个关键词试试。" : "完成一次模拟后，它会自动归档到这里。"}
            action={!items?.length ? <Button variant="primary" icon="play" onClick={() => onNavigate("/simulate")}>新建模拟</Button> : null}
          />
        ) : (
          <div className="history-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th>模拟编号</th>
                  <th>创建日期</th>
                  <th>状态</th>
                  <th>局数</th>
                  <th>变量角色</th>
                  <th>固定角色及性格</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((sim) => (
                  <tr key={sim.id} onClick={() => onNavigate(`/history/${sim.id}`)}>
                    <td>
                      <div className="sim-id-cell">
                        <b>#{String(sim.no).padStart(4, "0")}</b>
                        <span>{sim.name || "人格狼人杀模拟"}</span>
                      </div>
                    </td>
                    <td>{formatDate(sim.created_at)}</td>
                    <td>
                      <StatusBadge status={sim.status} />
                      {sim.status === "running" || sim.status === "paused" ? (
                        <ProgressBar value={sim.completed_games} max={sim.total_games} height={4} tone="ochre" />
                      ) : null}
                    </td>
                    <td>
                      <b>{sim.completed_games}</b> / {sim.total_games}
                    </td>
                    <td>
                      <div className="history-roles">
                        <span className="mini-chip">{sim.config.player_count || 9} 人局</span>
                        {ROLE_ORDER.filter((role) => sim.variable_roles?.[role]).map((role) => (
                          <span className="mini-chip" key={role}>{ROLES[role].name} ×{sim.variable_roles[role]}</span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <div className="history-fixed">
                        {sim.fixed_assignments.slice(0, 3).map((item) => (
                          <span className="fixed-chip fixed-chip--compact" key={`${item.role}-${item.player_id}`}>
                            <b>{item.role_name}</b> {item.name} <TypeBadge type={item.mbti} size="sm" />
                          </span>
                        ))}
                        {sim.fixed_assignments.length > 3 ? (
                          <span className="fixed-more">+{sim.fixed_assignments.length - 3}</span>
                        ) : null}
                      </div>
                    </td>
                    <td className="history-open"><span>查看结果</span><Icon name="chevronRight" size={14} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export function HistoryDetailPage({
  simId,
  onNavigate,
}: {
  simId: string;
  onNavigate: (path: string) => void;
}) {
  const toast = useToast();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [statsOpen, setStatsOpen] = useState(false);
  const [detailNo, setDetailNo] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.analysis(simId);
      setAnalysis(data);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "读取模拟结果失败", "error");
    } finally {
      setLoading(false);
    }
  }, [simId, toast]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!analysis) return;
    const status = analysis.simulation.status;
    if (status !== "running" && status !== "paused") return;
    const timer = window.setInterval(load, 8000);
    return () => window.clearInterval(timer);
  }, [analysis?.simulation.status, load]);

  if (loading && !analysis) {
    return <div className="page"><div className="panel-loading page-loading"><Spinner size={28} /><span>正在读取模拟结果…</span></div></div>;
  }
  if (!analysis) {
    return (
      <div className="page">
        <EmptyState icon="alert" title="模拟不存在" desc="它可能已被删除。" action={<Button variant="primary" onClick={() => onNavigate("/history")}>返回历史记录</Button>} />
      </div>
    );
  }

  const sim = analysis.simulation;
  const allGames = analysis.games;
  const games = [...allGames].reverse().slice(0, 300);
  const stats = analysis.stats;

  return (
    <div className="page history-detail-page">
      <div className="page-head">
        <div>
          <button type="button" className="back-link" onClick={() => onNavigate("/history")}>
            <Icon name="arrowLeft" size={15} /> 历史记录
          </button>
          <div className="eyebrow">SIMULATION #{String(sim.no).padStart(4, "0")} · {formatFullDate(sim.created_at)}</div>
          <h1 className="page-title page-title--run">
            {sim.name || "人格狼人杀模拟"}
            <StatusBadge status={sim.status} />
          </h1>
          <p className="page-desc">{roleSummary(sim.variable_roles)} 为变量 · 固定玩家 {sim.fixed_assignments.length} 名 · Seed {sim.seed}</p>
        </div>
        <div className="page-actions">
          <Button variant="ghost" icon="refresh" onClick={load}>刷新</Button>
          {["running", "paused", "stopped", "created", "error"].includes(sim.status) ? (
            <Button variant="secondary" icon="play" onClick={() => onNavigate(`/simulate/${sim.id}`)}>打开控制台</Button>
          ) : null}
          {sim.completed_games > 0 ? <Button variant="primary" icon="chart" onClick={() => setStatsOpen(true)}>查看统计</Button> : null}
        </div>
      </div>

      <div className="stat-row">
        <StatTile label="完成局数" value={`${sim.completed_games} / ${sim.total_games}`} hint={sim.status === "completed" ? "批次已完成" : "批次未跑完"} icon="flag" tone="ochre" />
        <StatTile label="狼人方胜率" value={pct(stats.camps.wolf.rate)} hint={`${stats.camps.wolf.wins} 胜`} tone="wolf" />
        <StatTile label="好人方胜率" value={pct(stats.camps.good.rate)} hint={`${stats.camps.good.wins} 胜`} tone="good" />
        <StatTile label="平均轮次" value={stats.avg_rounds.toFixed(1)} hint={`${stats.tokens.toLocaleString()} tokens`} tone="violet" />
      </div>

      <div className="history-detail-grid">
        <section className="setup-card">
          <SectionHead eyebrow="CONFIG" title="本次实验配置" desc="所有可选项已固定展示，不可在本页修改。" />
          <div className="config-readout">
            <div className="config-block">
              <span>板子</span>
              <div className="config-chips">
                <span className="mini-chip">{sim.config.player_count || 9} 人 · {sim.config.player_count === 10 ? 4 : 3} 民</span>
              </div>
            </div>
            <div className="config-block">
              <span>变量角色</span>
              <div className="config-chips">
                {ROLE_ORDER.filter((role) => sim.variable_roles?.[role]).map((role) => (
                  <span className="mini-chip" key={role}>{ROLES[role].name} ×{sim.variable_roles[role]}</span>
                ))}
              </div>
            </div>
            <div className="config-block">
              <span>并发局数</span>
              <div className="config-chips">
                <span className="mini-chip">{sim.config.concurrency || 1} 局同时运行</span>
              </div>
            </div>
            <div className="config-block">
              <span>可轮换性格</span>
              <div className="config-chips">
                {(sim.config.eligible_types || []).map((type) => (
                  <span className="mini-type" key={type}>{type} <b>{sim.config.eligible_counts?.[type] || 0}</b></span>
                ))}
              </div>
            </div>
            <div className="config-block">
              <span>固定角色及性格</span>
              <div className="config-fixed-list">
                {sim.fixed_assignments.map((item) => (
                  <span className="fixed-chip" key={`${item.role}-${item.player_id}`}>
                    <b>{item.role_name}</b> {item.name} <TypeBadge type={item.mbti} size="sm" />
                  </span>
                ))}
              </div>
            </div>
            <div className="config-block config-block--meta">
              <span>Seed</span><b>{sim.seed}</b>
              <span>开始</span><b>{formatDate(sim.started_at)}</b>
              <span>结束</span><b>{formatDate(sim.finished_at)}</b>
              <span>Token</span><b>{sim.total_tokens.toLocaleString()}</b>
            </div>
          </div>
          {sim.error ? <div className="inline-error"><Icon name="alert" size={16} /> {sim.error}</div> : null}
        </section>

        <section className="setup-card history-side">
          <SectionHead eyebrow="OUTCOME" title="快速结论" />
          {stats.games ? (
            <>
              <div className="outcome-line">
                <span>狼人</span>
                <div className="outcome-bar"><span style={{ width: `${stats.camps.wolf.rate * 100}%`, background: "#eb6834" }} /></div>
                <b>{pct(stats.camps.wolf.rate)}</b>
              </div>
              <div className="outcome-line">
                <span>好人</span>
                <div className="outcome-bar"><span style={{ width: `${stats.camps.good.rate * 100}%`, background: "#2a78d6" }} /></div>
                <b>{pct(stats.camps.good.rate)}</b>
              </div>
              <div className="outcome-line">
                <span>未决</span>
                <div className="outcome-bar"><span style={{ width: `${stats.camps.draw.rate * 100}%`, background: "#8a847c" }} /></div>
                <b>{pct(stats.camps.draw.rate)}</b>
              </div>
              <div className="outcome-types">
                {stats.by_type.slice(0, 4).map((row) => (
                  <div key={row.type}>
                    <TypeBadge type={row.type} size="sm" />
                    <span>{row.games} 局</span>
                    <b>{pct(row.player_rate)}</b>
                  </div>
                ))}
              </div>
              <Button variant="secondary" icon="chart" onClick={() => setStatsOpen(true)}>打开完整统计</Button>
            </>
          ) : (
            <EmptyState icon="chart" title="还没有完成的对局" desc="该批次尚未产生可统计的结果。" />
          )}
        </section>
      </div>

      <section className="results-card">
        <div className="results-head">
          <div>
            <h2>全部对局</h2>
            <p>
              {allGames.length} 局 · 最新优先 · 点击任意一行查看复盘
              {allGames.length > games.length ? ` · 列表显示最近 ${games.length} 局，统计仍使用全部对局` : ""}
            </p>
          </div>
        </div>
        {games.length === 0 ? (
          <EmptyState icon="play" title="没有对局记录" desc="该批次尚未完成任何一局。" />
        ) : (
          <GameTable games={games} onOpen={setDetailNo} />
        )}
      </section>

      <StatsPanel simId={simId} open={statsOpen} onClose={() => setStatsOpen(false)} onOpenGame={(no) => { setStatsOpen(false); setDetailNo(no); }} />
      <GameDrawer open={detailNo !== null} simId={simId} gameNo={detailNo} onClose={() => setDetailNo(null)} />
    </div>
  );
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}
