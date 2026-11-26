import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { Analysis, GameSummary, TypeStat } from "../lib/types";
import { TYPE_NAMES, pct } from "../lib/format";
import { Button, Modal, Spinner, StatTile, TypeBadge, useToast } from "./Ui";
import { Icon } from "./Icons";
import { CampSplitBar, WinRateChart } from "./Charts";

function computeSlice(games: GameSummary[], upTo: number) {
  const slice = games.filter((game) => game.game_no <= upTo);
  const camps = { wolf: 0, good: 0, draw: 0 };
  const byType = new Map<string, TypeStat>();
  let rounds = 0;
  slice.forEach((game) => {
    if (game.winner === "wolf") camps.wolf += 1;
    else if (game.winner === "good") camps.good += 1;
    else camps.draw += 1;
    rounds += game.rounds;
    const type = game.variable_type || "—";
    const item = byType.get(type) || {
      type,
      type_name: TYPE_NAMES[type] || "",
      games: 0,
      wolf_games: 0,
      wolf_wins: 0,
      good_games: 0,
      good_wins: 0,
      appearances: 0,
      player_wins: 0,
      rounds: 0,
      tokens: 0,
      wolf_rate: 0,
      good_rate: 0,
      player_rate: 0,
      avg_rounds: 0,
    };
    const wolf = game.variable_camp_wins?.wolf || { players: 0, wins: 0 };
    const good = game.variable_camp_wins?.good || { players: 0, wins: 0 };
    item.games += 1;
    if (wolf.players) {
      item.wolf_games += 1;
      item.wolf_wins += wolf.wins;
    }
    if (good.players) {
      item.good_games += 1;
      item.good_wins += good.wins;
    }
    item.appearances += game.variable_player_count || 0;
    item.player_wins += game.variable_player_wins || 0;
    item.rounds += game.rounds;
    item.tokens += game.tokens;
    byType.set(type, item);
  });
  const rows = [...byType.values()].map((item) => ({
    ...item,
    wolf_rate: item.wolf_games ? item.wolf_wins / item.wolf_games : 0,
    good_rate: item.good_games ? item.good_wins / item.good_games : 0,
    player_rate: item.appearances ? item.player_wins / item.appearances : 0,
    avg_rounds: item.games ? item.rounds / item.games : 0,
  }));
  rows.sort((a, b) => b.player_rate - a.player_rate || b.games - a.games || a.type.localeCompare(b.type));
  return {
    games: slice.length,
    camps,
    rows,
    avgRounds: slice.length ? rounds / slice.length : 0,
  };
}

