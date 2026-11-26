import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { GameDetail, GameEvent, GamePlayer } from "../lib/types";
import {
  WINNER_LABEL,
  formatDate,
  formatDuration,
  pct,
  roleSummary,
} from "../lib/format";
import { Drawer, EmptyState, Modal, RoleBadge, Spinner, Tabs, TypeBadge, WinnerBadge } from "./Ui";
import { Icon } from "./Icons";

type Tab = "replay" | "players" | "data";

function seatName(players: GamePlayer[], seat?: number | null): string {
  if (!seat) return "—";
  const player = players.find((item) => item.seat === seat);
  return player ? `${seat}号 ${player.name}` : `${seat}号`;
}

function playerBySeat(players: GamePlayer[], seat?: number | null): GamePlayer | undefined {
  return seat ? players.find((item) => item.seat === seat) : undefined;
}

function NightPanel({ event, players }: { event: GameEvent; players: GamePlayer[] }) {
  const dawn = event as unknown as {
    wolf_target?: number | null;
    wolf_choices?: { seat: number; name: string; target: number }[];
    saved?: boolean;
    poisoned?: number | null;
    seer_check?: { target: number; result: string } | null;
    deaths?: { seat: number; name: string; role: string; role_name: string; cause: string }[];
  };
  const witch = players.find((p) => p.role === "witch");
  const seer = players.find((p) => p.role === "seer");
  const wolfTarget = dawn.wolf_target;
  const checked = dawn.seer_check;
  const poisoned = dawn.poisoned;
  return (
    <div className="night-panel">
      <div className="night-panel__head">
        <span className="night-panel__title"><Icon name="moon" size={15} /> 夜间行动（赛后可见）</span>
        <span className="night-panel__hint">狼人 → 女巫 → 预言家</span>
      </div>
      <div className="night-grid">
        <div className="night-cell">
          <span className="night-cell__label"><Icon name="paw" size={14} /> 狼人刀人</span>
          <strong>{wolfTarget ? seatName(players, wolfTarget) : "空刀"}</strong>
          {dawn.wolf_choices?.length ? (
            <div className="night-cell__sub">
              {dawn.wolf_choices.map((choice) => (
                <span key={`${choice.seat}-${choice.target}`}>{choice.seat}号→{choice.target}号</span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="night-cell">
          <span className="night-cell__label"><Icon name="flask" size={14} /> 女巫用药</span>
          <strong>{!witch
            ? "无女巫"
            : !witch.alive && (witch.death_round ?? 99) < event.round
              ? "已出局"
              : (dawn.saved ? "使用解药" : "未用解药") + (witch.alive ? "" : "（同夜出局）")}</strong>
          {poisoned ? <div className="night-cell__sub night-cell__sub--danger">毒药 → {seatName(players, poisoned)}</div> : <div className="night-cell__sub">未用毒药</div>}
        </div>
        <div className="night-cell">
          <span className="night-cell__label"><Icon name="eye" size={14} /> 预言家查验</span>
          <strong>{checked ? seatName(players, checked.target) : "未查验"}</strong>
          {checked ? (
            <div className={`night-cell__sub ${checked.result === "wolf" ? "night-cell__sub--danger" : "night-cell__sub--good"}`}>
              结果：{checked.result === "wolf" ? "狼人" : "好人"}
            </div>
          ) : null}
        </div>
        <div className="night-cell">
          <span className="night-cell__label"><Icon name="skull" size={14} /> 天亮死亡</span>
          <strong>{dawn.deaths?.length ? `${dawn.deaths.length} 人` : "平安夜"}</strong>
          <div className="night-cell__sub">
            {dawn.deaths?.length
              ? dawn.deaths.map((death) => `${death.seat}号 ${death.role_name}${death.cause === "poison" ? "（毒）" : ""}`).join("、")
              : "无人死亡"}
          </div>
        </div>
      </div>
      <div className="night-panel__note">
        女巫 {witch?.name || "—"} · 预言家 {seer?.name || "—"}。以上信息赛后公开，局中只对当事人可见。
      </div>
    </div>
  );
}

function SpeechBubble({
  event,
  players,
  onOpen,
}: {
  event: GameEvent;
  players: GamePlayer[];
  onOpen: () => void;
}) {
  const speech = event as unknown as {
    seat: number;
    name: string;
    role: string;
    role_name: string;
    mbti: string;
    text: string;
    thinking?: string;
    claimed_role?: string | null;
    accused?: number[];
    vote_intent?: number | null;
    state_repair?: number;
    fallback?: boolean;
  };
  const player = playerBySeat(players, speech.seat);
  return (
    <div
      className={`speech speech--clickable ${player?.camp === "wolf" ? "speech--wolf" : ""}`}
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      aria-label={`查看 ${speech.seat}号 ${speech.name} 本轮的思考过程`}
    >
      <div className="speech__avatar">{speech.name.slice(0, 1)}</div>
      <div className="speech__body">
        <div className="speech__head">
          <b>{speech.seat} 号 · {speech.name}</b>
          <TypeBadge type={speech.mbti} size="sm" />
          <RoleBadge role={player?.role || "villager"} size="sm" />
          {player?.is_variable ? <span className="variable-dot" title="本局变量角色">变量</span> : null}
          <span className="speech__thinking-hint"><Icon name="sparkles" size={12} /> 思考</span>
        </div>
        <p className="speech__text">{speech.text}</p>
        <div className="speech__meta">
          {speech.claimed_role ? <span className="speech-tag speech-tag--claim">跳 {speech.claimed_role}</span> : null}
          {speech.accused?.length ? <span className="speech-tag speech-tag--accuse">指认 {speech.accused.map((s) => `${s}号`).join("、")}</span> : null}
          {speech.vote_intent ? <span className="speech-tag speech-tag--intent">倾向投 {speech.vote_intent}号</span> : null}
          {speech.state_repair ? <span className="speech-tag speech-tag--repair">已修正越界发言</span> : null}
          {speech.fallback ? <span className="speech-tag speech-tag--warn">兜底发言</span> : null}
        </div>
      </div>
    </div>
  );
}

function VoteCard({ event, players }: { event: GameEvent; players: GamePlayer[] }) {
  const vote = event as unknown as {
    votes: { voter: number; target: number | null; reason?: string; consistency?: string }[];
    tally: Record<string, number>;
    tie: boolean;
    eliminated: number | null;
    summary: string;
  };
  const tally = Object.entries(vote.tally || {})
    .map(([seat, count]) => ({ seat: Number(seat), count }))
    .sort((a, b) => b.count - a.count || a.seat - b.seat);
  return (
    <div className="vote-card">
      <div className="vote-card__head">
        <span><Icon name="flag" size={15} /> 投票</span>
        <strong>{vote.summary}</strong>
      </div>
      <div className="vote-card__chips">
        {vote.votes?.map((item) => (
          <span className={`vote-chip ${item.target !== null && vote.eliminated === item.target ? "vote-chip--target" : ""}`} key={`${item.voter}-${item.target}`}>
            {item.voter}号 <Icon name="arrowUpRight" size={11} /> {item.target === null ? "弃票" : `${item.target}号`}
          </span>
        ))}
      </div>
      {vote.votes?.some((item) => item.reason) ? (
        <div className="vote-reasons">
          {vote.votes.filter((item) => item.reason).map((item) => (
            <div key={`reason-${item.voter}`}>
              <b>{item.voter}号</b>
              <span>{item.reason}</span>
              {item.consistency === "changed_with_reason" ? <em>改票</em> : null}
              {item.consistency === "waited_then_voted" ? <em>说等却投</em> : null}
            </div>
          ))}
        </div>
      ) : null}
      {tally.length ? (
        <div className="vote-tally">
          {tally.map((item) => (
            <div className="vote-tally__row" key={item.seat}>
              <span>{seatName(players, item.seat)}</span>
              <div className="vote-tally__bar"><span style={{ width: `${Math.max(12, (item.count / Math.max(...tally.map((t) => t.count))) * 100)}%` }} /></div>
              <b>{item.count} 票</b>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Replay({ game, onOpenSpeech }: { game: GameDetail; onOpenSpeech: (event: GameEvent) => void }) {
  const events = game.detail.events;
  const players = game.detail.players;
  const items: { event: GameEvent; index: number }[] = [];
  events.forEach((event, index) => {
    if (["game_start", "final_players", "day", "night", "witch", "seer"].includes(event.type)) return;
    items.push({ event, index });
  });
  let lastRound = 0;
  return (
    <div className="replay">
      <div className="replay__summary">
        <span><Icon name="seed" size={14} /> Seed {game.seed}</span>
        <span><Icon name="clock" size={14} /> {formatDuration(game.duration_ms)}</span>
        <span><Icon name="tokens" size={14} /> {game.tokens.toLocaleString()} tokens</span>
        <span><Icon name="layers" size={14} /> {game.rounds} 轮</span>
      </div>
      {items.map(({ event, index }) => {
        const isNewRound = event.round !== lastRound;
        lastRound = event.round;
        return (
          <div key={index}>
            {isNewRound ? (
              <div className="round-marker">
                <span className="round-marker__line" />
                <span className="round-marker__label">第 {event.round} 轮</span>
                <span className="round-marker__line" />
              </div>
            ) : null}
            {event.type === "dawn" ? (
              <>
                <NightPanel event={event} players={players} />
                <div className="public-divider"><Icon name="sun" size={14} /> {String(event.public || "")}</div>
              </>
            ) : null}
            {event.type === "speech" ? <SpeechBubble event={event} players={players} onOpen={() => onOpenSpeech(event)} /> : null}
            {event.type === "vote" ? <VoteCard event={event} players={players} /> : null}
            {event.type === "last_words" ? (
              <div className="last-words">
                <Icon name="book" size={16} />
                <div>
                  <b>{seatName(players, Number((event as unknown as { seat: number }).seat))} 的遗言</b>
                  <p>{String((event as unknown as { text: string }).text || "")}</p>
                </div>
              </div>
            ) : null}
            {event.type === "hunter_shot" ? (
              <div className="hunter-shot">
                <Icon name="crosshair" size={16} />
                <span>{String(event.public || "猎人开枪")}</span>
              </div>
            ) : null}
            {event.type === "win" ? (
              <div className={`win-banner win-banner--${game.winner}`}>
                <div className="win-banner__icon"><Icon name={game.winner === "wolf" ? "paw" : game.winner === "good" ? "sun" : "wave"} size={24} /></div>
                <div>
                  <b>{WINNER_LABEL[game.winner]}</b>
                  <span>{game.win_reason}</span>
                </div>
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function PlayersTab({ game }: { game: GameDetail }) {
  const players = [...game.detail.players].sort((a, b) => a.seat - b.seat);
  return (
    <div className="replay-players">
      {players.map((player) => (
        <div className={`replay-player ${!player.alive ? "is-dead" : ""}`} key={player.seat}>
          <div className="replay-player__seat">{player.seat}</div>
          <div className="replay-player__main">
            <div className="replay-player__name">
              <b>{player.name}</b>
              {player.is_variable ? <span className="variable-dot">变量</span> : null}
              {!player.alive ? <span className="dead-tag">第 {player.death_round} 轮出局</span> : null}
            </div>
            <div className="replay-player__meta">
              {player.age ? `${player.age}岁` : "—"} · {player.gender} · {player.occupation || "—"} · {player.province || "—"}
            </div>
            {player.checks?.length ? (
              <div className="replay-player__checks">
                {player.checks.map((check) => (
                  <span key={`${check.seat}-${check.round}`}>验 {check.seat}号 → {check.result === "wolf" ? "狼" : "好"}</span>
                ))}
              </div>
            ) : null}
          </div>
          <div className="replay-player__badges">
            <RoleBadge role={player.role} />
            <TypeBadge type={player.mbti} size="sm" />
          </div>
        </div>
      ))}
    </div>
  );
}

function DataTab({ game }: { game: GameDetail }) {
  return (
    <div className="replay-data">
      <div className="data-grid">
        <div><span>本局种子</span><b>{game.seed}</b></div>
        <div><span>板子</span><b>{game.detail.players.length} 人</b></div>
        <div><span>变量性格</span><b>{game.variable_type}</b></div>
        <div><span>变量角色</span><b>{roleSummary(game.variable_roles)}</b></div>
        <div><span>轮次</span><b>{game.rounds} / 8</b></div>
        <div><span>耗时</span><b>{formatDuration(game.duration_ms)}</b></div>
        <div><span>Token</span><b>{game.tokens.toLocaleString()}</b></div>
        <div><span>变量角色胜率</span><b>{game.variable_player_count ? pct(game.variable_player_wins / game.variable_player_count) : "—"}</b></div>
        <div><span>兜底标记</span><b>{game.degenerate ? "有" : "无"}</b></div>
      </div>
      <section className="data-section">
        <h4>轮次摘要</h4>
        <ul>
          {game.detail.round_summaries.map((item, index) => <li key={index}>{item}</li>)}
        </ul>
      </section>
      {game.detail.errors?.length ? (
        <section className="data-section">
          <h4>异常与兜底</h4>
          <ul className="data-errors">
            {game.detail.errors.map((error, index) => <li key={index}>{error.seat ? `${error.seat}号 · ` : ""}{error.error}</li>)}
          </ul>
        </section>
      ) : null}
      <section className="data-section">
        <h4>公开日志</h4>
        <div className="public-log">
          {game.detail.public_log.map((line, index) => <p key={index}>{line}</p>)}
        </div>
      </section>
    </div>
  );
}

function ThinkingModal({
  event,
  players,
  onClose,
}: {
  event: GameEvent | null;
  players: GamePlayer[];
  onClose: () => void;
}) {
  const speech = event as unknown as {
    seat?: number;
    name?: string;
    text?: string;
    thinking?: string;
    claimed_role?: string | null;
    accused?: number[];
    vote_intent?: number | null;
    state_repair?: number;
  } | null;
  const player = speech?.seat ? playerBySeat(players, speech.seat) : undefined;
  return (
    <Modal
      open={Boolean(event)}
      onClose={onClose}
      className="thinking-modal"
      size="sm"
      title={speech?.seat ? `${speech.seat} 号 · ${speech.name || ""} 的本轮思考` : "本轮思考"}
      subtitle={event ? `第 ${event.round} 轮 · 赛后可见，局中其他玩家看不到` : undefined}
    >
      {speech ? (
        <div className="thinking-card">
          <div className="thinking-card__who">
            {player ? <RoleBadge role={player.role} /> : null}
            {player ? <TypeBadge type={player.mbti} size="sm" /> : null}
            {speech.state_repair ? <span className="speech-tag speech-tag--repair">越界发言已修正</span> : null}
          </div>
          <div className="thinking-card__block">
            <span>内心判断</span>
            <p>{speech.thinking || "这一轮没有记录到内心独白。"}</p>
          </div>
          <div className="thinking-card__block">
            <span>公开发言</span>
            <p>{speech.text || "—"}</p>
          </div>
          <div className="thinking-card__facts">
            <div><span>声称身份</span><b>{speech.claimed_role || "未跳"}</b></div>
            <div><span>怀疑对象</span><b>{speech.accused?.length ? speech.accused.map((s) => `${s}号`).join("、") : "未点名"}</b></div>
            <div><span>投票倾向</span><b>{speech.vote_intent ? `${speech.vote_intent}号` : "未定/弃票"}</b></div>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}

export function GameDrawer({
  open,
  simId,
  gameNo,
  onClose,
}: {
  open: boolean;
  simId: string | null;
  gameNo: number | null;
  onClose: () => void;
}) {
  const [game, setGame] = useState<GameDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("replay");
  const [thinkingEvent, setThinkingEvent] = useState<GameEvent | null>(null);

  useEffect(() => {
    if (!open || !simId || !gameNo) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setGame(null);
    setTab("replay");
    setThinkingEvent(null);
    api.game(simId, gameNo)
      .then((data) => {
        if (!cancelled) setGame(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, simId, gameNo]);

  const title = useMemo(() => (gameNo ? `第 ${gameNo} 局复盘` : "对局复盘"), [gameNo]);

  return (
    <>
    <Drawer open={open} onClose={onClose} width={820} dark label={title}>
      <div className="replay-drawer">
        <div className="replay-drawer__head">
          <div>
            <div className="replay-drawer__eyebrow">GAME REPLAY · 赛后全知视角</div>
            <h2>{title}</h2>
            {game ? (
              <div className="replay-drawer__meta">
                <TypeBadge type={game.variable_type} size="sm" />
                <WinnerBadge winner={game.winner} size="sm" />
                <span>{game.rounds} 轮</span>
                <span>{formatDate(game.created_at)}</span>
              </div>
            ) : null}
          </div>
          <button type="button" className="icon-btn icon-btn--dark" onClick={onClose} aria-label="关闭">
            <Icon name="close" size={20} />
          </button>
        </div>
        {loading ? (
          <div className="drawer-loading"><Spinner size={26} /><span>正在读取对局记录…</span></div>
        ) : error ? (
          <EmptyState icon="alert" title="读取失败" desc={error} />
        ) : game ? (
          <>
            <Tabs
              value={tab}
              onChange={setTab}
              options={[
                { value: "replay", label: "复盘", icon: "play" },
                { value: "players", label: "玩家", icon: "users" },
                { value: "data", label: "数据", icon: "chart" },
              ]}
            />
            <div className="replay-drawer__body">
              {tab === "replay" ? <Replay game={game} onOpenSpeech={setThinkingEvent} /> : null}
              {tab === "players" ? <PlayersTab game={game} /> : null}
              {tab === "data" ? <DataTab game={game} /> : null}
            </div>
          </>
        ) : null}
      </div>
    </Drawer>
    <ThinkingModal
      event={thinkingEvent}
      players={game?.detail.players || []}
      onClose={() => setThinkingEvent(null)}
    />
    </>
  );
}
