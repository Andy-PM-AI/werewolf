import { useMemo, useState } from "react";
import type { Player } from "../lib/types";
import { GROUP_LABEL, PARAM_LABELS, TYPE_NAMES, formatDate, groupOf } from "../lib/format";
import { Button, Drawer, EmptyState, Modal, TypeBadge } from "./Ui";
import { Icon } from "./Icons";

export function GenderBadge({ gender }: { gender?: string | null }) {
  const value = (gender || "").trim();
  const tone = value.startsWith("男") ? "male" : value.startsWith("女") ? "female" : "unknown";
  return (
    <span className={`gender-badge gender-badge--${tone}`} aria-label={`性别 ${value || "未知"}`}>
      {value || "未知"}
    </span>
  );
}

export function PlayerAvatar({ player, size = 42 }: { player: { name: string; mbti: string }; size?: number }) {
  const group = groupOf(player.mbti);
  return (
    <span
      className={`player-avatar player-avatar--${group.toLowerCase()}`}
      style={{ width: size, height: size, fontSize: Math.max(13, size * 0.36) }}
      aria-hidden="true"
    >
      {player.name.slice(0, 1)}
    </span>
  );
}

const DIMS = [
  { key: "EI", left: "E", right: "I", leftName: "外倾", rightName: "内倾", leftKey: "E", rightKey: "I", pctKey: "E_pct" },
  { key: "SN", left: "S", right: "N", leftName: "感觉", rightName: "直觉", leftKey: "S", rightKey: "N", pctKey: "S_pct" },
  { key: "TF", left: "T", right: "F", leftName: "思维", rightName: "情感", leftKey: "T", rightKey: "F", pctKey: "T_pct" },
  { key: "JP", left: "J", right: "P", leftName: "判断", rightName: "知觉", leftKey: "J", rightKey: "P", pctKey: "J_pct" },
] as const;

function hasMbtiDims(player: Player): boolean {
  const dims = player.dims || ({} as Player["dims"]);
  return ["E", "I", "S", "N", "T", "F", "J", "P"].every((key) => key in dims);
}

