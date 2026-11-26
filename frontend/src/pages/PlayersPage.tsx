import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import type { Catalog, Player, PlayerStats, Questionnaire } from "../lib/types";
import { formatDate } from "../lib/format";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  IconButton,
  SectionHead,
  Spinner,
  StatTile,
  useToast,
} from "../components/Ui";
import { Icon } from "../components/Icons";
import { PlayerCard, PlayerDetailDrawer } from "../components/PlayerBits";
import { SampleModal } from "../components/SampleModal";

const DIM_FILTERS = [
  { key: "EI", options: ["E", "I"], label: "E / I" },
  { key: "SN", options: ["S", "N"], label: "S / N" },
  { key: "TF", options: ["T", "F"], label: "T / F" },
  { key: "JP", options: ["J", "P"], label: "J / P" },
] as const;

export function PlayersPage({ catalog, onNavigate }: { catalog: Catalog | null; onNavigate: (path: string) => void }) {
  const toast = useToast();
  const [stats, setStats] = useState<PlayerStats | null>(null);
  const [questionnaires, setQuestionnaires] = useState<Questionnaire[]>([]);
  const [activeQuestionnaireId, setActiveQuestionnaireId] = useState("");
  const [switching, setSwitching] = useState(false);
  const [players, setPlayers] = useState<Player[]>([]);
  const [total, setTotal] = useState(0);
  const [types, setTypes] = useState<Record<string, number>>({});
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const [dims, setDims] = useState<Record<string, string>>({ EI: "", SN: "", TF: "", JP: "" });
  const [loading, setLoading] = useState(true);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sampleOpen, setSampleOpen] = useState(false);
  const [detail, setDetail] = useState<Player | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Player | null>(null);
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [retesting, setRetesting] = useState(false);
  const searchTimer = useRef<number | undefined>(undefined);

  const loadStats = useCallback(async () => {
    try {
      const data = await api.playerStats();
      setStats(data);
      setTypes(data.types);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "读取统计失败", "error");
    }
  }, [toast]);

  const loadQuestionnaires = useCallback(async () => {
    try {
      const data = await api.questionnaires();
      setQuestionnaires(data.items);
      setActiveQuestionnaireId(data.active_id);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "读取问卷列表失败", "error");
    }
  }, [toast]);

  const loadPlayers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.players({
        type,
        q: search,
        EI: dims.EI,
        SN: dims.SN,
        TF: dims.TF,
        JP: dims.JP,
        limit: 500,
      });
      setPlayers(data.players);
      setTotal(data.total);
      if (Object.keys(data.types).length) setTypes(data.types);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "读取玩家库失败", "error");
    } finally {
      setLoading(false);
    }
  }, [type, search, dims, toast]);

  useEffect(() => {
    loadStats();
    loadQuestionnaires();
  }, [loadStats, loadQuestionnaires]);

  useEffect(() => {
    window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(() => {
      loadPlayers();
    }, search ? 220 : 0);
    return () => window.clearTimeout(searchTimer.current);
  }, [loadPlayers, search]);

  const refresh = useCallback(() => {
    loadStats();
    loadPlayers();
    loadQuestionnaires();
  }, [loadStats, loadPlayers, loadQuestionnaires]);

  const switchQuestionnaire = async (id: string) => {
    if (!id || id === activeQuestionnaireId) return;
    setSwitching(true);
    try {
      await api.activateQuestionnaire(id);
      setActiveQuestionnaireId(id);
      setType("");
      setDims({ EI: "", SN: "", TF: "", JP: "" });
      refresh();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "切换问卷失败", "error");
    } finally {
      setSwitching(false);
    }
  };

  const activeQuestionnaire = questionnaires.find((item) => item.id === activeQuestionnaireId);

  const toggleSelect = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const retestOne = async () => {
    if (!detail) return;
    setRetesting(true);
    try {
      const result = await api.retestPlayer(detail.id);
      setDetail(result.player);
      toast.push(`${result.player.name} 已重新测验：${result.player.mbti}`, "success");
      refresh();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "重新测验失败", "error");
    } finally {
      setRetesting(false);
    }
  };

  const deleteOne = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.deletePlayers([deleteTarget.id]);
      toast.push(`已删除 ${deleteTarget.name}`, "success");
      setDeleteTarget(null);
      if (detail?.id === deleteTarget.id) setDetail(null);
      refresh();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "删除失败", "error");
    } finally {
      setDeleting(false);
    }
  };

  const deleteBulk = async () => {
    setDeleting(true);
    try {
      const result = await api.deletePlayers([...selected]);
      toast.push(`已删除 ${result.removed} 位玩家`, "success");
      setSelected(new Set());
      setBulkConfirm(false);
      refresh();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "删除失败", "error");
    } finally {
      setDeleting(false);
    }
  };

  const hasFilters = Boolean(type || search || dims.EI || dims.SN || dims.TF || dims.JP);
  const isMbti = !stats?.questionnaire || stats.questionnaire.kind === "mbti";
  const typeChips = useMemo(
    () => Object.entries(types)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([code, count]) => ({ code, count })),
    [types],
  );

  return (
    <div className="page players-page">
      <div className="page-head">
        <div>
          <div className="eyebrow">POPULATION LIBRARY · 人口样本库</div>
          <h1 className="page-title">玩家库</h1>
          <p className="page-desc">
            从 AudienceLib 抽取真实人口画像。当前生效问卷：{activeQuestionnaire?.name || "加载中…"}。人格结果不是标签，而是一组会改变发言、投票和冒险行为参数。
          </p>
        </div>
        <div className="page-actions page-actions--questionnaire">
          <label className="active-q-select">
            <span>生效问卷</span>
            <select value={activeQuestionnaireId} disabled={switching} onChange={(event) => switchQuestionnaire(event.target.value)}>
              {questionnaires.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <Button variant="secondary" icon="layers" onClick={() => onNavigate("/questionnaires")}>问卷管理</Button>
          <Button
            variant={selectionMode ? "primary" : "ghost"}
            icon="check"
            onClick={() => {
              setSelectionMode((value) => !value);
              setSelected(new Set());
            }}
          >
            {selectionMode ? "批量管理中" : "批量管理"}
          </Button>
          <Button variant="primary" icon="sparkles" onClick={() => setSampleOpen(true)}>
            抽取样本
          </Button>
        </div>
      </div>

      <div className="stat-row">
        <StatTile label="样本总数" value={stats?.total ?? "—"} hint={stats ? `当前问卷已测 ${stats.tested ?? 0} 人` : "玩家库总人数"} icon="users" tone="ochre" />
        <StatTile label="覆盖性格" value={stats ? `${stats.type_count} / 16` : "—"} hint="16 型中已有样本的类型" icon="layers" />
        <StatTile
          label="最近入库"
          value={stats?.last_created ? formatDate(stats.last_created) : "尚无"}
          hint={stats?.fallback ? `${stats.fallback} 位使用补答兜底` : "最近入库的样本"}
          icon="clock"
        />
        <StatTile
          label="问卷覆盖率"
          value={stats ? `${Math.round((stats.coverage || 0) * 100)}%` : "—"}
          hint={stats ? `${stats.tested ?? 0} / ${stats.total} 人已完成` : "当前生效问卷"}
          icon="chart"
          tone="violet"
        />
      </div>

      <section className="library-panel">
        <div className="library-toolbar">
          <div className="search-box search-box--library">
            <Icon name="search" size={17} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索姓名、职业、地区或性格代码"
            />
            {search ? (
              <button type="button" className="search-clear" onClick={() => setSearch("")} aria-label="清空搜索">
                <Icon name="close" size={14} />
              </button>
            ) : null}
          </div>
          <div className="type-chip-row">
            <button type="button" className={`type-chip ${type === "" ? "is-active" : ""}`} onClick={() => setType("")}>
              全部 <b>{stats?.total ?? total}</b>
            </button>
            {typeChips.map(({ code, count }) => (
              <button
                type="button"
                key={code}
                className={`type-chip type-chip--${code.includes("N") ? (code.includes("T") ? "nt" : "nf") : (code.includes("J") ? "sj" : "sp")} ${type === code ? "is-active" : ""} ${count === 0 ? "is-empty" : ""}`}
                onClick={() => setType(type === code ? "" : code)}
              >
                {code} <b>{count}</b>
              </button>
            ))}
          </div>
        </div>
        {isMbti ? <div className="dim-filter-row">
          <span className="dim-filter-row__label"><Icon name="filter" size={14} /> 维度筛选</span>
          {DIM_FILTERS.map((dim) => (
            <div className="dim-filter" key={dim.key}>
              <span>{dim.label}</span>
              {dim.options.map((letter) => (
                <button
                  type="button"
                  key={letter}
                  className={`dim-filter__btn ${dims[dim.key] === letter ? "is-active" : ""}`}
                  onClick={() => setDims((current) => ({ ...current, [dim.key]: current[dim.key] === letter ? "" : letter }))}
                >
                  {letter}
                </button>
              ))}
            </div>
          ))}
          {hasFilters ? (
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setType("");
                setSearch("");
                setDims({ EI: "", SN: "", TF: "", JP: "" });
              }}
            >
              清除筛选
            </button>
          ) : null}
          <span className="dim-filter-row__count">{loading ? "读取中…" : `显示 ${players.length} / ${total} 位`}</span>
        </div> : null}

        {selectionMode ? (
          <div className="bulk-bar">
            <span>已选 <b>{selected.size}</b> 位玩家</span>
            <div>
              <button type="button" className="link-btn" onClick={() => setSelected(new Set(players.map((p) => p.id)))}>全选当前页</button>
              <button type="button" className="link-btn" onClick={() => setSelected(new Set())}>清空</button>
              <Button variant="danger" size="sm" icon="trash" disabled={!selected.size} onClick={() => setBulkConfirm(true)}>
                删除选中
              </Button>
            </div>
          </div>
        ) : null}

        {loading && !players.length ? (
          <div className="panel-loading"><Spinner size={24} /><span>正在读取玩家库…</span></div>
        ) : players.length === 0 ? (
          <EmptyState
            icon={hasFilters ? "search" : "users"}
            title={hasFilters ? "没有符合条件的玩家" : "玩家库还是空的"}
            desc={hasFilters ? "换一个性格标签或维度组合试试。" : "先抽取一批人口样本，系统会自动为每个人完成 MBTI 问卷并绑定人格。"}
            action={!hasFilters ? <Button variant="primary" icon="sparkles" onClick={() => setSampleOpen(true)}>抽取第一批样本</Button> : null}
          />
        ) : (
          <div className="player-grid">
            {players.map((player) => (
              <PlayerCard
                key={player.id}
                player={player}
                selected={selected.has(player.id)}
                selectionMode={selectionMode}
                onToggleSelect={() => toggleSelect(player.id)}
                onOpen={() => setDetail(player)}
                onDelete={() => setDeleteTarget(player)}
              />
            ))}
          </div>
        )}
        {players.length < total ? (
          <div className="load-more">
            <span>仅显示前 {players.length} 位，请用筛选缩小范围。</span>
          </div>
        ) : null}
      </section>

      <div className="players-footnote">
        <Icon name="info" size={15} />
        <span>样本来自 AudienceLib 合成人口，不是真人调查。MBTI 结果由模型以人物身份作答后按标准 93 题规则计分。</span>
      </div>

      <SampleModal open={sampleOpen} onClose={() => setSampleOpen(false)} catalog={catalog} onDone={refresh} questionnaireName={activeQuestionnaire?.name} />
      <PlayerDetailDrawer player={detail} onClose={() => setDetail(null)} onDelete={(player) => setDeleteTarget(player)} onRetest={retestOne} retesting={retesting} />
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除样本"
        message={<>确定从玩家库删除 <b>{deleteTarget?.name}</b>？正在使用该玩家的模拟不会自动停止，但后续局可能因人数不足而报错。</>}
        confirmText={deleting ? "删除中…" : "删除"}
        danger
        onCancel={() => setDeleteTarget(null)}
        onConfirm={deleteOne}
      />
      <ConfirmDialog
        open={bulkConfirm}
        title="批量删除样本"
        message={<>确定删除已选中的 <b>{selected.size}</b> 位玩家？此操作不可撤销。</>}
        confirmText={deleting ? "删除中…" : "全部删除"}
        danger
        onCancel={() => setBulkConfirm(false)}
        onConfirm={deleteBulk}
      />
    </div>
  );
}

function dominantDimension(stats: PlayerStats): string {
  const counts: Record<string, number> = { E: 0, I: 0, S: 0, N: 0, T: 0, F: 0, J: 0, P: 0 };
  Object.values(stats.dimensions || {}).forEach((values) => {
    Object.entries(values).forEach(([letter, count]) => {
      counts[letter] = (counts[letter] || 0) + count;
    });
  });
  const opposite: Record<string, string> = { E: "I", I: "E", S: "N", N: "S", T: "F", F: "T", J: "P", P: "J" };
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  if (!top || !top[1]) return "—";
  const pair = top[1] + (counts[opposite[top[0]]] || 0);
  return `${top[0]} ${Math.round((top[1] / Math.max(1, pair)) * 100)}%`;
}