export function StatsPanel({
  simId,
  open,
  onClose,
  onOpenGame,
}: {
  simId: string;
  open: boolean;
  onClose: () => void;
  onOpenGame?: (no: number) => void;
}) {
  const toast = useToast();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [upTo, setUpTo] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [showTable, setShowTable] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.analysis(simId);
      setAnalysis(data);
      const n = Math.max(1, data.games.length);
      setUpTo(n);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "读取统计失败", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      setPlaying(false);
      setShowTable(false);
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, simId]);

  const total = analysis?.games.length || 0;

  useEffect(() => {
    if (!playing || !total) return;
    const timer = window.setInterval(() => {
      setUpTo((value) => {
        if (value >= total) {
          setPlaying(false);
          return total;
        }
        return value + 1;
      });
    }, 280);
    return () => window.clearInterval(timer);
  }, [playing, total]);

  const slice = useMemo(() => (analysis ? computeSlice(analysis.games, upTo) : null), [analysis, upTo]);
  const timeline = useMemo(() => (analysis ? analysis.stats.timeline.slice(0, upTo) : []), [analysis, upTo]);
  const current = analysis?.snapshot;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="分角色 × 分性格胜率"
      subtitle="拖动进度条，观察结论从第 1 局到第 n 局如何稳定下来。"
      size="xl"
      className="stats-modal"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>关闭</Button>
          <Button variant="secondary" icon="refresh" onClick={load} loading={loading}>刷新数据</Button>
        </>
      }
    >
      {loading && !analysis ? (
        <div className="panel-loading"><Spinner size={26} /><span>正在汇总全部对局…</span></div>
      ) : !analysis || !slice ? (
        <div className="panel-loading">暂无统计数据</div>
      ) : total === 0 ? (
        <div className="panel-loading">还没有完成任何一局。</div>
      ) : (
        <div className="stats-panel">
          <div className="stats-head">
            <div>
              <span className="eyebrow">SIMULATION ANALYSIS</span>
              <h3>第 1 – {upTo} 局 · 共 {slice.games} 个有效样本</h3>
              <p>
                {current?.status === "running"
                  ? `模拟仍在运行，已完成 ${current.completed_games} / ${current.total_games} 局。`
                  : `本次模拟共完成 ${current?.completed_games ?? total} 局。`}
              </p>
            </div>
            <div className="stats-slider-wrap">
              <div className="stats-slider__head">
                <button type="button" className="link-btn" onClick={() => setPlaying((value) => !value)}>
                  <Icon name={playing ? "pause" : "play"} size={14} /> {playing ? "暂停回放" : "自动回放"}
                </button>
                <span>观察至第 <b>{upTo}</b> 局</span>
              </div>
              <input
                type="range"
                min={1}
                max={Math.max(1, total)}
                value={upTo}
                onChange={(event) => {
                  setPlaying(false);
                  setUpTo(Number(event.target.value));
                }}
                className="stats-slider"
              />
              <div className="stats-slider__labels"><span>第 1 局</span><span>第 {total} 局</span></div>
            </div>
          </div>

          <div className="stat-row stat-row--stats">
            <StatTile label="狼人方胜率" value={pct(slice.camps.wolf / Math.max(1, slice.games))} hint={`${slice.camps.wolf} 胜`} tone="wolf" />
            <StatTile label="好人方胜率" value={pct(slice.camps.good / Math.max(1, slice.games))} hint={`${slice.camps.good} 胜`} tone="good" />
            <StatTile label="未决率" value={pct(slice.camps.draw / Math.max(1, slice.games))} hint={`${slice.camps.draw} 局未决`} />
            <StatTile label="平均轮次" value={slice.avgRounds.toFixed(1)} hint="8 轮未分胜负判未决" tone="violet" />
          </div>

          <div className="stats-chart-card">
            <CampSplitBar camps={slice.camps} compact />
            <WinRateChart points={analysis.stats.timeline} upTo={upTo} />
            <div className="chart-foot">
              <span>曲线为累计胜率，不是单局胜率。</span>
              <button type="button" className="link-btn" onClick={() => setShowTable((value) => !value)}>
                {showTable ? "收起数据表" : "查看数据表"}
              </button>
            </div>
            {showTable ? (
              <div className="chart-data-table">
                <table>
                  <thead>
                    <tr><th>局数</th><th>狼人胜率</th><th>好人胜率</th><th>未决率</th></tr>
                  </thead>
                  <tbody>
                    {timeline
                      .filter((point, index) => index === 0 || (index + 1) % Math.max(1, Math.ceil(total / 12)) === 0 || index === timeline.length - 1)
                      .map((point) => (
                        <tr key={point.no}>
                          <td>第 {point.no} 局</td>
                          <td>{pct(point.wolf_rate, 1)}</td>
                          <td>{pct(point.good_rate, 1)}</td>
                          <td>{pct(point.draw_rate, 1)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>

          <div className="type-stats">
            <div className="type-stats__head">
              <div>
                <h4>分变量性格</h4>
                <p>每局所有变量角色共享同一性格。若变量角色同时跨两个阵营，狼/好两列会分别统计。</p>
              </div>
              <span className="type-stats__count">{slice.rows.length} 种性格有样本</span>
            </div>
            <div className="type-table-wrap">
              <table className="type-table">
                <thead>
                  <tr>
                    <th>性格</th>
                    <th>局数</th>
                    <th>狼人方</th>
                    <th>好人方</th>
                    <th className="type-table__rate">变量玩家胜率</th>
                    <th>平均轮次</th>
                  </tr>
                </thead>
                <tbody>
                  {slice.rows.map((row) => (
                    <tr key={row.type}>
                      <td>
                        <div className="type-cell">
                          <TypeBadge type={row.type} size="sm" />
                          <span>{row.type_name || ""}</span>
                        </div>
                      </td>
                      <td>{row.games}</td>
                      <td>{row.wolf_games ? `${pct(row.wolf_rate)}（${row.wolf_wins}/${row.wolf_games}）` : "—"}</td>
                      <td>{row.good_games ? `${pct(row.good_rate)}（${row.good_wins}/${row.good_games}）` : "—"}</td>
                      <td className="type-table__rate">
                        <div className="rate-cell">
                          <div className="rate-cell__track"><span style={{ width: `${row.player_rate * 100}%` }} /></div>
                          <b>{pct(row.player_rate)}</b>
                        </div>
                      </td>
                      <td>{row.avg_rounds.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="type-stats__note">
              “变量玩家胜率”= 变量玩家所在阵营获胜的次数 / 变量玩家出场次数。它同时受到角色分配和阵营基础胜率影响，不能直接当作性格强弱。
            </p>
          </div>

          <div className="stats-games-hint">
            <Icon name="info" size={15} />
            <span>要核对某一局，请关闭统计面板，在结果列表中打开该局复盘。</span>
            {onOpenGame && slice.games ? (
              <button type="button" className="link-btn" onClick={() => {
                const recent = analysis.games[analysis.games.length - 1];
                if (recent) onOpenGame(recent.game_no);
              }}>
                打开最近一局
              </button>
            ) : null}
          </div>
        </div>
      )}
    </Modal>
  );
}