export function DimensionBars({ player, compact = false }: { player: Player; compact?: boolean }) {
  const group = groupOf(player.mbti);
  return (
    <div className={`dims ${compact ? "dims--compact" : ""}`}>
      {DIMS.map((dim) => {
        // Use the raw answer counts, not a separately rounded percentage, so
        // the two segments always add up to the numbers printed on the card.
        const leftValue = Number(player.dims?.[dim.leftKey] || 0);
        const rightValue = Number(player.dims?.[dim.rightKey] || 0);
        const total = leftValue + rightValue;
        const storedPct = Number(player.dims?.[dim.pctKey] || 50);
        const leftShare = total > 0 ? (leftValue / total) * 100 : storedPct;
        const rightShare = 100 - leftShare;
        const strongLeft = leftShare >= 50;
        const title = `${dim.leftName} ${dim.left} ${leftValue} · ${dim.rightName} ${dim.right} ${rightValue}`;
        return (
          <div className="dim-row" key={dim.key} title={title}>
            <span className={`dim-row__side ${strongLeft ? "is-strong" : ""}`}>
              {dim.left} <b>{leftValue}</b>
            </span>
            <div
              className={`dim-track dim-track--${group.toLowerCase()}`}
              role="img"
              aria-label={title}
            >
              <span className="dim-track__fill dim-track__fill--left" style={{ width: `${leftShare}%` }} />
              <span className="dim-track__fill dim-track__fill--right" style={{ width: `${rightShare}%` }} />
            </div>
            <span className={`dim-row__side dim-row__side--right ${!strongLeft ? "is-strong" : ""}`}>
              <b>{rightValue}</b> {dim.right}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function paramLevel(value: number): { label: string; tone: string } {
  if (value >= 0.65) return { label: "高", tone: "high" };
  if (value <= 0.35) return { label: "低", tone: "low" };
  return { label: "中", tone: "mid" };
}

export function ParamChips({ player, limit }: { player: Player; limit?: number }) {
  const entries = Object.entries(player.params || {}).slice(0, limit);
  return (
    <div className="param-chips">
      {entries.map(([key, value]) => {
        const level = paramLevel(Number(value));
        return (
          <span className={`param-chip param-chip--${level.tone}`} key={key} title={`${PARAM_LABELS[key] || key}：${Number(value).toFixed(1)}`}>
            {PARAM_LABELS[key] || key}
            <b>{level.label}</b>
          </span>
        );
      })}
    </div>
  );
}

export function ParamGrid({ player }: { player: Player }) {
  return (
    <div className="param-grid">
      {Object.entries(player.params || {}).map(([key, value]) => {
        const level = paramLevel(Number(value));
        return (
          <div className="param-row" key={key}>
            <span className="param-row__label">{PARAM_LABELS[key] || key}</span>
            <div className="param-row__track">
              <span className={`param-row__fill param-row__fill--${level.tone}`} style={{ width: `${Number(value) * 100}%` }} />
            </div>
            <span className={`param-row__value param-row__value--${level.tone}`}>{level.label}</span>
          </div>
        );
      })}
    </div>
  );
}

export function PlayerCard({
  player,
  selected,
  selectionMode,
  onToggleSelect,
  onOpen,
  onDelete,
}: {
  player: Player;
  selected?: boolean;
  selectionMode?: boolean;
  onToggleSelect?: () => void;
  onOpen?: () => void;
  onDelete?: () => void;
}) {
  const tested = player.has_result !== false && Boolean(player.mbti);
  const showDims = tested && hasMbtiDims(player);
  return (
    <article className={`player-card ${selected ? "is-selected" : ""}`}>
      <div className="player-card__head">
        {selectionMode ? (
          <button
            type="button"
            className={`check-box ${selected ? "is-checked" : ""}`}
            onClick={(event) => {
              event.stopPropagation();
              onToggleSelect?.();
            }}
            aria-label={selected ? "取消选择" : "选择玩家"}
          >
            {selected ? <Icon name="check" size={12} /> : null}
          </button>
        ) : null}
        <button type="button" className="player-card__identity" onClick={onOpen}>
          <PlayerAvatar player={player} />
          <span className="player-card__name-block">
            <span className="player-card__name">{player.name}</span>
            <span className="player-card__meta">
              {player.age ? `${player.age}岁` : "年龄未知"} · {player.province || "地区未知"}
            </span>
          </span>
        </button>
        <span className="player-card__badges">
          <GenderBadge gender={player.gender} />
          {tested ? <TypeBadge type={player.mbti} name={player.type_name} /> : <span className="untested-badge">未测</span>}
        </span>
      </div>
      <button type="button" className="player-card__body" onClick={onOpen}>
        <div className="player-card__sub">
          <span>{player.occupation || "职业未知"}</span>
          <span className="dot-sep">·</span>
          <span>{player.education || "学历未知"}</span>
          {player.income ? (
            <>
              <span className="dot-sep">·</span>
              <span>月入 {player.income}</span>
            </>
          ) : null}
        </div>
        {showDims ? <DimensionBars player={player} compact /> : (
          <div className="player-card__untested">
            {tested ? `结果：${player.mbti}${player.type_name ? `（${player.type_name}）` : ""}` : "当前生效问卷还没有这位玩家的结果"}
          </div>
        )}
        <div className="player-card__footer">
          {tested ? <ParamChips player={player} limit={4} /> : <span className="muted">未测试</span>}
          <span className="player-card__created">{formatDate(player.created_at)}</span>
        </div>
      </button>
      {onDelete ? (
        <button
          type="button"
          className="player-card__delete"
          onClick={(event) => {
            event.stopPropagation();
            onDelete();
          }}
          aria-label={`删除 ${player.name}`}
          title="删除样本"
        >
          <Icon name="trash" size={15} />
        </button>
      ) : null}
    </article>
  );
}

export function PlayerPicker({
  open,
  onClose,
  players,
  selectedIds,
  title,
  subtitle,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  players: Player[];
  selectedIds: Set<string>;
  title: string;
  subtitle?: string;
  onPick: (player: Player) => void;
}) {
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return players.filter((player) => {
      if (type && player.mbti !== type) return false;
      if (!needle) return true;
      return `${player.name} ${player.occupation} ${player.province} ${player.mbti}`.toLowerCase().includes(needle);
    });
  }, [players, query, type]);

  const types = useMemo(() => {
    const counts: Record<string, number> = {};
    players.forEach((p) => {
      counts[p.mbti] = (counts[p.mbti] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [players]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      subtitle={subtitle}
      size="xl"
      footer={<Button variant="ghost" onClick={onClose}>取消</Button>}
    >
      <div className="picker-toolbar">
        <div className="search-box">
          <Icon name="search" size={17} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索姓名、职业、地区或性格"
            autoFocus
          />
        </div>
        <div className="picker-types">
          <button type="button" className={`type-filter ${type === "" ? "is-active" : ""}`} onClick={() => setType("")}>
            全部 <b>{players.length}</b>
          </button>
          {types.map(([code, count]) => (
            <button
              type="button"
              key={code}
              className={`type-filter ${type === code ? "is-active" : ""}`}
              onClick={() => setType(code)}
            >
              {code} <b>{count}</b>
            </button>
          ))}
        </div>
      </div>
      <div className="picker-list">
        {filtered.length === 0 ? (
          <EmptyState icon="search" title="没有匹配的玩家" desc="换个关键词，或先到玩家库抽取样本。" />
        ) : (
          filtered.map((player) => {
            const taken = selectedIds.has(player.id);
            return (
              <button
                type="button"
                key={player.id}
                className={`picker-row ${taken ? "is-taken" : ""}`}
                disabled={taken}
                onClick={() => onPick(player)}
              >
                <PlayerAvatar player={player} size={38} />
                <span className="picker-row__main">
                  <span className="picker-row__name">
                    {player.name}
                    {taken ? <em className="picker-row__taken">已选</em> : null}
                  </span>
                  <span className="picker-row__meta">
                    {player.age ? `${player.age}岁` : "—"} · {player.gender || "性别未知"} · {player.occupation || "职业未知"} · {player.province || "地区未知"}
                  </span>
                </span>
                <TypeBadge type={player.mbti} name={player.type_name} size="sm" />
                <span className="picker-row__params">
                  <ParamChips player={player} limit={2} />
                </span>
                <Icon name="chevronRight" size={16} className="picker-row__chevron" />
              </button>
            );
          })
        )}
      </div>
    </Modal>
  );
}

export function PlayerDetailDrawer({
  player,
  onClose,
  onDelete,
  onRetest,
  retesting,
}: {
  player: Player | null;
  onClose: () => void;
  onDelete?: (player: Player) => void;
  onRetest?: (player: Player) => void;
  retesting?: boolean;
}) {
  const tested = Boolean(player?.has_result !== false && player?.mbti);
  const showDims = Boolean(player && tested && hasMbtiDims(player));
  return (
    <Drawer open={Boolean(player)} onClose={onClose} width={620} label="玩家档案">
      {player ? (
        <div className="player-detail">
          <div className="drawer-head">
            <div className="drawer-head__title">
              <PlayerAvatar player={player} size={54} />
              <div>
                <div className="drawer-head__eyebrow">{GROUP_LABEL[groupOf(player.mbti)]} · {TYPE_NAMES[player.mbti] || "探索型"}</div>
                <h2>{player.name}</h2>
                <div className="drawer-head__sub">
                  {player.age ? `${player.age}岁` : "年龄未知"} · {player.gender || "性别未知"} · {player.province || "地区未知"}
                </div>
              </div>
            </div>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭">
              <Icon name="close" size={18} />
            </button>
          </div>
          <div className="player-detail__badges">
            {tested ? <TypeBadge type={player.mbti} name={player.type_name} size="lg" showName /> : <span className="untested-badge">当前问卷未测</span>}
            <span className="soft-badge">{player.occupation || "职业未知"}</span>
            <span className="soft-badge">{player.education || "学历未知"}</span>
            {player.income ? <span className="soft-badge">月入 {player.income} 元</span> : null}
            {player.test_fallback ? <span className="soft-badge soft-badge--warn">测验补答</span> : null}
          </div>

          {showDims ? (
            <section className="detail-section">
              <h4>四维倾向</h4>
              <DimensionBars player={player} />
            </section>
          ) : null}

          {tested ? (
            <section className="detail-section">
              <h4>行为参数</h4>
              <p className="detail-note">问卷结果只用来生成行为参数，不直接写进发言 prompt。</p>
              <ParamGrid player={player} />
            </section>
          ) : null}

          <section className="detail-section">
            <h4>人物小传</h4>
            <p className="persona-text">{player.persona || "暂无人物小传。"}</p>
          </section>

          {player.profile_json?.big_five ? (
            <section className="detail-section">
              <h4>心理测量底稿</h4>
              <div className="bigfive">
                {Object.entries(player.profile_json.big_five).map(([key, value]) => (
                  <div key={key} className="bigfive__item">
                    <span>{key}</span>
                    <b>{String(value)}</b>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className="detail-section detail-section--foot">
            <div>
              <span className="muted">来源 {player.source === "audiencelib" ? "AudienceLib 人口库" : player.source}</span>
              <span className="muted"> · 入库 {formatDate(player.created_at)}</span>
              <span className="muted"> · 问卷 {player.answer_count ?? 93} 题</span>
            </div>
            <div className="detail-actions">
              {onRetest ? (
                <Button variant="secondary" size="sm" icon="refresh" loading={retesting} onClick={() => onRetest(player)}>
                  用当前问卷重新测验
                </Button>
              ) : null}
              {onDelete ? (
                <Button variant="danger" size="sm" icon="trash" onClick={() => onDelete(player)}>
                  删除样本
                </Button>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </Drawer>
  );
}
